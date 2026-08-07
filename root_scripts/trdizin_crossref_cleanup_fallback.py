#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from trdizin_crossref_bibliographic_fallback import (
    CONTACT_EMAIL,
    best_candidate,
    clean_reference_query,
    first_text,
    issued_year,
    limit_query,
    make_session,
    percent,
    search_crossref,
)
from trdizin_openalex_fallback import build_crossref_sets, normalize_doi, truthy


YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-3][0-9])\b")
LEADING_REFNO_RE = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)])\s*")
WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+")
ARTICLE_LIKE_RE = re.compile(
    r"\b\d+\s*\(\s*\d+\s*\)\s*[:,]\s*\d+\s*[-–]\s*\d+"
    r"|\b\d+\s*[:,]\s*\d+\s*[-–]\s*\d+"
    r"|\[(?:CrossRef|Crossref|PubMed|pubmed)\]",
    re.IGNORECASE,
)
DOI_CANDIDATE_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/\s*|doi\s*[:.]?\s*)?(10\.\d{4,9}\s*/\s*[^\s\"'<>]+)",
    re.IGNORECASE,
)
NOISE_RE = re.compile(
    r"\[(?:CrossRef|Crossref|PubMed|pubmed|Google Scholar|Video)\]"
    r"|\b(?:retrieved|accessed|erişim|erisim)\s+(?:from|tarihi)?\b.*$",
    re.IGNORECASE,
)


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


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "query_mode",
        "source_doi",
        "hidden_doi",
        "experiment8_status",
        "experiment8_doi",
        "experiment8_title",
        "experiment8_year",
        "experiment8_publisher",
        "crossref_score",
        "confidence",
        "title_coverage",
        "title_similarity",
        "title_token_count",
        "author_coverage",
        "year_match",
        "request_key",
        "query",
        "context",
    ]
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


def build_base_found(
    sample_rows: List[Dict[str, str]],
    stq_rows: List[Dict[str, str]],
    doi_fallback_rows: List[Dict[str, str]],
    no_doi_fallback_rows: List[Dict[str, str]],
    openalex_rows: List[Dict[str, Any]],
    dergipark_rows: List[Dict[str, Any]],
) -> set[str]:
    crossref_sets = build_crossref_sets(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows)
    openalex_found = {
        str(row.get("sample_index"))
        for row in openalex_rows
        if row.get("openalex_status") in {"strong", "possible"}
    }
    dergipark_found = {
        str(row.get("sample_index"))
        for row in dergipark_rows
        if row.get("dergipark_status") in {"strong", "possible"}
    }
    return crossref_sets["union"] | openalex_found | dergipark_found


def normalized_reference(context: str) -> str:
    value = html.unescape(context or "")
    value = value.replace("\u00ad", "")
    value = LEADING_REFNO_RE.sub("", value)
    value = re.sub(r"([A-Za-zÇĞİÖŞÜçğıöşü])-\s+([A-Za-zÇĞİÖŞÜçğıöşü])", r"\1\2", value)
    value = NOISE_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .;,")


def aggressive_dehyphenated(context: str) -> str:
    value = normalized_reference(context)
    value = re.sub(r"([a-zçğıöşü]{3,})-([a-zçğıöşü]{2,})", r"\1\2", value)
    return value.strip(" .;,")


def extract_hidden_dois(context: str) -> List[str]:
    dois: List[str] = []
    for match in DOI_CANDIDATE_RE.finditer(context or ""):
        raw = re.sub(r"\s*/\s*", "/", match.group(1))
        doi = normalize_doi(raw)
        if doi.startswith("10.") and doi not in dois:
            dois.append(doi)
    return dois


def first_year(context: str) -> str:
    match = YEAR_RE.search(context or "")
    return match.group(1) if match else ""


def plausible_title(value: str) -> bool:
    words = WORD_RE.findall(value or "")
    return 4 <= len(words) <= 28


def split_title_journal(context: str) -> Tuple[str, str]:
    value = normalized_reference(context)
    year_match = YEAR_RE.search(value)
    if not year_match:
        return "", ""

    after_year = value[year_match.end() :].strip(" .;:,()")
    apa_title = ""
    if after_year:
        parts = [part.strip(" .;:,") for part in re.split(r"\.\s+", after_year) if part.strip(" .;:,")]
        if parts and plausible_title(parts[0]):
            apa_title = parts[0]
            journal = parts[1] if len(parts) > 1 else ""
            return apa_title, journal

    prefix = value[: year_match.start()].strip(" .;:,")
    parts = [part.strip(" .;:,") for part in re.split(r"\.\s+", prefix) if part.strip(" .;:,")]
    if len(parts) >= 2 and plausible_title(parts[-2]):
        return parts[-2], parts[-1]
    return "", ""


def build_queries(context: str, source_doi: str, max_query_chars: int) -> List[Tuple[str, str]]:
    queries: List[Tuple[str, str]] = []

    raw_clean = normalized_reference(clean_reference_query(context, source_doi or None))
    if raw_clean:
        queries.append(("cleaned_context", limit_query(raw_clean, max_query_chars)))

    dehyphenated = aggressive_dehyphenated(clean_reference_query(context, source_doi or None))
    if dehyphenated and dehyphenated != raw_clean:
        queries.append(("dehyphenated_context", limit_query(dehyphenated, max_query_chars)))

    title, journal = split_title_journal(context)
    year = first_year(context)
    if title:
        title_query = " ".join(piece for piece in [title, journal, year] if piece)
        queries.append(("title_journal_year", limit_query(title_query, max_query_chars)))

    seen: set[str] = set()
    unique: List[Tuple[str, str]] = []
    for mode, query in queries:
        key = " ".join(query.split())
        if len(key) < 12 or key.lower() in seen:
            continue
        seen.add(key.lower())
        unique.append((mode, key))
    return unique


def is_article_like(context: str) -> bool:
    return bool(ARTICLE_LIKE_RE.search(context or ""))


def build_targets(
    sample_rows: List[Dict[str, str]],
    base_found: set[str],
    max_query_chars: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in sample_rows:
        if row["sample_index"] in base_found:
            continue
        context = row.get("context") or ""
        source_doi = normalize_doi(row.get("doi") or "")
        hidden_dois = [doi for doi in extract_hidden_dois(context) if doi and doi != source_doi]
        article_like = is_article_like(context)
        if not hidden_dois and not article_like:
            rows.append(
                {
                    "sample_index": row.get("sample_index", ""),
                    "publication_id": row.get("publication_id", ""),
                    "reference_id": row.get("reference_id", ""),
                    "reference_order": row.get("reference_order", ""),
                    "source_doi": source_doi,
                    "hidden_doi": "",
                    "query_mode": "not_article_like",
                    "queries": [],
                    "context": context,
                }
            )
            continue

        queries = build_queries(context, source_doi, max_query_chars)
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "source_doi": source_doi,
                "hidden_doi": hidden_dois[0] if hidden_dois else "",
                "query_mode": "hidden_doi" if hidden_dois else "article_like",
                "hidden_dois": hidden_dois,
                "queries": queries,
                "context": context,
            }
        )
    return rows


def lookup_crossref_doi(
    session: requests.Session,
    doi: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    last_error = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt)))
        try:
            response = session.get(url, params={"mailto": CONTACT_EMAIL}, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                return {"status": "error", "http_status": 200, "error": "invalid json"}
            work = payload.get("message") if isinstance(payload, dict) else {}
            return {"status": "ok", "http_status": 200, "items": [work] if isinstance(work, dict) else []}
        if response.status_code == 404:
            return {"status": "not_found", "http_status": 404, "items": []}
        if response.status_code == 429:
            return {"status": "rate_limited", "http_status": 429, "error": "HTTP 429"}
        if response.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {response.status_code}"
            continue
        return {"status": "error", "http_status": response.status_code, "error": response.text[:300]}
    return {"status": "error", "http_status": None, "error": last_error or "request failed"}


def fetch_key(
    key: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    rate_limiter: RateLimiter,
) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_session()
    kind, value = key.split(":", 1)
    if kind == "doi":
        result = lookup_crossref_doi(session, value, timeout, retries, sleep_seconds)
    elif kind == "query":
        result = search_crossref(session, value, rows, timeout, retries, sleep_seconds)
    else:
        result = {"status": "error", "error": f"unknown key: {key}"}
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
    workers: int,
    max_start_rate: float,
    save_every: int,
    batch_size: int,
) -> None:
    if not missing_keys:
        return
    completed = 0
    for start in range(0, len(missing_keys), batch_size):
        batch = missing_keys[start : start + batch_size]
        dirty = False
        rate_limiter = RateLimiter(max_start_rate)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_key, key, rows, timeout, retries, sleep_seconds, rate_limiter): key
                for key in batch
            }
            for future in as_completed(futures):
                key, result = future.result()
                if result.get("status") != "rate_limited":
                    cache[key] = result
                    dirty = True
                completed += 1
                if completed % save_every == 0:
                    save_cache(cache_path, cache)
                    dirty = False
                    print(f"cached {completed}/{len(missing_keys)} Crossref cleanup requests", flush=True)
        if dirty:
            save_cache(cache_path, cache)
        print(f"batch {min(start + len(batch), len(missing_keys))}/{len(missing_keys)} done", flush=True)


def score_row(row: Dict[str, Any], cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    base = {
        "sample_index": row.get("sample_index", ""),
        "publication_id": row.get("publication_id", ""),
        "reference_id": row.get("reference_id", ""),
        "reference_order": row.get("reference_order", ""),
        "query_mode": row.get("query_mode", ""),
        "source_doi": row.get("source_doi", ""),
        "hidden_doi": row.get("hidden_doi", ""),
        "experiment8_status": "not_checked" if row.get("queries") or row.get("hidden_dois") else row.get("query_mode", "not_checked"),
        "experiment8_doi": "",
        "experiment8_title": "",
        "experiment8_year": "",
        "experiment8_publisher": "",
        "crossref_score": "",
        "confidence": "",
        "title_coverage": "",
        "title_similarity": "",
        "title_token_count": "",
        "author_coverage": "",
        "year_match": "",
        "request_key": "",
        "query": "",
        "context": row.get("context", ""),
    }

    candidates: List[Dict[str, Any]] = []
    for doi in row.get("hidden_dois") or []:
        key = f"doi:{doi}"
        result = cache.get(key)
        if result and result.get("status") == "ok" and result.get("items"):
            work = result["items"][0]
            base.update(
                {
                    "experiment8_status": "strong",
                    "experiment8_doi": normalize_doi(work.get("DOI") or doi),
                    "experiment8_title": first_text(work.get("title")) or "",
                    "experiment8_year": issued_year(work) or "",
                    "experiment8_publisher": work.get("publisher") or "",
                    "request_key": key,
                    "query": doi,
                }
            )
            return base
        if result and result.get("status") in {"error", "rate_limited"}:
            base["experiment8_status"] = "search_error"
            base["request_key"] = key

    for mode, query in row.get("queries") or []:
        key = f"query:{query}"
        result = cache.get(key)
        if not result:
            continue
        if result.get("status") in {"error", "rate_limited"}:
            if base["experiment8_status"] == "not_checked":
                base["experiment8_status"] = "search_error"
                base["request_key"] = key
            continue
        items = result.get("items") if isinstance(result.get("items"), list) else []
        score = best_candidate(items, row.get("context") or "")
        if score and safe_query_score(score):
            candidates.append({"mode": mode, "query": query, "key": key, "score": score})

    if not candidates:
        if base["experiment8_status"] == "not_checked":
            base["experiment8_status"] = "no_match"
        return base

    status_rank = {"strong": 2, "possible": 1, "no_match": 0}
    best = max(
        candidates,
        key=lambda item: (
            status_rank[item["score"].match_status],
            item["score"].confidence,
            item["score"].candidate.get("score") or 0,
        ),
    )
    score = best["score"]
    work = score.candidate
    base.update(
        {
            "query_mode": best["mode"],
            "experiment8_status": score.match_status,
            "experiment8_doi": normalize_doi(work.get("DOI") or ""),
            "experiment8_title": first_text(work.get("title")) or "",
            "experiment8_year": issued_year(work) or "",
            "experiment8_publisher": work.get("publisher") or "",
            "crossref_score": work.get("score") or "",
            "confidence": score.confidence,
            "title_coverage": score.title_coverage,
            "title_similarity": score.title_similarity,
            "title_token_count": score.title_token_count,
            "author_coverage": score.author_coverage,
            "year_match": score.year_match,
            "request_key": best["key"],
            "query": best["query"],
        }
    )
    return base


def safe_query_score(score: Any) -> bool:
    if score.match_status not in {"strong", "possible"}:
        return False
    if score.title_token_count < 6:
        return False
    if score.title_coverage < 0.88:
        return False
    if not score.year_match:
        return False
    if score.author_coverage < 0.34:
        return False
    return True


def build_request_keys(targets: List[Dict[str, Any]]) -> List[str]:
    keys: List[str] = []
    seen: set[str] = set()
    for row in targets:
        for doi in row.get("hidden_dois") or []:
            key = f"doi:{doi}"
            if key not in seen:
                seen.add(key)
                keys.append(key)
        for _, query in row.get("queries") or []:
            key = f"query:{query}"
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def build_summary(base_found: int, sampled: int, targets: List[Dict[str, Any]], output_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    strong = sum(1 for row in output_rows if row["experiment8_status"] == "strong")
    possible = sum(1 for row in output_rows if row["experiment8_status"] == "possible")
    no_match = sum(1 for row in output_rows if row["experiment8_status"] == "no_match")
    search_error = sum(1 for row in output_rows if row["experiment8_status"] == "search_error")
    not_article_like = sum(1 for row in output_rows if row["experiment8_status"] == "not_article_like")
    hidden_targets = sum(1 for row in targets if row.get("hidden_doi"))
    queryable = sum(1 for row in targets if row.get("hidden_dois") or row.get("queries"))
    strict = base_found + strong
    broad = base_found + strong + possible
    return {
        "experiment_label": "Deney 8 - Crossref cleanup + query variants",
        "sampled_references": sampled,
        "base_found_before_experiment8": base_found,
        "base_found_before_experiment8_rate_percent": percent(base_found, sampled),
        "experiment8_target_remaining": len(targets),
        "experiment8_queryable": queryable,
        "experiment8_hidden_doi_targets": hidden_targets,
        "experiment8_article_like_targets": queryable - hidden_targets,
        "experiment8_not_article_like": not_article_like,
        "experiment8_strong_matches": strong,
        "experiment8_possible_matches": possible,
        "experiment8_no_match": no_match,
        "experiment8_search_errors": search_error,
        "experiment8_strict_found": strict,
        "experiment8_strict_found_rate_percent": percent(strict, sampled),
        "experiment8_broad_found": broad,
        "experiment8_broad_found_rate_percent": percent(broad, sampled),
        "complete": search_error == 0,
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Crossref Cleanup Deney 8",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 8 oncesi baz bulunan: {summary['base_found_before_experiment8']} ({summary['base_found_before_experiment8_rate_percent']}%)",
        f"- Kalan hedef: {summary['experiment8_target_remaining']}",
        f"- Sorgulanabilir hedef: {summary['experiment8_queryable']}",
        f"- Gizli DOI hedefi: {summary['experiment8_hidden_doi_targets']}",
        f"- Article-like Crossref hedefi: {summary['experiment8_article_like_targets']}",
        f"- Article-like olmayan: {summary['experiment8_not_article_like']}",
        f"- Strong eslesme: {summary['experiment8_strong_matches']}",
        f"- Possible eslesme: {summary['experiment8_possible_matches']}",
        f"- No match: {summary['experiment8_no_match']}",
        f"- Search error: {summary['experiment8_search_errors']}",
        "",
        "## Deney 8 Sonuc",
        "",
        f"- Strict toplam: {summary['experiment8_strict_found']} ({summary['experiment8_strict_found_rate_percent']}%)",
        f"- Broad toplam: {summary['experiment8_broad_found']} ({summary['experiment8_broad_found_rate_percent']}%)",
        "",
        "Not: Bu deney kalan kayitlarin sadece DOI veya article-like sinyal tasiyan kismini Crossref'te yeniden dener.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experiment 8: retry remaining article-like references with stronger cleanup and query variants.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-jsonl", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.jsonl"), type=Path)
    parser.add_argument("--dergipark-jsonl", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.jsonl"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback"), type=Path)
    parser.add_argument("--rows", default=5, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--max-start-rate", default=8.0, type=float)
    parser.add_argument("--save-every", default=100, type=int)
    parser.add_argument("--batch-size", default=400, type=int)
    parser.add_argument("--max-query-chars", default=260, type=int)
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sample_rows = read_csv(args.sample_csv)
    stq_rows = read_csv(args.stq_csv)
    doi_fallback_rows = read_csv(args.doi_fallback_csv)
    no_doi_fallback_rows = read_csv(args.no_doi_fallback_csv)
    openalex_rows = read_jsonl(args.openalex_jsonl)
    dergipark_rows = read_jsonl(args.dergipark_jsonl)

    base_found = build_base_found(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows, openalex_rows, dergipark_rows)
    targets = build_targets(sample_rows, base_found, args.max_query_chars)
    keys = build_request_keys(targets)

    cache_path = args.out_dir / "crossref_cleanup_cache.json"
    cache = load_cache(cache_path)
    missing = [key for key in keys if key not in cache]
    print(f"base={len(base_found)} targets={len(targets)} request_keys={len(keys)} missing={len(missing)}", flush=True)
    if missing and not args.score_only:
        fill_missing_cache(
            cache_path=cache_path,
            cache=cache,
            missing_keys=missing,
            rows=args.rows,
            timeout=args.timeout,
            retries=args.retries,
            sleep_seconds=args.sleep,
            workers=args.workers,
            max_start_rate=args.max_start_rate,
            save_every=args.save_every,
            batch_size=args.batch_size,
        )

    output_rows = [score_row(row, cache) for row in targets]
    summary = build_summary(len(base_found), len(sample_rows), targets, output_rows)
    write_csv(args.out_dir / "crossref_cleanup_matches.csv", output_rows)
    write_jsonl(args.out_dir / "crossref_cleanup_matches.jsonl", output_rows)
    write_json(args.out_dir / "crossref_cleanup_summary.json", summary)
    write_report(args.out_dir / "crossref_cleanup_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
