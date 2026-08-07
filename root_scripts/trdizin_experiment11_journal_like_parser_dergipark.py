#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from trdizin_crossref_bibliographic_fallback import (
    CONTACT_EMAIL,
    best_candidate as best_crossref_candidate,
    first_text,
    issued_year,
    make_session as make_crossref_session,
    percent,
    search_crossref,
)
from trdizin_openalex_fallback import author_coverage, context_years, normalize_doi, title_coverage, title_similarity, tokens


JINA_READER_PREFIX = "https://r.jina.ai/http://r.jina.ai/http://"
DERGIPARK_OAI_BASE = "https://dergipark.org.tr/api/public/oai/"
YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20[0-3]\d)\b")
LEADING_REFNO_RE = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)])\s*")
VOLUME_PAGES_RE = re.compile(
    r"(?P<journal>[^.;]+?)\s*[,;]\s*(?P<year>18\d{2}|19\d{2}|20[0-3]\d)?\s*[,;]?\s*"
    r"(?P<volume>\d{1,4})\s*(?:\((?P<issue>[^)]{1,25})\))?\s*[:,]\s*(?P<pages>\d+\s*[-–]\s*\d+)",
    re.IGNORECASE,
)
TR_QUOTED_RE = re.compile(
    r"[\"“‘'](?P<title>[^\"”’']{12,250})[\"”’']\s*,?\s*(?P<journal>[^,.;()]{4,160})"
    r".*?(?P<year>18\d{2}|19\d{2}|20[0-3]\d).*?(?P<pages>\d+\s*[-–]\s*\d+)",
    re.IGNORECASE,
)


@dataclass
class ParsedReference:
    title: str = ""
    journal: str = ""
    year: str = ""
    authors: str = ""
    query: str = ""
    parser: str = "unparsed"


class RateLimiter:
    def __init__(self, max_rate: float) -> None:
        self.interval = 1.0 / max_rate if max_rate > 0 else 0.0
        self.lock = threading.Lock()
        self.next_time = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval
        if wait_seconds:
            time.sleep(wait_seconds)


def normalize_text(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def compact_spaces(value: str) -> str:
    return " ".join((value or "").replace("\u00ad", "").split()).strip()


def clean_context(context: str) -> str:
    value = html.unescape(context or "")
    value = LEADING_REFNO_RE.sub("", value)
    value = re.sub(r"\[(?:CrossRef|Crossref|PubMed|Link|Google Scholar)\]", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü])-\s+([A-Za-zÇĞİÖŞÜçğıöşü])", r"\1\2", value)
    return compact_spaces(value).strip(" .;,")


def useful_phrase(value: str, min_tokens: int = 4, max_tokens: int = 32) -> bool:
    count = len(tokens(value))
    return min_tokens <= count <= max_tokens


def trim_journal(value: str) -> str:
    value = compact_spaces(value).strip(" .;,:\"“”'[]()")
    value = re.sub(r"^(?:in|ve|and)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+(?:vol|cilt|sayı|sy)\.?$", "", value, flags=re.IGNORECASE)
    return value.strip(" .;,:")


def first_author_piece(prefix: str) -> str:
    prefix = compact_spaces(prefix)
    prefix = re.sub(r"\bet\s+al\.?", "", prefix, flags=re.IGNORECASE)
    pieces = re.split(r"\.\s+|\s+\(\d{4}\)|\s+(?:18|19|20)\d{2}\.?", prefix)
    candidate = pieces[0] if pieces else prefix
    return candidate.strip(" .;,")


def build_query(parsed: ParsedReference) -> str:
    pieces = [parsed.title, parsed.authors, parsed.journal, parsed.year]
    query = " ".join(piece for piece in pieces if piece)
    return compact_spaces(query)[:280].strip(" .;,")


def parse_reference(context: str) -> ParsedReference:
    text = clean_context(context)
    years = YEAR_RE.findall(text)
    first_year = years[0] if years else ""

    quoted = TR_QUOTED_RE.search(text)
    if quoted:
        title = compact_spaces(quoted.group("title"))
        journal = trim_journal(quoted.group("journal"))
        prefix = text[: quoted.start()]
        parsed = ParsedReference(title=title, journal=journal, year=quoted.group("year"), authors=first_author_piece(prefix), parser="quoted")
        parsed.query = build_query(parsed)
        return parsed

    # APA: Authors. (2018). Title. Journal, 12(3), 1-10.
    apa = re.search(
        r"^(?P<authors>.+?)\s*\((?P<year>18\d{2}|19\d{2}|20[0-3]\d)[a-z]?\)\.?\s+"
        r"(?P<title>.+?)\.\s+(?P<journal>[^.;]+?)\s*[,;]\s*\d{1,4}\s*(?:\([^)]{0,25}\))?\s*[:,]?\s*\d+\s*[-–]\s*\d+",
        text,
        re.IGNORECASE,
    )
    if apa and useful_phrase(apa.group("title")):
        parsed = ParsedReference(
            title=compact_spaces(apa.group("title")),
            journal=trim_journal(apa.group("journal")),
            year=apa.group("year"),
            authors=first_author_piece(apa.group("authors")),
            parser="apa",
        )
        parsed.query = build_query(parsed)
        return parsed

    # Vancouver: Authors. Title. Journal. 2015;8(1 Pt A):60-9.
    parts = [part.strip(" .;,") for part in re.split(r"\.\s+", text) if part.strip(" .;,")]
    for index in range(1, min(len(parts) - 1, 4)):
        title = parts[index]
        rest = ". ".join(parts[index + 1 :])
        match = re.search(
            r"(?P<journal>[^.;]+?)\s*[.;,]?\s*(?P<year>18\d{2}|19\d{2}|20[0-3]\d)\s*;\s*"
            r"\d{1,4}\s*(?:\([^)]{0,25}\))?\s*:\s*\d+\s*[-–]\s*\d+",
            rest,
            re.IGNORECASE,
        )
        if match and useful_phrase(title):
            parsed = ParsedReference(
                title=compact_spaces(title),
                journal=trim_journal(match.group("journal")),
                year=match.group("year"),
                authors=first_author_piece(parts[0]),
                parser="vancouver",
            )
            parsed.query = build_query(parsed)
            return parsed

    # Loose APA: Authors. Year. Title. Journal; 17(1): 252-266.
    loose = re.search(
        r"^(?P<authors>.+?)\s+(?P<year>18\d{2}|19\d{2}|20[0-3]\d)\.?\s+"
        r"(?P<title>.+?)\.\s+(?P<journal>[^.;]+?)\s*[;,]\s*\d{1,4}\s*(?:\([^)]{0,25}\))?\s*:\s*\d+\s*[-–]\s*\d+",
        text,
        re.IGNORECASE,
    )
    if loose and useful_phrase(loose.group("title")):
        parsed = ParsedReference(
            title=compact_spaces(loose.group("title")),
            journal=trim_journal(loose.group("journal")),
            year=loose.group("year"),
            authors=first_author_piece(loose.group("authors")),
            parser="loose_year",
        )
        parsed.query = build_query(parsed)
        return parsed

    # Last resort: infer title as sentence before journal/volume/pages.
    vp = list(VOLUME_PAGES_RE.finditer(text))
    if vp:
        match = vp[-1]
        before = text[: match.start()].strip(" .;,")
        pieces = [piece.strip(" .;,") for piece in re.split(r"\.\s+", before) if piece.strip(" .;,")]
        if len(pieces) >= 2:
            title = pieces[-1]
            authors = first_author_piece(pieces[0])
            if useful_phrase(title):
                parsed = ParsedReference(
                    title=compact_spaces(title),
                    journal=trim_journal(match.group("journal")),
                    year=match.group("year") or first_year,
                    authors=authors,
                    parser="volume_pages",
                )
                parsed.query = build_query(parsed)
                return parsed

    return ParsedReference(year=first_year, parser="unparsed")


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_csv(path: Path, fieldnames: Sequence[str], rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_cache(path: Path, cache: Dict[str, Dict[str, Any]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def safe_crossref_score(score: Any) -> bool:
    if score.match_status not in {"strong", "possible"}:
        return False
    if score.title_token_count < 6:
        return False
    if score.title_coverage < 0.9:
        return False
    if not score.year_match:
        return False
    if score.author_coverage < 0.34 and score.title_similarity < 0.97:
        return False
    return True


def compact_crossref_output(work: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doi": normalize_doi(work.get("DOI") or ""),
        "title": first_text(work.get("title")) or "",
        "publisher": work.get("publisher") or "",
        "year": issued_year(work) or "",
        "score": work.get("score") or "",
    }


def fetch_crossref_key(
    key: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    rate_limiter: RateLimiter,
) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_crossref_session()
    result = search_crossref(session, key, rows, timeout, retries, sleep_seconds)
    if sleep_seconds:
        time.sleep(sleep_seconds)
    return key, result


def fill_crossref_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    queries: Sequence[str],
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    workers: int,
    max_start_rate: float,
    save_every: int,
) -> None:
    missing = [query for query in queries if query and query not in cache]
    if not missing:
        return
    completed = 0
    dirty = False
    rate_limiter = RateLimiter(max_start_rate)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_crossref_key, query, rows, timeout, retries, sleep_seconds, rate_limiter): query
            for query in missing
        }
        for future in as_completed(futures):
            query, result = future.result()
            if result.get("status") != "rate_limited":
                cache[query] = result
                dirty = True
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
                print(f"cached {completed}/{len(missing)} structured Crossref requests", flush=True)
    if dirty:
        save_cache(cache_path, cache)


def jina_url(url: str) -> str:
    return f"{JINA_READER_PREFIX}{url}"


def request_jina(url: str, timeout: float) -> Dict[str, Any]:
    try:
        response = requests.get(jina_url(url), timeout=timeout)
    except requests.RequestException as exc:
        return {"status": "error", "error": str(exc)}
    if response.status_code != 200:
        return {"status": "error", "http_status": response.status_code, "error": response.text[:250]}
    return {"status": "ok", "markdown": response.text}


def parse_dergipark_sets(markdown: str) -> List[Dict[str, str]]:
    sets: List[Dict[str, str]] = []
    pattern = re.compile(r"setName\s+(.+?)\s+setSpec\s+([A-Za-z0-9_.-]+)\s+", re.DOTALL)
    for match in pattern.finditer(markdown or ""):
        name = compact_spaces(match.group(1))
        spec = match.group(2).strip()
        if name and spec:
            sets.append({"set_name": name, "set_spec": spec})
    return sets


def set_similarity(journal: str, set_name: str) -> float:
    j_norm = normalize_text(journal)
    s_norm = normalize_text(set_name)
    if not j_norm or not s_norm:
        return 0.0
    if j_norm in s_norm or s_norm in j_norm:
        return 1.0
    j_tokens = set(j_norm.split())
    s_tokens = set(s_norm.split())
    overlap = len(j_tokens & s_tokens) / max(1, len(j_tokens | s_tokens))
    seq = SequenceMatcher(None, j_norm, s_norm).ratio()
    return round((overlap * 0.65) + (seq * 0.35), 4)


def load_dergipark_sets(cache_path: Path, timeout: float) -> List[Dict[str, str]]:
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
    result = request_jina(f"{DERGIPARK_OAI_BASE}?verb=ListSets", timeout)
    sets = parse_dergipark_sets(result.get("markdown") or "") if result.get("status") == "ok" else []
    write_json(cache_path, sets)
    return sets


def choose_dergipark_sets(parsed_rows: List[Dict[str, Any]], sets: List[Dict[str, str]], threshold: float, max_sets: int) -> List[Dict[str, Any]]:
    best_by_spec: Dict[str, Dict[str, Any]] = {}
    for row in parsed_rows:
        journal = row.get("parsed_journal") or ""
        if not journal:
            continue
        best: Optional[Dict[str, Any]] = None
        for item in sets:
            score = set_similarity(journal, item["set_name"])
            if score >= threshold and (best is None or score > best["set_match_score"]):
                best = {**item, "set_match_score": score, "matched_journal": journal}
        if not best:
            continue
        current = best_by_spec.get(best["set_spec"])
        if current is None or best["set_match_score"] > current["set_match_score"]:
            best_by_spec[best["set_spec"]] = best
        best_by_spec[best["set_spec"]]["target_count"] = best_by_spec[best["set_spec"]].get("target_count", 0) + 1
    return sorted(best_by_spec.values(), key=lambda item: (item["set_match_score"], item["target_count"]), reverse=True)[:max_sets]


def parse_dergipark_records(markdown: str, set_spec: str, set_name: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    chunks = re.split(r"\n## OAI Record:\s*", markdown or "")
    for chunk in chunks[1:]:
        lines = chunk.splitlines()
        record_id = lines[0].strip() if lines else ""
        title = ""
        creators: List[str] = []
        identifiers: List[str] = []
        year: Optional[int] = None
        source = ""
        for raw in lines[1:]:
            line = raw.strip()
            if line.startswith("Title ") and not title:
                title = compact_spaces(line.removeprefix("Title "))
            elif line.startswith("Author or Creator "):
                creators.append(compact_spaces(line.removeprefix("Author or Creator ")))
            elif line.startswith("Resource Identifier "):
                identifiers.append(compact_spaces(line.removeprefix("Resource Identifier ")))
            elif line.startswith("Source ") and not source:
                source = compact_spaces(line.removeprefix("Source "))
            elif line.startswith("Date ") and year is None:
                match = YEAR_RE.search(line)
                if match:
                    year = int(match.group(1))
        doi = ""
        url = ""
        for identifier in identifiers:
            normalized = normalize_doi(identifier)
            if normalized.startswith("10."):
                doi = normalized
            if identifier.startswith("http"):
                url = identifier
        if title:
            records.append(
                {
                    "oai_identifier": record_id,
                    "set_spec": set_spec,
                    "set_name": set_name,
                    "title": title,
                    "creators": creators,
                    "year": year,
                    "doi": doi,
                    "url": url,
                    "source": source or set_name,
                }
            )
    return records


def harvest_dergipark_records(
    cache_path: Path,
    candidate_sets: List[Dict[str, Any]],
    timeout: float,
    sleep_seconds: float,
) -> Tuple[List[Dict[str, Any]], int, int]:
    cache = load_cache(cache_path)
    records: List[Dict[str, Any]] = []
    errors = 0
    fetched = 0
    for index, item in enumerate(candidate_sets, start=1):
        spec = item["set_spec"]
        if spec not in cache:
            url = f"{DERGIPARK_OAI_BASE}?verb=ListRecords&metadataPrefix=oai_dc&set={spec}"
            result = request_jina(url, timeout)
            if result.get("status") == "ok":
                parsed = parse_dergipark_records(result.get("markdown") or "", spec, item["set_name"])
                cache[spec] = {"status": "ok", "records": parsed}
                fetched += 1
            else:
                cache[spec] = {"status": "error", "error": result.get("error") or ""}
                errors += 1
            save_cache(cache_path, cache)
            if sleep_seconds:
                time.sleep(sleep_seconds)
        cached = cache.get(spec) or {}
        if cached.get("status") == "ok":
            records.extend(cached.get("records") or [])
        elif cached.get("status") == "error":
            errors += 1
        print(f"DergiPark set {index}/{len(candidate_sets)} indexed: {spec}", flush=True)
    return records, fetched, errors


def dergipark_author_surnames(creators: Sequence[str]) -> List[str]:
    surnames: List[str] = []
    for creator in creators:
        name = creator.split(",", 1)[0] if "," in creator else creator
        name_tokens = tokens(name)
        if name_tokens:
            surnames.append(name_tokens[-1])
    return surnames


def dergipark_score(record: Dict[str, Any], context: str) -> Dict[str, Any]:
    title = record.get("title") or ""
    title_token_count = len(tokens(title))
    coverage = title_coverage(title, context)
    similarity = title_similarity(title, context)
    author_ratio = author_coverage(dergipark_author_surnames(record.get("creators") or []), context)
    year = record.get("year")
    year_match = bool(year and year in context_years(context))
    confidence = round((coverage * 0.56) + (similarity * 0.22) + (author_ratio * 0.14) + ((1.0 if year_match else 0.0) * 0.08), 4)
    status = "no_match"
    if title_token_count >= 5 and coverage >= 0.88 and (year_match or author_ratio >= 0.34):
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.78 and author_ratio >= 0.34 and year_match:
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.70 and author_ratio >= 0.34:
        status = "possible"
    return {
        "status": status,
        "confidence": confidence,
        "title_coverage": round(coverage, 4),
        "title_similarity": round(similarity, 4),
        "title_token_count": title_token_count,
        "author_coverage": round(author_ratio, 4),
        "year_match": year_match,
        "record": record,
    }


def best_dergipark_record(records: List[Dict[str, Any]], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    parsed_journal = row.get("parsed_journal") or ""
    candidate_records = [
        record for record in records if not parsed_journal or set_similarity(parsed_journal, record.get("set_name") or "") >= 0.55
    ]
    scored = [dergipark_score(record, row.get("context") or "") for record in candidate_records]
    scored = [score for score in scored if score["status"] in {"strong", "possible"}]
    if not scored:
        return None
    rank = {"strong": 2, "possible": 1}
    return max(scored, key=lambda item: (rank[item["status"]], item["confidence"], item["title_coverage"]))


def output_rows(
    parsed_rows: List[Dict[str, Any]],
    crossref_cache: Dict[str, Dict[str, Any]],
    dergipark_records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in parsed_rows:
        crossref_status = "not_checked" if not row.get("crossref_query") else "no_match"
        crossref_output: Dict[str, Any] = {}
        result = crossref_cache.get(row.get("crossref_query") or "")
        if result and result.get("status") == "ok":
            score = best_crossref_candidate(result.get("items") or [], row.get("context") or "")
            if score and safe_crossref_score(score):
                crossref_status = "strong"
                crossref_output = compact_crossref_output(score.candidate)
        elif result and result.get("status") in {"error", "rate_limited"}:
            crossref_status = "search_error"

        dergipark_match = best_dergipark_record(dergipark_records, row)
        dergipark_status = "no_match" if dergipark_records else "not_checked"
        dergipark_record: Dict[str, Any] = {}
        if dergipark_match:
            dergipark_status = dergipark_match["status"]
            dergipark_record = dergipark_match["record"]

        final_status = "no_match"
        final_source = ""
        if crossref_status == "strong":
            final_status = "strong"
            final_source = "crossref_structured"
        elif dergipark_status == "strong":
            final_status = "strong"
            final_source = "dergipark_index"
        elif dergipark_status == "possible":
            final_status = "possible"
            final_source = "dergipark_index"

        rows.append(
            {
                **row,
                "crossref_status": crossref_status,
                "crossref_doi": crossref_output.get("doi", ""),
                "crossref_title": crossref_output.get("title", ""),
                "crossref_year": crossref_output.get("year", ""),
                "dergipark_status": dergipark_status,
                "dergipark_oai_identifier": dergipark_record.get("oai_identifier", ""),
                "dergipark_doi": dergipark_record.get("doi", ""),
                "dergipark_title": dergipark_record.get("title", ""),
                "dergipark_year": dergipark_record.get("year", ""),
                "dergipark_set": dergipark_record.get("set_spec", ""),
                "final_status": final_status,
                "final_source": final_source,
            }
        )
    return rows


def build_summary(
    total: int,
    base_found: int,
    target_count: int,
    parsed_rows: List[Dict[str, Any]],
    output: List[Dict[str, Any]],
    set_count: int,
    indexed_record_count: int,
    harvest_errors: int,
) -> Dict[str, Any]:
    strong = sum(1 for row in output if row["final_status"] == "strong")
    possible = sum(1 for row in output if row["final_status"] == "possible")
    crossref_strong = sum(1 for row in output if row["crossref_status"] == "strong")
    dergipark_strong = sum(1 for row in output if row["dergipark_status"] == "strong")
    dergipark_possible = sum(1 for row in output if row["dergipark_status"] == "possible")
    parsed_count = sum(1 for row in parsed_rows if row.get("parsed_title"))
    journal_count = sum(1 for row in parsed_rows if row.get("parsed_journal"))
    strict = base_found + strong
    broad = base_found + strong + possible
    return {
        "experiment_label": "Deney 11 - Journal-like parser + DergiPark local index",
        "sampled_references": total,
        "base_found_before_experiment11": base_found,
        "base_found_before_experiment11_rate_percent": percent(base_found, total),
        "experiment11_target_journal_like": target_count,
        "advanced_parser_title_count": parsed_count,
        "advanced_parser_journal_count": journal_count,
        "dergipark_candidate_sets": set_count,
        "dergipark_indexed_records": indexed_record_count,
        "dergipark_harvest_errors": harvest_errors,
        "crossref_structured_strong_matches": crossref_strong,
        "dergipark_index_strong_matches": dergipark_strong,
        "dergipark_index_possible_matches": dergipark_possible,
        "experiment11_strong_matches": strong,
        "experiment11_possible_matches": possible,
        "experiment11_strict_found": strict,
        "experiment11_strict_found_rate_percent": percent(strict, total),
        "experiment11_broad_found": broad,
        "experiment11_broad_found_rate_percent": percent(broad, total),
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Deney 11 - Journal-like Parser + DergiPark Local Index",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 11 oncesi baz bulunan: {summary['base_found_before_experiment11']} ({summary['base_found_before_experiment11_rate_percent']}%)",
        f"- Journal-like hedef: {summary['experiment11_target_journal_like']}",
        f"- Parse edilen baslik: {summary['advanced_parser_title_count']}",
        f"- Parse edilen dergi: {summary['advanced_parser_journal_count']}",
        f"- DergiPark aday set: {summary['dergipark_candidate_sets']}",
        f"- DergiPark index kaydi: {summary['dergipark_indexed_records']}",
        f"- DergiPark harvest error: {summary['dergipark_harvest_errors']}",
        f"- Crossref structured strong: {summary['crossref_structured_strong_matches']}",
        f"- DergiPark index strong: {summary['dergipark_index_strong_matches']}",
        f"- DergiPark index possible: {summary['dergipark_index_possible_matches']}",
        "",
        "## Deney 11 Sonuc",
        "",
        f"- Strong yeni eslesme: {summary['experiment11_strong_matches']}",
        f"- Possible yeni eslesme: {summary['experiment11_possible_matches']}",
        f"- Strict toplam: {summary['experiment11_strict_found']} ({summary['experiment11_strict_found_rate_percent']}%)",
        f"- Broad toplam: {summary['experiment11_broad_found']} ({summary['experiment11_broad_found_rate_percent']}%)",
        "",
        "Not: DergiPark OAI title search degildir; burada erisilebilen setlerden lokal metadata index kurularak fuzzy title/year/author eslesmesi yapilir.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experiment 11 for journal-like remaining references.")
    parser.add_argument("--remaining-csv", default=Path("trdizin_crossref_doi_stats_10k/remaining_after_experiment10/remaining_after_experiment10_references.csv"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/experiment11_journal_like"), type=Path)
    parser.add_argument("--base-found", default=6123, type=int)
    parser.add_argument("--sampled", default=10000, type=int)
    parser.add_argument("--crossref-rows", default=5, type=int)
    parser.add_argument("--timeout", default=35.0, type=float)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--max-start-rate", default=8.0, type=float)
    parser.add_argument("--save-every", default=100, type=int)
    parser.add_argument("--dergipark-set-threshold", default=0.72, type=float)
    parser.add_argument("--max-dergipark-sets", default=30, type=int)
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    remaining_rows = [row for row in read_csv(args.remaining_csv) if row.get("exclusive_category") == "journal_like_left"]

    parsed_rows: List[Dict[str, Any]] = []
    for row in remaining_rows:
        parsed = parse_reference(row.get("context") or "")
        parsed_rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "parsed_title": parsed.title,
                "parsed_journal": parsed.journal,
                "parsed_year": parsed.year,
                "parsed_authors": parsed.authors,
                "parser": parsed.parser,
                "crossref_query": parsed.query,
                "context": row.get("context", ""),
            }
        )

    crossref_cache_path = args.out_dir / "experiment11_crossref_cache.json"
    crossref_cache = load_cache(crossref_cache_path)
    queries = sorted({row["crossref_query"] for row in parsed_rows if row.get("crossref_query") and row.get("parsed_title")})
    print(f"journal_like={len(remaining_rows)} parsed_queries={len(queries)}", flush=True)
    if queries and not args.score_only:
        fill_crossref_cache(
            cache_path=crossref_cache_path,
            cache=crossref_cache,
            queries=queries,
            rows=args.crossref_rows,
            timeout=args.timeout,
            retries=args.retries,
            sleep_seconds=args.sleep,
            workers=args.workers,
            max_start_rate=args.max_start_rate,
            save_every=args.save_every,
        )

    set_cache_path = args.out_dir / "experiment11_dergipark_sets.json"
    sets = load_dergipark_sets(set_cache_path, args.timeout)
    candidate_sets = choose_dergipark_sets(parsed_rows, sets, args.dergipark_set_threshold, args.max_dergipark_sets)
    write_json(args.out_dir / "experiment11_dergipark_candidate_sets.json", candidate_sets)
    dergipark_records: List[Dict[str, Any]] = []
    fetched_sets = 0
    harvest_errors = 0
    if candidate_sets and not args.score_only:
        dergipark_records, fetched_sets, harvest_errors = harvest_dergipark_records(
            cache_path=args.out_dir / "experiment11_dergipark_index_cache.json",
            candidate_sets=candidate_sets,
            timeout=args.timeout,
            sleep_seconds=args.sleep,
        )
    else:
        index_cache = load_cache(args.out_dir / "experiment11_dergipark_index_cache.json")
        for item in index_cache.values():
            if item.get("status") == "ok":
                dergipark_records.extend(item.get("records") or [])
            elif item.get("status") == "error":
                harvest_errors += 1

    output = output_rows(parsed_rows, crossref_cache, dergipark_records)
    summary = build_summary(
        total=args.sampled,
        base_found=args.base_found,
        target_count=len(remaining_rows),
        parsed_rows=parsed_rows,
        output=output,
        set_count=len(candidate_sets),
        indexed_record_count=len(dergipark_records),
        harvest_errors=harvest_errors,
    )

    write_csv(
        args.out_dir / "experiment11_parsed_targets.csv",
        [
            "sample_index",
            "publication_id",
            "reference_id",
            "reference_order",
            "parsed_title",
            "parsed_journal",
            "parsed_year",
            "parsed_authors",
            "parser",
            "crossref_query",
            "context",
        ],
        parsed_rows,
    )
    write_jsonl(args.out_dir / "experiment11_matches.jsonl", output)
    write_csv(
        args.out_dir / "experiment11_matches.csv",
        [
            "sample_index",
            "publication_id",
            "reference_id",
            "reference_order",
            "parsed_title",
            "parsed_journal",
            "parsed_year",
            "parser",
            "crossref_status",
            "crossref_doi",
            "crossref_title",
            "crossref_year",
            "dergipark_status",
            "dergipark_oai_identifier",
            "dergipark_doi",
            "dergipark_title",
            "dergipark_year",
            "dergipark_set",
            "final_status",
            "final_source",
            "context",
        ],
        output,
    )
    write_json(args.out_dir / "experiment11_summary.json", summary)
    write_report(args.out_dir / "experiment11_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
