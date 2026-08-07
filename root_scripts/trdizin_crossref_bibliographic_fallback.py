#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from xml.etree import ElementTree as ET

import requests
import threading


CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"
WORD_RE = re.compile(r"[a-z0-9]+")
YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-3][0-9])\b")
DOI_URL_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/\S+|doi\s*[:.]?\s*10\.\d{4,9}/\S+|10\.\d{4,9}/\S+)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
BRACKET_CROSSREF_RE = re.compile(r"\[(?:crossref|pubmed|google scholar)\s*\]", re.IGNORECASE)

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


def normalize_text(value: str) -> str:
    value = html.unescape(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(WORD_RE.findall(value))


def tokens(value: str) -> List[str]:
    return [token for token in normalize_text(value).split() if len(token) > 2 and token not in STOPWORDS]


def first_text(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return " ".join(value.split())
    return None


def issued_year(work: Dict[str, Any]) -> Optional[int]:
    for key in ("issued", "published-print", "published-online", "published"):
        value = work.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = parts[0][0]
            if isinstance(year, int):
                return year
    return None


def compact_work(work: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in (
        "DOI",
        "title",
        "publisher",
        "score",
        "author",
        "issued",
        "published-print",
        "published-online",
        "published",
    ):
        if key in work:
            compact[key] = work[key]
    return compact


def author_surnames(work: Dict[str, Any]) -> List[str]:
    authors = work.get("author")
    if not isinstance(authors, list):
        return []
    surnames: List[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        family = author.get("family")
        if isinstance(family, str):
            surname_tokens = tokens(family)
            if surname_tokens:
                surnames.append(surname_tokens[-1])
    return surnames


def clean_reference_query(context: str, doi: Optional[str]) -> str:
    query = html.unescape(context)
    if doi:
        query = re.sub(re.escape(doi), " ", query, flags=re.IGNORECASE)
    query = DOI_URL_RE.sub(" ", query)
    query = URL_RE.sub(" ", query)
    query = BRACKET_CROSSREF_RE.sub(" ", query)
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
    return {int(year) for year in YEAR_RE.findall(context)}


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
    title = first_text(work.get("title")) or ""
    title_token_count = len(tokens(title))
    coverage = title_coverage(title, context)
    similarity = title_similarity(title, context)
    surnames = author_surnames(work)
    author_ratio = author_coverage(surnames, context)
    year = issued_year(work)
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
    return max(scored, key=lambda item: (status_rank[item.match_status], item.confidence, item.candidate.get("score") or 0))


def search_crossref(
    session: requests.Session,
    query: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    url = "https://api.crossref.org/works"
    params = {
        "query.bibliographic": query,
        "rows": rows,
        "select": "DOI,title,author,issued,published-print,published-online,published,publisher,score",
        "mailto": CONTACT_EMAIL,
    }
    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt)))
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            message = payload.get("message") if isinstance(payload, dict) else {}
            items = message.get("items") if isinstance(message, dict) else []
            if not isinstance(items, list):
                items = []
            return {"status": "ok", "http_status": 200, "items": [compact_work(item) for item in items if isinstance(item, dict)]}
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after) if retry_after else 0.0
            except ValueError:
                wait_seconds = 0.0
            wait_seconds = max(wait_seconds, 5.0 * (attempt + 1), sleep_seconds)
            last_error = "HTTP 429"
            if attempt < retries:
                time.sleep(wait_seconds)
                continue
            return {"status": "rate_limited", "http_status": 429, "error": last_error}
        if response.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {response.status_code}"
            continue
        return {"status": "error", "http_status": response.status_code, "error": response.text[:300]}
    return {"status": "error", "http_status": None, "error": last_error or "request failed"}


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


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": f"trdizin-crossref-bibliographic-fallback/0.1 (mailto:{CONTACT_EMAIL})",
        }
    )
    return session


def fetch_query(
    query: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    rate_limiter: Optional[RateLimiter] = None,
) -> tuple[str, Dict[str, Any]]:
    if rate_limiter:
        rate_limiter.wait()
    session = make_session()
    result = search_crossref(
        session=session,
        query=query,
        rows=rows,
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    if sleep_seconds:
        time.sleep(sleep_seconds)
    return query, result


def fill_missing_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    missing_queries: Sequence[str],
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    workers: int,
    save_every: int,
    batch_size: int,
    rate_limit_sleep: float,
    max_start_rate: float,
) -> None:
    if not missing_queries:
        return

    if workers <= 1:
        session = make_session()
        dirty = False
        for index, query in enumerate(missing_queries, start=1):
            result = search_crossref(
                session=session,
                query=query,
                rows=rows,
                timeout=timeout,
                retries=retries,
                sleep_seconds=sleep_seconds,
            )
            if result.get("status") != "rate_limited":
                cache[query] = result
                dirty = True
            if sleep_seconds:
                time.sleep(sleep_seconds)
            if index % save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
        if dirty:
            save_cache(cache_path, cache)
        return

    completed = 0
    for start in range(0, len(missing_queries), batch_size):
        batch = missing_queries[start : start + batch_size]
        dirty = False
        rate_limited = 0
        rate_limiter = RateLimiter(max_start_rate)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(fetch_query, query, rows, timeout, retries, sleep_seconds, rate_limiter): query
                for query in batch
            }
            for future in as_completed(futures):
                query, result = future.result()
                if result.get("status") == "rate_limited":
                    rate_limited += 1
                else:
                    cache[query] = result
                    dirty = True
                completed += 1
                if completed % save_every == 0:
                    save_cache(cache_path, cache)
                    dirty = False
                    print(f"cached {completed}/{len(missing_queries)} missing queries", flush=True)
        if dirty:
            save_cache(cache_path, cache)
        print(
            f"batch {min(start + len(batch), len(missing_queries))}/{len(missing_queries)} done"
            + (f", rate_limited={rate_limited}" if rate_limited else ""),
            flush=True,
        )
        if rate_limited and rate_limit_sleep > 0:
            time.sleep(min(rate_limit_sleep, 10.0 * rate_limited))


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
        "original_doi",
        "fallback_status",
        "fallback_doi",
        "fallback_title",
        "fallback_publisher",
        "fallback_year",
        "crossref_score",
        "confidence",
        "title_coverage",
        "title_similarity",
        "title_token_count",
        "author_coverage",
        "year_match",
        "query",
        "context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def percent(numerator: int, denominator: int) -> Optional[float]:
    if denominator == 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def read_input_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_summary(
    input_summary: Dict[str, Any],
    rows: List[Dict[str, Any]],
    source_rows: int,
    target_statuses: Sequence[str],
    base_found: Optional[int],
) -> Dict[str, Any]:
    strong = sum(1 for row in rows if row["fallback_status"] == "strong")
    possible = sum(1 for row in rows if row["fallback_status"] == "possible")
    no_match = sum(1 for row in rows if row["fallback_status"] == "no_match")
    search_errors = sum(1 for row in rows if row["fallback_status"] == "search_error")
    original_found = int(base_found if base_found is not None else input_summary.get("crossref_found_by_doi") or 0)
    sampled = int(input_summary.get("sampled_references") or source_rows)
    doi_refs = int(input_summary.get("references_with_doi") or 0)
    target_total = len(rows)
    strict_found = original_found + strong
    broad_found = original_found + strong + possible
    doi_rate_applicable = "no_doi" not in set(target_statuses)
    return {
        "source_rows": source_rows,
        "fallback_scope": "rows selected by source crossref_status",
        "target_statuses": list(target_statuses),
        "fallback_checked": len(rows),
        "fallback_strong_matches": strong,
        "fallback_possible_matches": possible,
        "fallback_no_match": no_match,
        "fallback_search_errors": search_errors,
        "base_crossref_found": original_found,
        "target_total": target_total,
        "strict_crossref_found_after_fallback": strict_found,
        "broad_crossref_found_after_fallback": broad_found,
        "strict_found_rate_all_references_percent": percent(strict_found, sampled),
        "broad_found_rate_all_references_percent": percent(broad_found, sampled),
        "strict_found_rate_doi_references_percent": percent(strict_found, doi_refs) if doi_rate_applicable else None,
        "broad_found_rate_doi_references_percent": percent(broad_found, doi_refs) if doi_rate_applicable else None,
        "doi_reference_rate_applicable": doi_rate_applicable,
        "fallback_recovery_rate_strong_percent": percent(strong, target_total),
        "fallback_recovery_rate_broad_percent": percent(strong + possible, target_total),
    }


def write_summary_md(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Crossref Bibliographic Fallback Stats",
        "",
        f"- Scope: {summary['fallback_scope']}",
        f"- Target statuses: {', '.join(summary['target_statuses'])}",
        f"- Checked fallback references: {summary['fallback_checked']}",
        f"- Strong bibliographic matches: {summary['fallback_strong_matches']}",
        f"- Possible bibliographic matches: {summary['fallback_possible_matches']}",
        f"- No match: {summary['fallback_no_match']}",
        f"- Search errors: {summary['fallback_search_errors']}",
        "",
        "## Updated Stats",
        "",
        f"- Base Crossref found: {summary['base_crossref_found']}",
        f"- Target total: {summary['target_total']}",
        f"- Strict found after fallback: {summary['strict_crossref_found_after_fallback']} ({summary['strict_found_rate_all_references_percent']}% of all refs)",
        f"- Broad found after fallback: {summary['broad_crossref_found_after_fallback']} ({summary['broad_found_rate_all_references_percent']}% of all refs)",
        f"- Fallback recovery, strong only: {summary['fallback_recovery_rate_strong_percent']}%",
        f"- Fallback recovery, strong + possible: {summary['fallback_recovery_rate_broad_percent']}%",
        "",
        "`strong` is the safer count. `possible` should be manually reviewed before treating it as ground truth.",
        "",
    ]
    if summary.get("doi_reference_rate_applicable"):
        insert_at = lines.index(f"- Fallback recovery, strong only: {summary['fallback_recovery_rate_strong_percent']}%")
        lines[insert_at:insert_at] = [
            f"- Strict found rate among DOI refs: {summary['strict_found_rate_doi_references_percent']}%",
            f"- Broad found rate among DOI refs: {summary['broad_found_rate_doi_references_percent']}%",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Crossref bibliographically for rows whose extracted DOI returned 404."
    )
    parser.add_argument(
        "--input-csv",
        default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"),
        type=Path,
    )
    parser.add_argument(
        "--input-summary",
        default=Path("trdizin_crossref_doi_stats_10k/summary.json"),
        type=Path,
    )
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k"), type=Path)
    parser.add_argument("--rows", default=5, type=int)
    parser.add_argument(
        "--target-statuses",
        default="not_found",
        help="Comma-separated source crossref_status values to search, e.g. not_found,no_doi.",
    )
    parser.add_argument(
        "--output-prefix",
        default="doi_not_found_bibliographic_fallback",
        help="Prefix for CSV/JSONL outputs. Summary files use <prefix>_summary.*",
    )
    parser.add_argument(
        "--base-found",
        default=None,
        type=int,
        help="Existing found count to use when computing updated aggregate rates.",
    )
    parser.add_argument("--timeout", default=20.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--sleep", default=0.1, type=float)
    parser.add_argument("--workers", default=1, type=int)
    parser.add_argument("--save-every", default=100, type=int)
    parser.add_argument("--batch-size", default=200, type=int)
    parser.add_argument("--max-query-chars", default=700, type=int)
    parser.add_argument("--rate-limit-sleep", default=120.0, type=float)
    parser.add_argument("--max-start-rate", default=0.0, type=float)
    parser.add_argument(
        "--tei-dir",
        default=Path("trdizin_full_reference_training_clean_date_good10k/citation_corpus"),
        type=Path,
    )
    parser.add_argument("--use-tei-query", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="Only score rows already present in cache.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    input_rows = read_input_rows(args.input_csv)
    target_statuses = tuple(status.strip() for status in args.target_statuses.split(",") if status.strip())
    targets = [row for row in input_rows if row.get("crossref_status") in target_statuses]
    input_summary = json.loads(args.input_summary.read_text(encoding="utf-8"))

    cache_path = args.out_dir / "crossref_bibliographic_fallback_cache.json"
    cache = load_cache(cache_path)
    prepared_targets: List[Dict[str, Any]] = []
    unique_queries: List[str] = []
    seen_queries: set[str] = set()
    for row in targets:
        context = row.get("context") or ""
        original_doi = row.get("doi") or None
        tei_query = (
            tei_query_for_reference(args.tei_dir, row.get("publication_id"), row.get("reference_order"))
            if args.use_tei_query
            else None
        )
        query = limit_query(tei_query or clean_reference_query(context, original_doi), args.max_query_chars)
        prepared_targets.append({"row": row, "context": context, "original_doi": original_doi, "query": query})
        if query not in seen_queries:
            unique_queries.append(query)
            seen_queries.add(query)

    missing_queries = [query for query in unique_queries if query not in cache]
    if not args.no_fetch:
        fill_missing_cache(
            cache_path=cache_path,
            cache=cache,
            missing_queries=missing_queries,
            rows=args.rows,
            timeout=args.timeout,
            retries=args.retries,
            sleep_seconds=args.sleep,
            workers=args.workers,
        save_every=args.save_every,
        batch_size=args.batch_size,
        rate_limit_sleep=args.rate_limit_sleep,
        max_start_rate=args.max_start_rate,
    )

    output_rows: List[Dict[str, Any]] = []
    for prepared in prepared_targets:
        row = prepared["row"]
        context = prepared["context"]
        original_doi = prepared["original_doi"]
        query = prepared["query"]
        result = cache.get(query) or {"status": "missing_cache", "error": "missing cache result"}

        if result.get("status") != "ok":
            output_rows.append(
                {
                    "sample_index": row.get("sample_index"),
                    "publication_id": row.get("publication_id"),
                    "reference_id": row.get("reference_id"),
                    "reference_order": row.get("reference_order"),
                    "original_doi": original_doi,
                    "fallback_status": "search_error",
                    "query": query,
                    "context": context,
                    "error": result.get("error"),
                }
            )
            continue

        candidate = best_candidate(result.get("items") or [], context)
        if candidate is None:
            output_rows.append(
                {
                    "sample_index": row.get("sample_index"),
                    "publication_id": row.get("publication_id"),
                    "reference_id": row.get("reference_id"),
                    "reference_order": row.get("reference_order"),
                    "original_doi": original_doi,
                    "fallback_status": "no_match",
                    "query": query,
                    "context": context,
                }
            )
            continue

        work = candidate.candidate
        output_rows.append(
            {
                "sample_index": row.get("sample_index"),
                "publication_id": row.get("publication_id"),
                "reference_id": row.get("reference_id"),
                "reference_order": row.get("reference_order"),
                "original_doi": original_doi,
                "fallback_status": candidate.match_status,
                "fallback_doi": work.get("DOI"),
                "fallback_title": first_text(work.get("title")),
                "fallback_publisher": work.get("publisher"),
                "fallback_year": issued_year(work),
                "crossref_score": work.get("score"),
                "confidence": candidate.confidence,
                "title_coverage": candidate.title_coverage,
                "title_similarity": candidate.title_similarity,
                "title_token_count": candidate.title_token_count,
                "author_coverage": candidate.author_coverage,
                "year_match": candidate.year_match,
                "query": query,
                "context": context,
            }
        )

    summary = build_summary(
        input_summary=input_summary,
        rows=output_rows,
        source_rows=len(input_rows),
        target_statuses=target_statuses,
        base_found=args.base_found,
    )
    write_csv(args.out_dir / f"{args.output_prefix}.csv", output_rows)
    write_jsonl(args.out_dir / f"{args.output_prefix}.jsonl", output_rows)
    write_json(args.out_dir / f"{args.output_prefix}_summary.json", summary)
    write_summary_md(args.out_dir / f"{args.output_prefix}_summary.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
