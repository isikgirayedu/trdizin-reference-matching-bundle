#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from trdizin_openalex_fallback import (
    CONTACT_EMAIL,
    RateLimiter,
    author_coverage,
    build_crossref_sets,
    build_target_rows,
    context_years,
    normalize_doi,
    percent,
    read_csv,
    target_indexes_for_scope,
    title_coverage,
    title_similarity,
    tokens,
)


DATACITE_DOIS_URL = "https://api.datacite.org/dois"
DATACITE_FIELDS = "doi,titles,creators,publisher,publicationYear,types,url"


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


def first_title(attributes: Dict[str, Any]) -> str:
    titles = attributes.get("titles")
    if not isinstance(titles, list):
        return ""
    for item in titles:
        if isinstance(item, dict) and isinstance(item.get("title"), str):
            return " ".join(item["title"].split())
    return ""


def publication_year(attributes: Dict[str, Any]) -> Optional[int]:
    value = attributes.get("publicationYear")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def creator_names(attributes: Dict[str, Any]) -> List[str]:
    creators = attributes.get("creators")
    if not isinstance(creators, list):
        return []
    names: List[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        name = creator.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
            continue
        pieces = [creator.get("givenName"), creator.get("familyName")]
        combined = " ".join(piece for piece in pieces if isinstance(piece, str) and piece.strip())
        if combined:
            names.append(combined)
    return names


def creator_surnames(attributes: Dict[str, Any]) -> List[str]:
    creators = attributes.get("creators")
    if not isinstance(creators, list):
        return []
    surnames: List[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        family = creator.get("familyName")
        if isinstance(family, str) and family.strip():
            family_tokens = tokens(family)
            if family_tokens:
                surnames.append(family_tokens[-1])
            continue
        name = creator.get("name")
        if not isinstance(name, str):
            continue
        name_part = name.split(",", 1)[0] if "," in name else name
        name_tokens = tokens(name_part)
        if name_tokens:
            surnames.append(name_tokens[-1])
    return surnames


def compact_doi_record(record: Dict[str, Any], rank: int = 0) -> Dict[str, Any]:
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    types = attributes.get("types")
    if not isinstance(types, dict):
        types = {}
    return {
        "id": record.get("id") or attributes.get("doi") or "",
        "doi": normalize_doi(str(attributes.get("doi") or record.get("id") or "")),
        "title": first_title(attributes),
        "publisher": attributes.get("publisher") or "",
        "publication_year": publication_year(attributes),
        "resource_type": types.get("resourceTypeGeneral") or types.get("resourceType") or "",
        "url": attributes.get("url") or "",
        "authors": creator_names(attributes),
        "creator_surnames": creator_surnames(attributes),
        "search_rank": rank,
    }


def datacite_safe_query(query: str, max_tokens: int = 60) -> str:
    query_tokens = tokens(query)
    return " ".join(query_tokens[:max_tokens])


def score_candidate(work: Dict[str, Any], context: str) -> CandidateScore:
    title = work.get("title") or ""
    title_token_count = len(tokens(title))
    coverage = title_coverage(title, context)
    similarity = title_similarity(title, context)
    author_ratio = author_coverage(work.get("creator_surnames") or [], context)
    year = work.get("publication_year")
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
    return max(
        scored,
        key=lambda item: (
            status_rank[item.match_status],
            item.confidence,
            -int(item.candidate.get("search_rank") or 0),
        ),
    )


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
            "Accept": "application/vnd.api+json, application/json",
            "User-Agent": f"trdizin-datacite-fallback/0.1 (mailto:{CONTACT_EMAIL})",
        }
    )
    return session


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
        if response.status_code == 200:
            try:
                return {"status": "ok", "http_status": 200, "payload": response.json()}
            except ValueError:
                return {"status": "error", "http_status": 200, "error": "invalid json"}
        if response.status_code == 404:
            return {"status": "not_found", "http_status": 404}
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
            return {"status": "rate_limited", "http_status": 429, "error": last_error}
        if response.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {response.status_code}"
            continue
        return {"status": "error", "http_status": response.status_code, "error": response.text[:300]}
    return {"status": "error", "http_status": None, "error": last_error or "request failed"}


def lookup_datacite_doi(
    session: requests.Session,
    doi: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    result = request_json(
        session=session,
        url=f"{DATACITE_DOIS_URL}/{quote(doi, safe='')}",
        params={"fields[dois]": DATACITE_FIELDS},
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    if result.get("status") == "ok" and isinstance(result.get("payload"), dict):
        record = result["payload"].get("data")
        items = [compact_doi_record(record)] if isinstance(record, dict) else []
        return {"status": "ok", "http_status": result.get("http_status"), "items": items}
    return result


def search_datacite(
    session: requests.Session,
    query: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    result = request_json(
        session=session,
        url=DATACITE_DOIS_URL,
        params={
            "query": query,
            "page[size]": rows,
            "fields[dois]": DATACITE_FIELDS,
        },
        timeout=timeout,
        retries=retries,
        sleep_seconds=sleep_seconds,
    )
    if result.get("status") == "ok" and isinstance(result.get("payload"), dict):
        records = result["payload"].get("data")
        if not isinstance(records, list):
            records = []
        items = [
            compact_doi_record(record, rank=index)
            for index, record in enumerate(records, start=1)
            if isinstance(record, dict)
        ]
        return {"status": "ok", "http_status": result.get("http_status"), "items": items}
    return result


def fetch_request_key(
    key: str,
    rows: int,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    rate_limiter: Optional[RateLimiter],
) -> Tuple[str, Dict[str, Any]]:
    if rate_limiter:
        rate_limiter.wait()
    session = make_session()
    kind, value = key.split(":", 1)
    if kind == "doi":
        result = lookup_datacite_doi(session, value, timeout, retries, sleep_seconds)
    elif kind == "search":
        result = search_datacite(session, value, rows, timeout, retries, sleep_seconds)
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
    workers: int,
    max_start_rate: float,
    save_every: int,
) -> None:
    if not missing_keys:
        return

    completed = 0
    dirty = False
    if workers <= 1:
        rate_limiter = RateLimiter(max_start_rate)
        for key in missing_keys:
            request_key, result = fetch_request_key(key, rows, timeout, retries, sleep_seconds, rate_limiter)
            if result.get("status") != "rate_limited":
                cache[request_key] = result
                dirty = True
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
                print(f"cached {completed}/{len(missing_keys)} DataCite requests", flush=True)
            if result.get("status") == "rate_limited":
                print(f"rate limited after {completed}/{len(missing_keys)} requests", flush=True)
                break
        if dirty:
            save_cache(cache_path, cache)
        return

    rate_limiter = RateLimiter(max_start_rate)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_request_key, key, rows, timeout, retries, sleep_seconds, rate_limiter): key
            for key in missing_keys
        }
        for future in as_completed(futures):
            request_key, result = future.result()
            if result.get("status") != "rate_limited":
                cache[request_key] = result
                dirty = True
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
                print(f"cached {completed}/{len(missing_keys)} DataCite requests", flush=True)
        if dirty:
            save_cache(cache_path, cache)


def openalex_found_indexes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    rows = read_csv(path)
    return {row["sample_index"] for row in rows if row.get("openalex_status") in {"strong", "possible"}}


def target_indexes_for_datacite(
    scope: str,
    crossref_sets: Dict[str, set[str]],
    all_indexes: set[str],
    openalex_found: set[str],
) -> set[str]:
    if scope == "crossref_openalex_not_found":
        return all_indexes - (crossref_sets["union"] | openalex_found)
    return target_indexes_for_scope(scope, crossref_sets, all_indexes)


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
        "datacite_status": "not_checked",
        "datacite_doi": "",
        "datacite_title": "",
        "datacite_publisher": "",
        "datacite_year": "",
        "datacite_type": "",
        "datacite_url": "",
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
        if not row.get("query") and not row.get("source_doi"):
            base_output["datacite_status"] = "unqueryable"
            return base_output
        return base_output
    if result.get("status") in {"rate_limited", "error"}:
        base_output["datacite_status"] = "search_error" if result.get("status") == "error" else "rate_limited"
        return base_output
    if result.get("status") == "not_found":
        base_output["datacite_status"] = "no_match"
        return base_output

    items = result.get("items")
    if not isinstance(items, list) or not items:
        base_output["datacite_status"] = "no_match"
        return base_output

    if used_key.startswith("doi:"):
        candidate = items[0]
        source_doi = row.get("source_doi") or ""
        datacite_doi = normalize_doi(candidate.get("doi") or "")
        exact_doi = bool(source_doi and datacite_doi == source_doi)
        score = score_candidate(candidate, row.get("context") or "")
        status = "strong" if exact_doi else score.match_status
    else:
        score = best_candidate(items, row.get("context") or "")
        if not score:
            base_output["datacite_status"] = "no_match"
            return base_output
        candidate = score.candidate
        status = score.match_status

    base_output.update(
        {
            "datacite_status": status,
            "datacite_doi": candidate.get("doi") or "",
            "datacite_title": candidate.get("title") or "",
            "datacite_publisher": candidate.get("publisher") or "",
            "datacite_year": candidate.get("publication_year") or "",
            "datacite_type": candidate.get("resource_type") or "",
            "datacite_url": candidate.get("url") or "",
            "confidence": score.confidence,
            "title_coverage": score.title_coverage,
            "title_similarity": score.title_similarity,
            "title_token_count": score.title_token_count,
            "author_coverage": score.author_coverage,
            "year_match": score.year_match,
        }
    )
    return base_output


def build_summary(
    scope: str,
    crossref_sets: Dict[str, set[str]],
    openalex_found: set[str],
    all_count: int,
    target_total: int,
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    strong = sum(1 for row in results if row["datacite_status"] == "strong")
    possible = sum(1 for row in results if row["datacite_status"] == "possible")
    no_match = sum(1 for row in results if row["datacite_status"] == "no_match")
    search_error = sum(1 for row in results if row["datacite_status"] == "search_error")
    rate_limited = sum(1 for row in results if row["datacite_status"] == "rate_limited")
    unqueryable = sum(1 for row in results if row["datacite_status"] == "unqueryable")
    not_checked = sum(1 for row in results if row["datacite_status"] == "not_checked")
    checked = len(results) - not_checked

    if scope == "crossref_openalex_not_found":
        base_found = len(crossref_sets["union"] | openalex_found)
    elif scope == "crossref_union_not_found":
        base_found = len(crossref_sets["union"])
    elif scope == "crossref_broad_not_found":
        base_found = len(crossref_sets["broad"])
    elif scope == "crossref_strict_not_found":
        base_found = len(crossref_sets["strict"])
    elif scope == "stq_not_found":
        base_found = len(crossref_sets["stq"])
    else:
        base_found = len(crossref_sets["union"] | openalex_found)

    experiment5_strict = base_found + strong
    experiment5_broad = base_found + strong + possible
    return {
        "scope": scope,
        "sampled_references": all_count,
        "base_found_before_datacite": base_found,
        "base_found_before_datacite_rate_percent": percent(base_found, all_count),
        "datacite_target_total": target_total,
        "datacite_checked": checked,
        "datacite_not_checked": not_checked,
        "datacite_strong_matches": strong,
        "datacite_possible_matches": possible,
        "datacite_no_match": no_match,
        "datacite_search_errors": search_error,
        "datacite_rate_limited_rows": rate_limited,
        "datacite_unqueryable": unqueryable,
        "datacite_recovery_rate_checked_strong_percent": percent(strong, checked),
        "datacite_recovery_rate_checked_broad_percent": percent(strong + possible, checked),
        "datacite_recovery_rate_target_strong_percent": percent(strong, target_total),
        "datacite_recovery_rate_target_broad_percent": percent(strong + possible, target_total),
        "experiment5_strict_found": experiment5_strict,
        "experiment5_strict_found_rate_percent": percent(experiment5_strict, all_count),
        "experiment5_broad_found": experiment5_broad,
        "experiment5_broad_found_rate_percent": percent(experiment5_broad, all_count),
        "complete": not_checked == 0,
        "component_counts": {
            "doi_only": len(crossref_sets["doi"]),
            "strict": len(crossref_sets["strict"]),
            "broad": len(crossref_sets["broad"]),
            "simple_text_query": len(crossref_sets["stq"]),
            "crossref_union": len(crossref_sets["union"]),
            "openalex_found": len(openalex_found),
            "base_before_datacite": base_found,
        },
    }


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "source_doi",
        "datacite_status",
        "datacite_doi",
        "datacite_title",
        "datacite_publisher",
        "datacite_year",
        "datacite_type",
        "datacite_url",
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
        "# DataCite Deney 5",
        "",
        f"- Durum: {status}",
        f"- Kapsam: {summary['scope']}",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- DataCite oncesi baz bulunan: {summary['base_found_before_datacite']} ({summary['base_found_before_datacite_rate_percent']}%)",
        f"- DataCite hedef kalan: {summary['datacite_target_total']}",
        f"- DataCite kontrol edilen: {summary['datacite_checked']}",
        f"- Kontrol edilmeyen: {summary['datacite_not_checked']}",
        f"- Strong DataCite eslesme: {summary['datacite_strong_matches']}",
        f"- Possible DataCite eslesme: {summary['datacite_possible_matches']}",
        f"- No match: {summary['datacite_no_match']}",
        f"- Search error: {summary['datacite_search_errors']}",
        f"- Sorgulanamaz: {summary['datacite_unqueryable']}",
        "",
        "## Deney 5 Sonuc",
        "",
        f"- Strict DataCite ekli: {summary['experiment5_strict_found']} ({summary['experiment5_strict_found_rate_percent']}%)",
        f"- Broad DataCite ekli: {summary['experiment5_broad_found']} ({summary['experiment5_broad_found_rate_percent']}%)",
        f"- Checked strong recovery: {summary['datacite_recovery_rate_checked_strong_percent']}%",
        f"- Checked broad recovery: {summary['datacite_recovery_rate_checked_broad_percent']}%",
        "",
        "Not: Script cache/resume destekler; ayni komut yeniden calistirilirse sadece eksik istekleri tamamlar.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use DataCite REST API for references not matched by previous experiments.")
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
        "--openalex-csv",
        default=Path("trdizin_crossref_doi_stats_10k/openalex_fallback/openalex_fallback_matches.csv"),
        type=Path,
    )
    parser.add_argument(
        "--tei-dir",
        default=Path("trdizin_full_reference_training_clean_date_good10k/citation_corpus"),
        type=Path,
    )
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/datacite_fallback"), type=Path)
    parser.add_argument(
        "--scope",
        default="crossref_openalex_not_found",
        choices=[
            "stq_not_found",
            "crossref_strict_not_found",
            "crossref_broad_not_found",
            "crossref_union_not_found",
            "crossref_openalex_not_found",
        ],
    )
    parser.add_argument("--rows", default=5, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--workers", default=6, type=int)
    parser.add_argument("--max-start-rate", default=8.0, type=float)
    parser.add_argument("--save-every", default=50, type=int)
    parser.add_argument("--max-query-chars", default=300, type=int)
    parser.add_argument("--max-search-requests", default=None, type=int)
    parser.add_argument("--max-doi-requests", default=None, type=int)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", default=20260805, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.out_dir / "datacite_fallback_cache.json"
    cache = load_cache(cache_path)

    sample_rows = read_csv(args.sample_csv)
    stq_rows = read_csv(args.stq_csv)
    doi_fallback_rows = read_csv(args.doi_fallback_csv)
    no_doi_fallback_rows = read_csv(args.no_doi_fallback_csv)
    crossref_sets = build_crossref_sets(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows)
    openalex_found = openalex_found_indexes(args.openalex_csv)
    all_indexes = {row["sample_index"] for row in sample_rows}
    target_indexes = target_indexes_for_datacite(args.scope, crossref_sets, all_indexes, openalex_found)
    target_rows = build_target_rows(sample_rows, target_indexes, args.tei_dir, args.max_query_chars)
    for row in target_rows:
        row["query"] = datacite_safe_query(str(row.get("query") or ""))

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
        workers=args.workers,
        max_start_rate=args.max_start_rate,
        save_every=args.save_every,
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
        workers=args.workers,
        max_start_rate=args.max_start_rate,
        save_every=args.save_every,
    )

    result_rows = [score_result(row, cache) for row in sorted(target_rows, key=lambda item: int(item["sample_index"]))]
    summary = build_summary(args.scope, crossref_sets, openalex_found, len(sample_rows), len(target_rows), result_rows)
    write_csv(args.out_dir / "datacite_fallback_matches.csv", result_rows)
    write_jsonl(args.out_dir / "datacite_fallback_matches.jsonl", result_rows)
    write_json(args.out_dir / "datacite_fallback_summary.json", summary)
    write_report(args.out_dir / "datacite_fallback_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
