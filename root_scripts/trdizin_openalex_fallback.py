#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET

import requests


CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_SELECT = "id,doi,title,display_name,publication_year,authorships,primary_location,relevance_score,type"
WORD_RE = re.compile(r"[a-z0-9]+")
YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-3][0-9])\b")
DOI_URL_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/\S+|doi\s*[:.]?\s*10\.\d{4,9}/\S+|10\.\d{4,9}/\S+)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
BRACKET_CROSSREF_RE = re.compile(r"\[(?:crossref|pubmed|google scholar)\s*\]", re.IGNORECASE)
LEADING_REFNO_RE = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)])\s*")

STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "using",
    "based",
    "study",
    "analysis",
    "review",
    "article",
    "book",
    "bir",
    "ve",
    "ile",
    "icin",
    "uzerine",
    "dergisi",
    "journal",
}


@dataclass
class CandidateScore:
    match_status: str
    confidence: float
    title_coverage: float
    title_similarity: float
    title_token_count: int
    author_coverage: float
    year_match: bool
    candidate: Dict[str, Any]


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


def normalize_doi(value: str) -> str:
    doi = unquote(value or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*[:.]?\s*)", "", doi, flags=re.IGNORECASE)
    doi = doi.strip(" \t\r\n\"'<>[]{}")
    doi = re.split(r"[#?]", doi, maxsplit=1)[0]
    return doi.rstrip(".,;:").lower()


def normalize_text(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(WORD_RE.findall(value))


def tokens(value: str) -> List[str]:
    return [token for token in normalize_text(value).split() if len(token) > 2 and token not in STOPWORDS]


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def first_text(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return " ".join(value.split())
    return None


def openalex_title(work: Dict[str, Any]) -> str:
    return first_text(work.get("title")) or first_text(work.get("display_name")) or ""


def openalex_year(work: Dict[str, Any]) -> Optional[int]:
    year = work.get("publication_year")
    return year if isinstance(year, int) else None


def openalex_author_surnames(work: Dict[str, Any]) -> List[str]:
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return []
    surnames: List[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        display_name = ""
        if isinstance(author, dict) and isinstance(author.get("display_name"), str):
            display_name = author["display_name"]
        raw_name = authorship.get("raw_author_name")
        if isinstance(raw_name, str) and raw_name.strip():
            display_name = raw_name
        name_tokens = tokens(display_name)
        if name_tokens:
            surnames.append(name_tokens[-1])
    return surnames


def compact_work(work: Dict[str, Any]) -> Dict[str, Any]:
    source_title = ""
    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        source = primary_location.get("source")
        if isinstance(source, dict) and isinstance(source.get("display_name"), str):
            source_title = source["display_name"]

    authors: List[str] = []
    authorships = work.get("authorships")
    if isinstance(authorships, list):
        for authorship in authorships[:8]:
            if not isinstance(authorship, dict):
                continue
            raw_name = authorship.get("raw_author_name")
            author = authorship.get("author")
            if isinstance(raw_name, str) and raw_name.strip():
                authors.append(raw_name.strip())
            elif isinstance(author, dict) and isinstance(author.get("display_name"), str):
                authors.append(author["display_name"].strip())

    return {
        "id": work.get("id") or "",
        "doi": normalize_doi(str(work.get("doi") or "")),
        "title": openalex_title(work),
        "publication_year": openalex_year(work),
        "source_title": source_title,
        "relevance_score": work.get("relevance_score"),
        "type": work.get("type") or "",
        "authors": authors,
        "authorships": work.get("authorships") if isinstance(work.get("authorships"), list) else [],
    }


def clean_reference_query(context: str, doi: Optional[str]) -> str:
    query = html.unescape(context or "")
    if doi:
        query = re.sub(re.escape(doi), " ", query, flags=re.IGNORECASE)
    query = DOI_URL_RE.sub(" ", query)
    query = URL_RE.sub(" ", query)
    query = BRACKET_CROSSREF_RE.sub(" ", query)
    query = LEADING_REFNO_RE.sub("", query)
    query = re.sub(r"\s+", " ", query)
    return query.strip(" .;,")


def limit_query(query: str, max_chars: int) -> str:
    if max_chars <= 0 or len(query) <= max_chars:
        return query
    limited = query[:max_chars].rsplit(" ", 1)[0]
    return limited.strip(" .;,") or query[:max_chars].strip(" .;,")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def child_with_attr(element: ET.Element, tag: str, attr: str, value: str) -> Optional[ET.Element]:
    for child in element.iter():
        if local_name(child.tag) == tag and child.get(attr) == value:
            return child
    return None


def tei_query_for_reference(
    tei_dir: Optional[Path],
    publication_id: Optional[str],
    reference_order: Optional[str],
) -> Optional[str]:
    if not tei_dir or not publication_id or not reference_order:
        return None
    path = tei_dir / f"{publication_id}.training.references.tei.xml"
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    try:
        wanted_order = int(reference_order)
    except (TypeError, ValueError):
        return None

    for bibl in root.iter():
        if local_name(bibl.tag) != "bibl":
            continue
        text = element_text(bibl)
        match = re.match(r"\s*(\d+)\s*[.)]", text)
        if not match or int(match.group(1)) != wanted_order:
            continue
        article_title = element_text(child_with_attr(bibl, "title", "level", "a"))
        main_title = article_title or element_text(child_with_attr(bibl, "title", "level", "m"))
        journal_title = element_text(child_with_attr(bibl, "title", "level", "j"))
        author = element_text(next((child for child in bibl.iter() if local_name(child.tag) == "author"), None))
        date = element_text(next((child for child in bibl.iter() if local_name(child.tag) == "date"), None))
        pieces = [main_title, author.split(",")[0], date, journal_title]
        query = " ".join(piece for piece in pieces if piece)
        return " ".join(query.split()) or None
    return None


def context_years(context: str) -> set[int]:
    return {int(year) for year in YEAR_RE.findall(context or "")}


def title_coverage(title: str, context: str) -> float:
    title_tokens = tokens(title)
    if not title_tokens:
        return 0.0
    context_tokens = set(tokens(context))
    return len([token for token in title_tokens if token in context_tokens]) / len(title_tokens)


def title_similarity(title: str, context: str) -> float:
    title_norm = normalize_text(title)
    context_norm = normalize_text(context)
    if not title_norm or not context_norm:
        return 0.0
    if title_norm in context_norm:
        return 1.0
    return SequenceMatcher(None, title_norm, context_norm).ratio()


def author_coverage(surnames: Sequence[str], context: str) -> float:
    if not surnames:
        return 0.0
    context_tokens = set(tokens(context))
    usable = [surname for surname in surnames if len(surname) > 2]
    if not usable:
        return 0.0
    matched = sum(1 for surname in usable if surname in context_tokens)
    denominator = min(len(usable), 3)
    return min(matched, denominator) / denominator


def score_candidate(work: Dict[str, Any], context: str) -> CandidateScore:
    title = openalex_title(work)
    title_token_count = len(tokens(title))
    coverage = title_coverage(title, context)
    similarity = title_similarity(title, context)
    surnames = openalex_author_surnames(work)
    author_ratio = author_coverage(surnames, context)
    year = openalex_year(work)
    years = context_years(context)
    has_year_match = bool(year and year in years)

    confidence = (
        (coverage * 0.55)
        + (similarity * 0.20)
        + (min(author_ratio, 1.0) * 0.15)
        + ((1.0 if has_year_match else 0.0) * 0.10)
    )

    if similarity >= 0.98 and (has_year_match or author_ratio >= 0.34):
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.88 and (has_year_match or author_ratio >= 0.34):
        status = "strong"
    elif title_token_count >= 8 and coverage >= 0.78 and author_ratio >= 0.34 and has_year_match:
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.68 and (has_year_match or author_ratio >= 0.34):
        status = "possible"
    elif title_token_count >= 8 and coverage >= 0.58 and author_ratio >= 0.34:
        status = "possible"
    else:
        status = "no_match"

    return CandidateScore(
        match_status=status,
        confidence=round(confidence, 4),
        title_coverage=round(coverage, 4),
        title_similarity=round(similarity, 4),
        title_token_count=title_token_count,
        author_coverage=round(author_ratio, 4),
        year_match=has_year_match,
        candidate=work,
    )


def best_candidate(items: List[Dict[str, Any]], context: str) -> Optional[CandidateScore]:
    scored = [score_candidate(item, context) for item in items]
    if not scored:
        return None
    status_rank = {"strong": 2, "possible": 1, "no_match": 0}
    return max(scored, key=lambda item: (status_rank[item.match_status], item.confidence, item.candidate.get("relevance_score") or 0))


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


def make_session(api_key: Optional[str]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": f"trdizin-openalex-fallback/0.1 (mailto:{CONTACT_EMAIL})",
        }
    )
    if api_key:
        session.params = {"api_key": api_key}
    return session


def response_limit_info(response: requests.Response) -> Dict[str, Any]:
    wanted = [
        "x-ratelimit-credits-used",
        "x-ratelimit-remaining",
        "x-ratelimit-limit",
        "x-ratelimit-reset",
        "x-ratelimit-cost-usd",
        "x-ratelimit-remaining-usd",
    ]
    return {key: response.headers.get(key) for key in wanted if response.headers.get(key) is not None}


def request_json(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt)))
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue

        limit_info = response_limit_info(response)
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                return {"status": "error", "http_status": 200, "error": "invalid json", "rate_limit": limit_info}
            return {"status": "ok", "http_status": 200, "payload": payload, "rate_limit": limit_info}
        if response.status_code == 404:
            return {"status": "not_found", "http_status": 404, "rate_limit": limit_info}
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after) if retry_after else 0.0
            except ValueError:
                wait_seconds = 0.0
            last_error = "HTTP 429"
            if attempt < retries:
                time.sleep(max(wait_seconds, 3.0 * (attempt + 1), sleep_seconds))
                continue
            return {"status": "rate_limited", "http_status": 429, "error": last_error, "rate_limit": limit_info}
        if response.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {response.status_code}"
            continue
        return {
            "status": "error",
            "http_status": response.status_code,
            "error": response.text[:300],
            "rate_limit": limit_info,
        }
    return {"status": "error", "http_status": None, "error": last_error or "request failed"}


def lookup_openalex_doi(
    session: requests.Session,
    doi: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    url = f"{OPENALEX_WORKS_URL}/doi:{quote(doi, safe='')}"
    result = request_json(
        session=session,
        url=url,
        params={"select": OPENALEX_SELECT, "mailto": CONTACT_EMAIL},
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    if result.get("status") == "ok" and isinstance(result.get("payload"), dict):
        return {
            "status": "ok",
            "http_status": result.get("http_status"),
            "items": [compact_work(result["payload"])],
            "rate_limit": result.get("rate_limit", {}),
        }
    return result


def search_openalex(
    session: requests.Session,
    query: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    result = request_json(
        session=session,
        url=OPENALEX_WORKS_URL,
        params={
            "search": query,
            "per-page": rows,
            "select": OPENALEX_SELECT,
            "mailto": CONTACT_EMAIL,
        },
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    if result.get("status") == "ok" and isinstance(result.get("payload"), dict):
        items = result["payload"].get("results")
        if not isinstance(items, list):
            items = []
        return {
            "status": "ok",
            "http_status": result.get("http_status"),
            "items": [compact_work(item) for item in items if isinstance(item, dict)],
            "rate_limit": result.get("rate_limit", {}),
        }
    return result


def fetch_request_key(
    key: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    api_key: Optional[str],
    rate_limiter: Optional[RateLimiter],
) -> Tuple[str, Dict[str, Any]]:
    if rate_limiter:
        rate_limiter.wait()
    session = make_session(api_key)
    kind, value = key.split(":", 1)
    if kind == "doi":
        result = lookup_openalex_doi(session, value, timeout, retries, sleep_seconds)
    elif kind == "search":
        result = search_openalex(session, value, rows, timeout, retries, sleep_seconds)
    else:
        result = {"status": "error", "error": f"unknown key kind: {kind}"}
    if sleep_seconds:
        time.sleep(sleep_seconds)
    return key, result


def fill_missing_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    missing_keys: Sequence[str],
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    api_key: Optional[str],
    workers: int,
    max_start_rate: float,
    save_every: int,
    batch_size: int = 200,
) -> None:
    if not missing_keys:
        return

    completed = 0
    dirty = False
    if workers <= 1:
        rate_limiter = RateLimiter(max_start_rate)
        for key in missing_keys:
            request_key, result = fetch_request_key(
                key=key,
                rows=rows,
                timeout=timeout,
                retries=retries,
                sleep_seconds=sleep_seconds,
                api_key=api_key,
                rate_limiter=rate_limiter,
            )
            if result.get("status") != "rate_limited":
                cache[request_key] = result
                dirty = True
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
                print(f"cached {completed}/{len(missing_keys)} OpenAlex requests", flush=True)
            if result.get("status") == "rate_limited":
                print(f"rate limited after {completed}/{len(missing_keys)} requests", flush=True)
                break
        if dirty:
            save_cache(cache_path, cache)
        return

    stop_for_rate_limit = False
    for start in range(0, len(missing_keys), batch_size):
        batch = missing_keys[start : start + batch_size]
        rate_limiter = RateLimiter(max_start_rate)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    fetch_request_key,
                    key,
                    rows,
                    timeout,
                    retries,
                    sleep_seconds,
                    api_key,
                    rate_limiter,
                ): key
                for key in batch
            }
            for future in as_completed(futures):
                request_key, result = future.result()
                if result.get("status") == "rate_limited":
                    stop_for_rate_limit = True
                else:
                    cache[request_key] = result
                    dirty = True
                completed += 1
                if completed % save_every == 0:
                    save_cache(cache_path, cache)
                    dirty = False
                    print(f"cached {completed}/{len(missing_keys)} OpenAlex requests", flush=True)
        if dirty:
            save_cache(cache_path, cache)
            dirty = False
        if stop_for_rate_limit:
            print(f"rate limited after {completed}/{len(missing_keys)} requests", flush=True)
            break


def build_crossref_sets(
    sample_rows: List[Dict[str, str]],
    stq_rows: List[Dict[str, str]],
    doi_fallback_rows: List[Dict[str, str]],
    no_doi_fallback_rows: List[Dict[str, str]],
) -> Dict[str, set[str]]:
    doi_found = {row["sample_index"] for row in sample_rows if row.get("crossref_status") == "found"}
    stq_found = {row["sample_index"] for row in stq_rows if truthy(row.get("stq_found", ""))}
    fallback_strong = {
        row["sample_index"]
        for row in [*doi_fallback_rows, *no_doi_fallback_rows]
        if row.get("fallback_status") == "strong"
    }
    fallback_possible = {
        row["sample_index"]
        for row in [*doi_fallback_rows, *no_doi_fallback_rows]
        if row.get("fallback_status") == "possible"
    }
    strict = doi_found | fallback_strong
    broad = strict | fallback_possible
    return {
        "doi": doi_found,
        "strict": strict,
        "broad": broad,
        "stq": stq_found,
        "union": broad | stq_found,
    }


def target_indexes_for_scope(scope: str, crossref_sets: Dict[str, set[str]], all_indexes: set[str]) -> set[str]:
    if scope == "stq_not_found":
        return all_indexes - crossref_sets["stq"]
    if scope == "crossref_strict_not_found":
        return all_indexes - crossref_sets["strict"]
    if scope == "crossref_broad_not_found":
        return all_indexes - crossref_sets["broad"]
    if scope == "crossref_union_not_found":
        return all_indexes - crossref_sets["union"]
    raise ValueError(f"Unknown scope: {scope}")


def build_target_rows(
    sample_rows: List[Dict[str, str]],
    target_indexes: set[str],
    tei_dir: Optional[Path],
    max_query_chars: int,
) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for row in sample_rows:
        if row["sample_index"] not in target_indexes:
            continue
        doi = normalize_doi(row.get("doi", ""))
        tei_query = tei_query_for_reference(tei_dir, row.get("publication_id"), row.get("reference_order"))
        raw_query = clean_reference_query(row.get("context", ""), doi)
        query = limit_query(tei_query or raw_query, max_query_chars)
        targets.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "source_doi": doi,
                "query": query,
                "query_source": "tei" if tei_query else "context",
                "context": row.get("context", ""),
            }
        )
    return targets


def score_result(row: Dict[str, Any], cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    doi_key = f"doi:{row['source_doi']}" if row.get("source_doi") else ""
    search_key = f"search:{row['query']}" if row.get("query") else ""

    used_key = ""
    result: Optional[Dict[str, Any]] = None
    if doi_key and doi_key in cache and cache[doi_key].get("status") == "ok" and cache[doi_key].get("items"):
        used_key = doi_key
        result = cache[doi_key]
    elif search_key and search_key in cache:
        used_key = search_key
        result = cache[search_key]
    elif doi_key and doi_key in cache:
        used_key = doi_key
        result = cache[doi_key]

    base_output = {
        "sample_index": row.get("sample_index"),
        "publication_id": row.get("publication_id"),
        "reference_id": row.get("reference_id"),
        "reference_order": row.get("reference_order"),
        "source_doi": row.get("source_doi"),
        "openalex_status": "not_checked",
        "openalex_id": "",
        "openalex_doi": "",
        "openalex_title": "",
        "openalex_year": "",
        "openalex_source": "",
        "openalex_type": "",
        "relevance_score": "",
        "confidence": "",
        "title_coverage": "",
        "title_similarity": "",
        "title_token_count": "",
        "author_coverage": "",
        "year_match": "",
        "request_key": used_key,
        "query_source": row.get("query_source"),
        "query": row.get("query"),
        "context": row.get("context"),
    }

    if not result:
        return base_output
    if result.get("status") in {"rate_limited", "error"}:
        base_output["openalex_status"] = "search_error" if result.get("status") == "error" else "rate_limited"
        return base_output
    if result.get("status") == "not_found":
        base_output["openalex_status"] = "no_match"
        return base_output

    items = result.get("items")
    if not isinstance(items, list) or not items:
        base_output["openalex_status"] = "no_match"
        return base_output

    if used_key.startswith("doi:"):
        candidate = items[0]
        source_doi = row.get("source_doi") or ""
        openalex_doi = normalize_doi(candidate.get("doi") or "")
        exact_doi = bool(source_doi and openalex_doi == source_doi)
        score = score_candidate(candidate, row.get("context") or "")
        status = "strong" if exact_doi else score.match_status
    else:
        score = best_candidate(items, row.get("context") or "")
        if not score:
            base_output["openalex_status"] = "no_match"
            return base_output
        candidate = score.candidate
        status = score.match_status

    base_output.update(
        {
            "openalex_status": status,
            "openalex_id": candidate.get("id") or "",
            "openalex_doi": normalize_doi(candidate.get("doi") or ""),
            "openalex_title": candidate.get("title") or "",
            "openalex_year": candidate.get("publication_year") or "",
            "openalex_source": candidate.get("source_title") or "",
            "openalex_type": candidate.get("type") or "",
            "relevance_score": candidate.get("relevance_score") or "",
            "confidence": score.confidence,
            "title_coverage": score.title_coverage,
            "title_similarity": score.title_similarity,
            "title_token_count": score.title_token_count,
            "author_coverage": score.author_coverage,
            "year_match": score.year_match,
        }
    )
    return base_output


def percent(numerator: int, denominator: int) -> Optional[float]:
    return round((numerator / denominator) * 100.0, 2) if denominator else None


def build_summary(
    scope: str,
    crossref_sets: Dict[str, set[str]],
    all_count: int,
    target_total: int,
    results: List[Dict[str, Any]],
    cache: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    strong = sum(1 for row in results if row["openalex_status"] == "strong")
    possible = sum(1 for row in results if row["openalex_status"] == "possible")
    no_match = sum(1 for row in results if row["openalex_status"] == "no_match")
    search_error = sum(1 for row in results if row["openalex_status"] == "search_error")
    rate_limited = sum(1 for row in results if row["openalex_status"] == "rate_limited")
    not_checked = sum(1 for row in results if row["openalex_status"] == "not_checked")
    checked = len(results) - not_checked
    base_crossref_found = {
        "stq_not_found": len(crossref_sets["stq"]),
        "crossref_strict_not_found": len(crossref_sets["strict"]),
        "crossref_broad_not_found": len(crossref_sets["broad"]),
        "crossref_union_not_found": len(crossref_sets["union"]),
    }[scope]
    experiment4_strict = base_crossref_found + strong
    experiment4_broad = base_crossref_found + strong + possible
    last_rate_limit = {}
    for cached in reversed(list(cache.values())):
        if cached.get("rate_limit"):
            last_rate_limit = cached["rate_limit"]
            break

    return {
        "scope": scope,
        "sampled_references": all_count,
        "base_crossref_found": base_crossref_found,
        "base_crossref_found_rate_percent": percent(base_crossref_found, all_count),
        "openalex_target_total": target_total,
        "openalex_checked": checked,
        "openalex_not_checked": not_checked,
        "openalex_strong_matches": strong,
        "openalex_possible_matches": possible,
        "openalex_no_match": no_match,
        "openalex_search_errors": search_error,
        "openalex_rate_limited_rows": rate_limited,
        "openalex_recovery_rate_checked_strong_percent": percent(strong, checked),
        "openalex_recovery_rate_checked_broad_percent": percent(strong + possible, checked),
        "openalex_recovery_rate_target_strong_percent": percent(strong, target_total),
        "openalex_recovery_rate_target_broad_percent": percent(strong + possible, target_total),
        "experiment4_strict_found": experiment4_strict,
        "experiment4_strict_found_rate_percent": percent(experiment4_strict, all_count),
        "experiment4_broad_found": experiment4_broad,
        "experiment4_broad_found_rate_percent": percent(experiment4_broad, all_count),
        "complete": not_checked == 0,
        "crossref_component_counts": {
            "doi_only": len(crossref_sets["doi"]),
            "strict": len(crossref_sets["strict"]),
            "broad": len(crossref_sets["broad"]),
            "simple_text_query": len(crossref_sets["stq"]),
            "crossref_union": len(crossref_sets["union"]),
        },
        "last_openalex_rate_limit_headers": last_rate_limit,
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "source_doi",
        "openalex_status",
        "openalex_id",
        "openalex_doi",
        "openalex_title",
        "openalex_year",
        "openalex_source",
        "openalex_type",
        "relevance_score",
        "confidence",
        "title_coverage",
        "title_similarity",
        "title_token_count",
        "author_coverage",
        "year_match",
        "request_key",
        "query_source",
        "query",
        "context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    status = "tamamlandi" if summary["complete"] else "partial"
    lines = [
        "# OpenAlex Deney 4",
        "",
        f"- Durum: {status}",
        f"- Kapsam: {summary['scope']}",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Crossref baz bulunan: {summary['base_crossref_found']} ({summary['base_crossref_found_rate_percent']}%)",
        f"- OpenAlex hedef kalan: {summary['openalex_target_total']}",
        f"- OpenAlex kontrol edilen: {summary['openalex_checked']}",
        f"- Kontrol edilmeyen: {summary['openalex_not_checked']}",
        f"- Strong OpenAlex eslesme: {summary['openalex_strong_matches']}",
        f"- Possible OpenAlex eslesme: {summary['openalex_possible_matches']}",
        f"- No match: {summary['openalex_no_match']}",
        f"- Search error: {summary['openalex_search_errors']}",
        "",
        "## Deney 4 Sonuc",
        "",
        f"- Strict OpenAlex ekli: {summary['experiment4_strict_found']} ({summary['experiment4_strict_found_rate_percent']}%)",
        f"- Broad OpenAlex ekli: {summary['experiment4_broad_found']} ({summary['experiment4_broad_found_rate_percent']}%)",
        f"- Checked strong recovery: {summary['openalex_recovery_rate_checked_strong_percent']}%",
        f"- Checked broad recovery: {summary['openalex_recovery_rate_checked_broad_percent']}%",
        "",
        "Not: API kredisi bitmeden durdurulduysa `complete=false` kalir; ayni komut cache uzerinden resume eder.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use OpenAlex for references not matched by Crossref experiments.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument(
        "--stq-csv",
        default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"),
        type=Path,
    )
    parser.add_argument(
        "--doi-fallback-csv",
        default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"),
        type=Path,
    )
    parser.add_argument(
        "--no-doi-fallback-csv",
        default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"),
        type=Path,
    )
    parser.add_argument(
        "--tei-dir",
        default=Path("trdizin_full_reference_training_clean_date_good10k/citation_corpus"),
        type=Path,
    )
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/openalex_fallback"), type=Path)
    parser.add_argument(
        "--scope",
        default="crossref_union_not_found",
        choices=["stq_not_found", "crossref_strict_not_found", "crossref_broad_not_found", "crossref_union_not_found"],
    )
    parser.add_argument("--rows", default=5, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--workers", default=1, type=int)
    parser.add_argument("--max-start-rate", default=2.0, type=float)
    parser.add_argument("--save-every", default=20, type=int)
    parser.add_argument("--batch-size", default=200, type=int)
    parser.add_argument("--max-query-chars", default=300, type=int)
    parser.add_argument("--max-search-requests", default=None, type=int)
    parser.add_argument("--max-doi-requests", default=None, type=int)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", default=20260805, type=int)
    parser.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.out_dir / "openalex_fallback_cache.json"
    cache = load_cache(cache_path)
    if args.retry_errors:
        retryable_keys = [key for key, value in cache.items() if value.get("status") in {"error", "rate_limited"}]
        for key in retryable_keys:
            del cache[key]
        if retryable_keys:
            save_cache(cache_path, cache)
            print(f"removed {len(retryable_keys)} retryable cached OpenAlex errors", flush=True)

    sample_rows = read_csv(args.sample_csv)
    stq_rows = read_csv(args.stq_csv)
    doi_fallback_rows = read_csv(args.doi_fallback_csv)
    no_doi_fallback_rows = read_csv(args.no_doi_fallback_csv)
    crossref_sets = build_crossref_sets(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows)
    all_indexes = {row["sample_index"] for row in sample_rows}
    target_indexes = target_indexes_for_scope(args.scope, crossref_sets, all_indexes)
    target_rows = build_target_rows(sample_rows, target_indexes, args.tei_dir, args.max_query_chars)

    if args.shuffle:
        rng = random.Random(args.seed)
        rng.shuffle(target_rows)

    doi_keys: List[str] = []
    for row in target_rows:
        if row.get("source_doi"):
            key = f"doi:{row['source_doi']}"
            if key not in cache and key not in doi_keys:
                doi_keys.append(key)
    if args.max_doi_requests is not None:
        doi_keys = doi_keys[: args.max_doi_requests]

    print(
        f"scope={args.scope} target={len(target_rows)} cached={len(cache)} missing_doi_keys={len(doi_keys)}",
        flush=True,
    )
    fill_missing_cache(
        cache_path=cache_path,
        cache=cache,
        missing_keys=doi_keys,
        rows=args.rows,
        timeout=args.timeout,
        retries=args.retries,
        sleep_seconds=args.sleep,
        api_key=args.api_key,
        workers=args.workers,
        max_start_rate=args.max_start_rate,
        save_every=args.save_every,
        batch_size=args.batch_size,
    )

    search_keys: List[str] = []
    for row in target_rows:
        if not row.get("query"):
            continue
        doi_key = f"doi:{row['source_doi']}" if row.get("source_doi") else ""
        doi_result = cache.get(doi_key) if doi_key else None
        if doi_result and doi_result.get("status") == "ok" and doi_result.get("items"):
            continue
        key = f"search:{row['query']}"
        if key not in cache and key not in search_keys:
            search_keys.append(key)
    if args.max_search_requests is not None:
        search_keys = search_keys[: args.max_search_requests]

    print(f"missing_search_keys={len(search_keys)} max_search_requests={args.max_search_requests}", flush=True)
    fill_missing_cache(
        cache_path=cache_path,
        cache=cache,
        missing_keys=search_keys,
        rows=args.rows,
        timeout=args.timeout,
        retries=args.retries,
        sleep_seconds=args.sleep,
        api_key=args.api_key,
        workers=args.workers,
        max_start_rate=args.max_start_rate,
        save_every=args.save_every,
        batch_size=args.batch_size,
    )

    result_rows = [score_result(row, cache) for row in sorted(target_rows, key=lambda item: int(item["sample_index"]))]
    summary = build_summary(args.scope, crossref_sets, len(sample_rows), len(target_rows), result_rows, cache)
    write_csv(args.out_dir / "openalex_fallback_matches.csv", result_rows)
    write_jsonl(args.out_dir / "openalex_fallback_matches.jsonl", result_rows)
    write_json(args.out_dir / "openalex_fallback_summary.json", summary)
    write_report(args.out_dir / "openalex_fallback_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
