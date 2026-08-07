#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from trdizin_experiment11_journal_like_parser_dergipark import parse_reference
from trdizin_experiment12_trdizin_target_publication import (
    CONTACT_EMAIL,
    build_base_found,
    extract_first_doi,
    fetch_crossref_doi,
    load_cache,
    normalize_doi,
    percent,
    read_csv,
    save_cache,
    write_csv,
    write_json,
    write_jsonl,
)
from trdizin_openalex_fallback import author_coverage, context_years, tokens


TRDIZIN_SEARCH_URL = "https://search.trdizin.gov.tr/api/defaultSearch/publication/"
WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+")
JOINING_APOSTROPHE_RE = re.compile(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü])[’'`´](?=[A-Za-zÇĞİÖŞÜçğıöşü])")
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
    "bir",
    "ve",
    "ile",
    "icin",
    "için",
    "uzerine",
    "üzerine",
    "dergisi",
    "journal",
    "international",
    "university",
    "universitesi",
    "üniversitesi",
}


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
    value = (value or "").lower()
    value = JOINING_APOSTROPHE_RE.sub("", value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def compact_query(value: str) -> str:
    value = JOINING_APOSTROPHE_RE.sub("", value or "")
    value = value.replace("\u00ad", "")
    words = WORD_RE.findall(value)
    return " ".join(words).strip()


def salient_query(value: str, max_tokens: int = 10) -> str:
    words = compact_query(value).split()
    useful = [word for word in words if len(normalize_text(word)) > 2 and normalize_text(word) not in STOPWORDS]
    return " ".join(useful[:max_tokens]).strip()


def no_space_similarity(left: str, right: str) -> float:
    left_normalized = normalize_text(left).replace(" ", "")
    right_normalized = normalize_text(right).replace(" ", "")
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def text_similarity(left: str, right: str) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return max(
        SequenceMatcher(None, left_normalized, right_normalized).ratio(),
        no_space_similarity(left, right),
    )


def fuzzy_token_coverage(needle: str, haystack: str) -> float:
    needle_tokens = tokens(needle)
    haystack_tokens = set(tokens(haystack))
    haystack_compact = normalize_text(haystack).replace(" ", "")
    if not needle_tokens:
        return 0.0
    matched = 0
    for token in needle_tokens:
        if token in haystack_tokens or token in haystack_compact:
            matched += 1
    return matched / len(needle_tokens)


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def source_title(source: Dict[str, Any]) -> str:
    return first_text(source.get("orderTitle")) or first_text(source.get("title"))


def source_year(source: Dict[str, Any]) -> str:
    issue = source.get("issue") if isinstance(source.get("issue"), dict) else {}
    return str(source.get("publicationYear") or issue.get("year") or "")


def source_journal(source: Dict[str, Any]) -> str:
    journal = source.get("journal") if isinstance(source.get("journal"), dict) else {}
    return str(journal.get("name") or "")


def source_journal_code(source: Dict[str, Any]) -> str:
    journal = source.get("journal") if isinstance(source.get("journal"), dict) else {}
    return str(journal.get("id") or "")


def source_author_surnames(source: Dict[str, Any]) -> List[str]:
    authors = source.get("authors")
    if not isinstance(authors, list):
        return []
    surnames: List[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        name = author.get("inPublicationName") or author.get("name")
        if not isinstance(name, str):
            continue
        name_tokens = tokens(name)
        if name_tokens:
            surnames.append(name_tokens[-1])
    return surnames


def compact_source(source: Dict[str, Any], hit_score: Any = "") -> Dict[str, Any]:
    journal = source.get("journal") if isinstance(source.get("journal"), dict) else {}
    return {
        "trdizin_id": str(source.get("id") or ""),
        "title": source_title(source),
        "year": source_year(source),
        "journal": source_journal(source),
        "journal_code": source_journal_code(source),
        "issn": str(journal.get("issn") or ""),
        "eissn": str(journal.get("eissn") or ""),
        "doi": normalize_doi(str(source.get("doi") or "")),
        "doc_type": str(source.get("docType") or source.get("publicationType") or ""),
        "authors": source.get("authors") if isinstance(source.get("authors"), list) else [],
        "hit_score": hit_score if hit_score is not None else "",
    }


def make_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": f"trdizin-title-search-resolver/0.1 (mailto:{CONTACT_EMAIL})",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def parse_search_key(key: str) -> Tuple[str, str, str]:
    parts = key.split("|", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return "title", "", key


def fetch_search_key(key: str, timeout: float, rows: int, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    mode, year, query = parse_search_key(key)
    rate_limiter.wait()
    session = make_session()
    params: List[Tuple[str, str | int]] = [
        ("q", query),
        ("order", "publicationYear-DESC"),
        ("page", 1),
        ("limit", rows),
        ("facet-documentType", "PAPER"),
    ]
    if mode == "year" and year:
        params.append(("facet-publication_year", year))
    try:
        response = session.get(TRDIZIN_SEARCH_URL, params=params, timeout=timeout)
        if response.status_code == 429:
            return key, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        payload = response.json()
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        items = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source")
            if isinstance(source, dict):
                items.append(compact_source(source, hit.get("_score")))
        total = ((payload.get("hits") or {}).get("total") or {}) if isinstance(payload, dict) else {}
        return key, {"status": "ok", "http_status": response.status_code, "items": items, "total": total}
    except Exception as error:
        return key, {"status": "error", "error": str(error)}


def fill_missing_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    keys: List[str],
    worker_fn: Any,
    workers: int,
    timeout: float,
    max_start_rate: float,
    save_every: int,
    rows: int = 10,
) -> None:
    missing = [key for key in keys if key not in cache]
    if not missing:
        return
    rate_limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(worker_fn, key, timeout, rows, rate_limiter): key
            for key in missing
        }
        for future in as_completed(futures):
            key, result = future.result()
            cache[str(key)] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} requests for {cache_path.name}", flush=True)
    save_cache(cache_path, cache)


def fill_missing_crossref_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    dois: List[str],
    workers: int,
    timeout: float,
    max_start_rate: float,
    save_every: int,
) -> None:
    missing = [doi for doi in dois if doi not in cache]
    if not missing:
        return
    rate_limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_crossref_doi, doi, timeout, rate_limiter): doi
            for doi in missing
        }
        for future in as_completed(futures):
            doi, result = future.result()
            cache[str(doi)] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} Crossref DOI requests", flush=True)
    save_cache(cache_path, cache)


def accepted_exp12_status(value: str) -> bool:
    return value in {"strong_doi_crossref", "strong_doi_not_crossref_verified", "strong_trdizin_id"}


def base_found_after_experiment12(args: argparse.Namespace, sample_rows: List[Dict[str, str]]) -> Dict[str, set[str]]:
    base_sets = build_base_found(args, sample_rows)
    exp12 = {
        str(row.get("sample_index"))
        for row in read_csv(args.experiment12_csv)
        if accepted_exp12_status(str(row.get("trdizin_status") or ""))
    }
    base_sets["experiment12"] = exp12
    base_sets["base_after_experiment12"] = set(base_sets["base"]) | exp12
    return base_sets


def query_variants(title: str, year: str, max_variants: int) -> List[Tuple[str, str, str]]:
    full = compact_query(title)
    salient = salient_query(title)
    variants: List[Tuple[str, str, str]] = []
    for query_mode, query in [("title_full", full), ("title_salient", salient)]:
        if len(query) < 8:
            continue
        for mode in ["year", "title"]:
            key = f"{mode}|{year}|{query}" if mode == "year" and year else f"title||{query}"
            variants.append((query_mode if mode == "title" else f"{query_mode}_year", key, query))
    unique: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in variants:
        if item[1] in seen:
            continue
        seen.add(item[1])
        unique.append(item)
    return unique[:max_variants]


def build_candidate_rows(sample_rows: List[Dict[str, str]], base_found: set[str], max_query_variants: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in sample_rows:
        if row["sample_index"] in base_found:
            continue
        context = row.get("context") or ""
        parsed = parse_reference(context)
        if not parsed.title or not parsed.year:
            continue
        if len(tokens(parsed.title)) < 4:
            continue
        variants = query_variants(parsed.title, parsed.year, max_query_variants)
        if not variants:
            continue
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "source_doi": normalize_doi(row.get("doi", "")),
                "hidden_doi": extract_first_doi(context),
                "parsed_title": parsed.title,
                "parsed_journal": parsed.journal,
                "parsed_year": parsed.year,
                "parsed_authors": parsed.authors,
                "parser": parsed.parser,
                "query_keys": [item[1] for item in variants],
                "query_modes": [item[0] for item in variants],
                "queries": [item[2] for item in variants],
                "context": context,
            }
        )
    return sorted(rows, key=lambda item: int(item["sample_index"]))


def score_candidate(candidate: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    parsed_title = row.get("parsed_title") or ""
    parsed_journal = row.get("parsed_journal") or ""
    context = row.get("context") or ""
    candidate_title = candidate.get("title") or ""
    candidate_year = str(candidate.get("year") or "")
    candidate_journal = candidate.get("journal") or ""
    title_sim = text_similarity(parsed_title, candidate_title)
    title_cov = max(
        fuzzy_token_coverage(candidate_title, parsed_title),
        fuzzy_token_coverage(parsed_title, candidate_title),
        fuzzy_token_coverage(candidate_title, context),
    )
    parsed_token_count = len(tokens(parsed_title))
    years = context_years(context)
    year_match = bool(candidate_year and (candidate_year == str(row.get("parsed_year") or "") or candidate_year in years))
    journal_sim = text_similarity(parsed_journal, candidate_journal) if parsed_journal and candidate_journal else 0.0
    author_ratio = author_coverage(source_author_surnames(candidate), context)
    self_match = bool(candidate.get("trdizin_id") and str(candidate.get("trdizin_id")) == str(row.get("publication_id")))
    confidence = round((title_sim * 0.52) + (title_cov * 0.22) + ((1.0 if year_match else 0.0) * 0.14) + (journal_sim * 0.07) + (author_ratio * 0.05), 4)

    status = "no_match"
    if not self_match and parsed_token_count >= 4:
        supporting_signal = journal_sim >= 0.55 or author_ratio >= 0.25
        if title_sim >= 0.96 and year_match:
            status = "strong"
        elif title_sim >= 0.92 and year_match and supporting_signal:
            status = "strong"
        elif title_cov >= 0.9 and title_sim >= 0.86 and year_match and supporting_signal:
            status = "strong"
        elif title_sim >= 0.88 and year_match:
            status = "possible"
        elif title_cov >= 0.82 and title_sim >= 0.82 and year_match and supporting_signal:
            status = "possible"

    return {
        "status": status,
        "confidence": confidence,
        "title_similarity": round(title_sim, 4),
        "title_coverage": round(title_cov, 4),
        "title_token_count": parsed_token_count,
        "year_match": year_match,
        "journal_similarity": round(journal_sim, 4),
        "author_coverage": round(author_ratio, 4),
        "self_match": self_match,
        "candidate": candidate,
    }


def best_candidate(row: Dict[str, Any], search_cache: Dict[str, Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str, str]:
    scored: List[Tuple[Dict[str, Any], str, str]] = []
    for query_mode, key, query in zip(row.get("query_modes") or [], row.get("query_keys") or [], row.get("queries") or []):
        result = search_cache.get(key)
        if not result or result.get("status") != "ok":
            continue
        for candidate in result.get("items") or []:
            if isinstance(candidate, dict):
                scored.append((score_candidate(candidate, row), query_mode, query))
    if not scored:
        return None, "", ""
    rank = {"strong": 2, "possible": 1, "no_match": 0}
    best = max(
        scored,
        key=lambda item: (
            rank[item[0]["status"]],
            item[0]["confidence"],
            item[0]["title_similarity"],
            item[0]["title_coverage"],
        ),
    )
    return best


def score_row(row: Dict[str, Any], search_cache: Dict[str, Dict[str, Any]], crossref_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    score, query_mode, query = best_candidate(row, search_cache)
    output = {
        "sample_index": row.get("sample_index", ""),
        "publication_id": row.get("publication_id", ""),
        "reference_id": row.get("reference_id", ""),
        "reference_order": row.get("reference_order", ""),
        "source_doi": row.get("source_doi", ""),
        "hidden_doi": row.get("hidden_doi", ""),
        "parser": row.get("parser", ""),
        "parsed_title": row.get("parsed_title", ""),
        "parsed_journal": row.get("parsed_journal", ""),
        "parsed_year": row.get("parsed_year", ""),
        "parsed_authors": row.get("parsed_authors", ""),
        "query_mode": query_mode,
        "query": query,
        "trdizin_title_status": "no_match",
        "trdizin_id": "",
        "target_doi": "",
        "target_crossref_status": "",
        "target_crossref_doi": "",
        "target_title": "",
        "target_year": "",
        "target_journal": "",
        "target_journal_code": "",
        "target_doc_type": "",
        "confidence": "",
        "title_similarity": "",
        "title_coverage": "",
        "title_token_count": "",
        "year_match": "",
        "journal_similarity": "",
        "author_coverage": "",
        "self_match": "",
        "context": row.get("context", ""),
    }
    if not score:
        return output
    candidate = score["candidate"]
    doi = candidate.get("doi") or ""
    output.update(
        {
            "trdizin_title_status": score["status"],
            "trdizin_id": candidate.get("trdizin_id") or "",
            "target_doi": doi,
            "target_title": candidate.get("title") or "",
            "target_year": candidate.get("year") or "",
            "target_journal": candidate.get("journal") or "",
            "target_journal_code": candidate.get("journal_code") or "",
            "target_doc_type": candidate.get("doc_type") or "",
            "confidence": score["confidence"],
            "title_similarity": score["title_similarity"],
            "title_coverage": score["title_coverage"],
            "title_token_count": score["title_token_count"],
            "year_match": score["year_match"],
            "journal_similarity": score["journal_similarity"],
            "author_coverage": score["author_coverage"],
            "self_match": score["self_match"],
        }
    )
    if doi:
        crossref_result = crossref_cache.get(doi)
        output["target_crossref_status"] = str((crossref_result or {}).get("status") or "not_checked")
        output["target_crossref_doi"] = normalize_doi(str((crossref_result or {}).get("doi") or ""))
    else:
        output["target_crossref_status"] = "no_doi"
    return output


def build_summary(
    sample_rows: List[Dict[str, str]],
    base_sets: Dict[str, set[str]],
    target_rows: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total = len(sample_rows)
    base_found = len(base_sets["base_after_experiment12"])
    strong = sum(1 for row in result_rows if row.get("trdizin_title_status") == "strong")
    possible = sum(1 for row in result_rows if row.get("trdizin_title_status") == "possible")
    no_match = sum(1 for row in result_rows if row.get("trdizin_title_status") == "no_match")
    strong_with_doi = sum(1 for row in result_rows if row.get("trdizin_title_status") == "strong" and row.get("target_doi"))
    strong_crossref_doi = sum(
        1 for row in result_rows if row.get("trdizin_title_status") == "strong" and row.get("target_crossref_status") == "ok"
    )
    experiment_found = base_found + strong
    return {
        "experiment_label": "Deney 13 - TR Dizin title search resolver",
        "sampled_references": total,
        "base_found_before_experiment13": base_found,
        "base_found_before_experiment13_rate_percent": percent(base_found, total),
        "remaining_before_experiment13": total - base_found,
        "title_search_targets": len(target_rows),
        "trdizin_title_strong_matches": strong,
        "trdizin_title_possible_matches": possible,
        "trdizin_title_no_match": no_match,
        "trdizin_title_strong_with_doi": strong_with_doi,
        "trdizin_title_strong_crossref_doi_found": strong_crossref_doi,
        "experiment13_auto_resolved_found": experiment_found,
        "experiment13_auto_resolved_rate_percent": percent(experiment_found, total),
        "experiment13_new_auto_resolved_rate_percent": percent(strong, total),
        "complete": True,
        "component_counts": {
            "base_union_after_experiment12": base_found,
            "trdizin_title_crossref_doi": strong_crossref_doi,
            "trdizin_title_id_only_or_unverified_doi": strong - strong_crossref_doi,
        },
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Deney 13 - TR Dizin Title Search Resolver",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 12 sonrasi baz bulunan: {summary['base_found_before_experiment13']} ({summary['base_found_before_experiment13_rate_percent']}%)",
        f"- Deney 13 oncesi kalan: {summary['remaining_before_experiment13']}",
        f"- Title search hedefi: {summary['title_search_targets']}",
        f"- Strong yeni eslesme: {summary['trdizin_title_strong_matches']}",
        f"- Possible aday: {summary['trdizin_title_possible_matches']}",
        f"- No match: {summary['trdizin_title_no_match']}",
        f"- Strong DOI var: {summary['trdizin_title_strong_with_doi']}",
        f"- Strong DOI Crossref'te dogrulandi: {summary['trdizin_title_strong_crossref_doi_found']}",
        "",
        "## Deney 13 Sonuc",
        "",
        f"- All strict resolved toplam: {summary['experiment13_auto_resolved_found']} ({summary['experiment13_auto_resolved_rate_percent']}%)",
        f"- Yeni resolved artis: {summary['trdizin_title_strong_matches']} ({summary['experiment13_new_auto_resolved_rate_percent']}% toplam)",
        "",
        "Not: Bu deney targetPublication alanı olmayan kalan referanslarda parsed title/year ile TR Dizin aramasi yapar. Sadece title similarity, yil ve destekleyici journal/author sinyali guclu olanlar strict sayilir.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experiment 13: resolve remaining references through TR Dizin title search.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-csv", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.csv"), type=Path)
    parser.add_argument("--dergipark-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.csv"), type=Path)
    parser.add_argument("--cleanup-csv", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/crossref_cleanup_matches.csv"), type=Path)
    parser.add_argument("--europepmc-csv", default=Path("trdizin_crossref_doi_stats_10k/europepmc_fallback/europepmc_fallback_matches.csv"), type=Path)
    parser.add_argument("--article-file-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_article_file_probe/dergipark_article_file_probe_matches.csv"), type=Path)
    parser.add_argument("--experiment11-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment11_journal_like/experiment11_matches.csv"), type=Path)
    parser.add_argument("--experiment12-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment12_trdizin_target/trdizin_target_publication_matches.csv"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/experiment13_trdizin_title_search"), type=Path)
    parser.add_argument("--rows", default=10, type=int)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--max-start-rate", default=8.0, type=float)
    parser.add_argument("--save-every", default=50, type=int)
    parser.add_argument("--max-query-variants", default=4, type=int)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    search_cache_path = args.out_dir / "trdizin_title_search_cache.json"
    crossref_cache_path = args.out_dir / "trdizin_title_search_crossref_doi_cache.json"
    search_cache = load_cache(search_cache_path)
    crossref_cache = load_cache(crossref_cache_path)

    if args.retry_errors:
        for cache_path, cache in [(search_cache_path, search_cache), (crossref_cache_path, crossref_cache)]:
            retryable = [key for key, value in cache.items() if value.get("status") in {"error", "rate_limited"}]
            for key in retryable:
                del cache[key]
            if retryable:
                save_cache(cache_path, cache)
                print(f"removed {len(retryable)} retryable cached errors from {cache_path.name}", flush=True)

    sample_rows = read_csv(args.sample_csv)
    base_sets = base_found_after_experiment12(args, sample_rows)
    target_rows = build_candidate_rows(sample_rows, base_sets["base_after_experiment12"], args.max_query_variants)
    search_keys: List[str] = []
    for row in target_rows:
        for key in row.get("query_keys") or []:
            if key not in search_keys:
                search_keys.append(key)

    print(
        f"sample={len(sample_rows)} base_after_exp12={len(base_sets['base_after_experiment12'])} targets={len(target_rows)} search_keys={len(search_keys)} cached={len(search_cache)}",
        flush=True,
    )

    if not args.score_only:
        fill_missing_cache(
            cache_path=search_cache_path,
            cache=search_cache,
            keys=search_keys,
            worker_fn=fetch_search_key,
            workers=args.workers,
            timeout=args.timeout,
            max_start_rate=args.max_start_rate,
            save_every=args.save_every,
            rows=args.rows,
        )

    result_rows = [score_row(row, search_cache, crossref_cache) for row in target_rows]
    strong_dois: List[str] = []
    for row in result_rows:
        if row.get("trdizin_title_status") == "strong" and row.get("target_doi") and row["target_doi"] not in strong_dois:
            strong_dois.append(row["target_doi"])

    if strong_dois and not args.score_only:
        fill_missing_crossref_cache(
            cache_path=crossref_cache_path,
            cache=crossref_cache,
            dois=strong_dois,
            workers=max(1, min(args.workers, 6)),
            timeout=args.timeout,
            max_start_rate=max(1.0, min(args.max_start_rate, 6.0)),
            save_every=args.save_every,
        )
        result_rows = [score_row(row, search_cache, crossref_cache) for row in target_rows]

    summary = build_summary(sample_rows, base_sets, target_rows, result_rows)
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "source_doi",
        "hidden_doi",
        "parser",
        "parsed_title",
        "parsed_journal",
        "parsed_year",
        "parsed_authors",
        "query_mode",
        "query",
        "trdizin_title_status",
        "trdizin_id",
        "target_doi",
        "target_crossref_status",
        "target_crossref_doi",
        "target_title",
        "target_year",
        "target_journal",
        "target_journal_code",
        "target_doc_type",
        "confidence",
        "title_similarity",
        "title_coverage",
        "title_token_count",
        "year_match",
        "journal_similarity",
        "author_coverage",
        "self_match",
        "context",
    ]
    write_csv(args.out_dir / "trdizin_title_search_matches.csv", fieldnames, result_rows)
    write_jsonl(args.out_dir / "trdizin_title_search_matches.jsonl", result_rows)
    review_rows = [row for row in result_rows if row.get("trdizin_title_status") == "possible"]
    write_csv(args.out_dir / "trdizin_title_search_review_candidates.csv", fieldnames, review_rows)
    write_json(args.out_dir / "trdizin_title_search_summary.json", summary)
    write_report(args.out_dir / "trdizin_title_search_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
