#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from trdizin_dergipark_oai_fallback import extract_dergipark_evidence, get_record, make_session as make_dergipark_session, score_candidate
from trdizin_experiment13_trdizin_title_search import base_found_after_experiment12
from trdizin_experiment12_trdizin_target_publication import (
    CONTACT_EMAIL,
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
from trdizin_experiment11_journal_like_parser_dergipark import parse_reference
from trdizin_openalex_fallback import author_coverage, context_years, title_coverage, title_similarity, tokens
from trdizin_remaining_after_experiment10_stats import PATTERNS, classify_remaining


CROSSREF_STRONG_STATUSES = {"strong", "possible"}
DOI_RE = re.compile(r"(10\.\d{4,9}\s*/\s*[^\s\"'<>]+)", re.IGNORECASE)
DERGIPARK_FILE_RE = re.compile(r"dergipark\.(?:org|gov)\.tr/(?:tr|en)?/?download/article-file/([0-9]+)", re.IGNORECASE)
ISBN_RE = re.compile(
    r"(?:ISBN(?:-1[03])?[:\s]*)?"
    r"((?:97[89][-\s]?)?[0-9][0-9Xx][-\s0-9Xx]{8,20})",
    re.IGNORECASE,
)
ECITMATCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/ecitmatch.cgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
OPENCITATIONS_META_URL = "https://api.opencitations.net/meta/v1/metadata/isbn:{isbn}"
BIOMEDICAL_RE = re.compile(
    r"\b("
    r"JAMA|Lancet|BMJ|PubMed|Medline|Medicine|Medical|Clinical|Clinic|Nurs|Nursing|"
    r"Pediatr|Pediatric|Cardiovasc|Surg|Surgery|Oncol|Cancer|Neurol|Psychiat|"
    r"Ophthalmol|Radiol|Pharm|Biol|Chem|Health|Hosp|Ther|Disease|Patient|"
    r"Hemşire|Hemsire|Sağlık|Saglik|Tıp|Tip|Pediatri|Klinik"
    r")\b",
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


def make_json_session(user_agent: str) -> requests.Session:
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
    session.headers.update({"Accept": "application/json", "User-Agent": user_agent})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def current_base_found(args: argparse.Namespace, sample_rows: List[Dict[str, str]]) -> set[str]:
    found_sets = base_found_after_experiment12(args, sample_rows)
    experiment13 = {
        str(row.get("sample_index"))
        for row in read_csv(args.experiment13_csv)
        if row.get("trdizin_title_status") == "strong"
    }
    return found_sets["base_after_experiment12"] | experiment13


def add_status_found(found: set[str], path: Path, status_column: str, accepted: set[str]) -> set[str]:
    output = set(found)
    for row in read_csv(path):
        if row.get(status_column) in accepted:
            output.add(str(row.get("sample_index")))
    return output


def found_after_experiment14(found: set[str], args: argparse.Namespace) -> set[str]:
    return add_status_found(found, args.experiment14_csv, "hidden_doi_status", {"strong"})


def found_after_experiment15(found: set[str], args: argparse.Namespace) -> set[str]:
    return add_status_found(found, args.experiment15_csv, "dergipark_file_status", {"strong"})


def found_after_experiment16(found: set[str], args: argparse.Namespace) -> set[str]:
    return add_status_found(found, args.experiment16_csv, "isbn_status", {"strong"})


def found_after_experiment18(found: set[str], args: argparse.Namespace) -> set[str]:
    return add_status_found(found, args.experiment18_csv, "pubmed_status", {"strong"})


def remaining_sample_rows(sample_rows: List[Dict[str, str]], found: set[str]) -> List[Dict[str, str]]:
    return [row for row in sample_rows if row["sample_index"] not in found]


def write_report(path: Path, title: str, lines: List[str]) -> None:
    path.write_text("\n".join([f"# {title}", "", *lines, ""]), encoding="utf-8")


def extract_doi_candidates(context: str) -> List[str]:
    candidates: List[str] = []
    for match in DOI_RE.finditer(context or ""):
        doi = normalize_doi(match.group(1))
        doi = doi.rstrip(".")
        if doi.startswith("10.") and doi not in candidates:
            candidates.append(doi)
    return candidates


def fetch_crossref_cache(
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
    limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_crossref_doi, doi, timeout, limiter): doi for doi in missing}
        for future in as_completed(futures):
            doi, result = future.result()
            cache[doi] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} Crossref DOI requests", flush=True)
    save_cache(cache_path, cache)


def run_experiment14(args: argparse.Namespace, sample_rows: List[Dict[str, str]], base_found: set[str]) -> set[str]:
    out_dir = args.out_dir / "experiment14_hidden_doi"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for row in remaining_sample_rows(sample_rows, base_found):
        dois = extract_doi_candidates(row.get("context") or "")
        if not dois:
            continue
        targets.append({**row, "doi_candidates": dois})

    cache_path = out_dir / "hidden_doi_crossref_cache.json"
    cache = load_cache(cache_path)
    all_dois = sorted({doi for row in targets for doi in row["doi_candidates"]})
    fetch_crossref_cache(cache_path, cache, all_dois, args.workers, args.timeout, args.crossref_rate, args.save_every)

    rows = []
    for row in targets:
        best_doi = ""
        best_status = "no_match"
        http_status = ""
        for doi in row["doi_candidates"]:
            result = cache.get(doi) or {}
            if result.get("status") == "ok":
                best_doi = doi
                best_status = "strong"
                http_status = str(result.get("http_status") or "")
                break
            if result.get("status") in {"not_found", "error", "rate_limited"} and not best_doi:
                best_doi = doi
                best_status = str(result.get("status") or "no_match")
                http_status = str(result.get("http_status") or "")
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "doi_candidates": ";".join(row["doi_candidates"]),
                "hidden_doi_status": best_status,
                "hidden_doi": best_doi,
                "crossref_http_status": http_status,
                "context": row.get("context", ""),
            }
        )

    strong = sum(1 for row in rows if row["hidden_doi_status"] == "strong")
    found = len(base_found) + strong
    summary = {
        "experiment_label": "Deney 14 - Hidden DOI cleanup",
        "sampled_references": len(sample_rows),
        "base_found_before_experiment14": len(base_found),
        "base_found_before_experiment14_rate_percent": percent(len(base_found), len(sample_rows)),
        "hidden_doi_targets": len(targets),
        "hidden_doi_unique_candidates": len(all_dois),
        "hidden_doi_strong_matches": strong,
        "hidden_doi_no_match": sum(1 for row in rows if row["hidden_doi_status"] != "strong"),
        "experiment14_auto_resolved_found": found,
        "experiment14_auto_resolved_rate_percent": percent(found, len(sample_rows)),
        "complete": True,
    }
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "doi_candidates",
        "hidden_doi_status",
        "hidden_doi",
        "crossref_http_status",
        "context",
    ]
    write_csv(out_dir / "hidden_doi_matches.csv", fieldnames, rows)
    write_jsonl(out_dir / "hidden_doi_matches.jsonl", rows)
    write_json(out_dir / "hidden_doi_summary.json", summary)
    write_report(
        out_dir / "hidden_doi_report_tr.md",
        "Deney 14 - Hidden DOI Cleanup",
        [
            f"- Deney 13 sonrasi baz: {summary['base_found_before_experiment14']} ({summary['base_found_before_experiment14_rate_percent']}%)",
            f"- Hidden DOI hedefi: {summary['hidden_doi_targets']}",
            f"- Strong Crossref DOI: {summary['hidden_doi_strong_matches']}",
            f"- Yeni toplam: {summary['experiment14_auto_resolved_found']} ({summary['experiment14_auto_resolved_rate_percent']}%)",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return found_after_experiment14(base_found, argparse.Namespace(experiment14_csv=out_dir / "hidden_doi_matches.csv"))


def run_experiment15(args: argparse.Namespace, sample_rows: List[Dict[str, str]], base_found: set[str]) -> set[str]:
    out_dir = args.out_dir / "experiment15_dergipark_article_file"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for row in remaining_sample_rows(sample_rows, base_found):
        evidence = extract_dergipark_evidence(row.get("context") or "")
        article_file_id = evidence.get("article_file_id")
        if article_file_id and not evidence.get("article_id"):
            targets.append({**row, "article_file_id": article_file_id})

    cache_path = out_dir / "dergipark_article_file_cache.json"
    cache = load_cache(cache_path)
    session = make_dergipark_session()
    for index, row in enumerate(targets, start=1):
        key = f"file-as-article:{row['article_file_id']}"
        if key not in cache:
            cache[key] = get_record(
                session=session,
                slug="",
                article_id=row["article_file_id"],
                timeout=args.timeout,
                retries=0,
                sleep_seconds=0,
                fetch_mode="jina",
            )
            save_cache(cache_path, cache)
        print(f"Deney 15 article-file {index}/{len(targets)}", flush=True)

    rows = []
    for row in targets:
        result = cache.get(f"file-as-article:{row['article_file_id']}", {})
        output = {
            "sample_index": row.get("sample_index", ""),
            "publication_id": row.get("publication_id", ""),
            "reference_id": row.get("reference_id", ""),
            "reference_order": row.get("reference_order", ""),
            "article_file_id": row.get("article_file_id", ""),
            "dergipark_file_status": "request_error" if result.get("status") != "ok" else "no_match",
            "oai_identifier": "",
            "dergipark_doi": "",
            "dergipark_title": "",
            "dergipark_year": "",
            "confidence": "",
            "title_coverage": "",
            "title_similarity": "",
            "title_token_count": "",
            "author_coverage": "",
            "year_match": "",
            "context": row.get("context", ""),
        }
        items = result.get("items") if isinstance(result.get("items"), list) else []
        if items:
            score = max((score_candidate(item, row.get("context") or "") for item in items), key=lambda item: item.confidence)
            candidate = score.candidate
            output.update(
                {
                    "dergipark_file_status": score.match_status,
                    "oai_identifier": candidate.get("oai_identifier") or "",
                    "dergipark_doi": candidate.get("doi") or "",
                    "dergipark_title": candidate.get("title") or "",
                    "dergipark_year": candidate.get("year") or "",
                    "confidence": score.confidence,
                    "title_coverage": score.title_coverage,
                    "title_similarity": score.title_similarity,
                    "title_token_count": score.title_token_count,
                    "author_coverage": score.author_coverage,
                    "year_match": score.year_match,
                }
            )
        rows.append(output)

    strong = sum(1 for row in rows if row["dergipark_file_status"] == "strong")
    possible = sum(1 for row in rows if row["dergipark_file_status"] == "possible")
    found = len(base_found) + strong
    summary = {
        "experiment_label": "Deney 15 - DergiPark article-file resolver",
        "sampled_references": len(sample_rows),
        "base_found_before_experiment15": len(base_found),
        "base_found_before_experiment15_rate_percent": percent(len(base_found), len(sample_rows)),
        "dergipark_article_file_targets": len(targets),
        "dergipark_article_file_strong_matches": strong,
        "dergipark_article_file_possible_matches": possible,
        "dergipark_article_file_no_match": sum(1 for row in rows if row["dergipark_file_status"] == "no_match"),
        "dergipark_article_file_request_errors": sum(1 for row in rows if row["dergipark_file_status"] == "request_error"),
        "experiment15_auto_resolved_found": found,
        "experiment15_auto_resolved_rate_percent": percent(found, len(sample_rows)),
        "complete": True,
    }
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "article_file_id",
        "dergipark_file_status",
        "oai_identifier",
        "dergipark_doi",
        "dergipark_title",
        "dergipark_year",
        "confidence",
        "title_coverage",
        "title_similarity",
        "title_token_count",
        "author_coverage",
        "year_match",
        "context",
    ]
    write_csv(out_dir / "dergipark_article_file_matches.csv", fieldnames, rows)
    write_jsonl(out_dir / "dergipark_article_file_matches.jsonl", rows)
    write_json(out_dir / "dergipark_article_file_summary.json", summary)
    write_report(
        out_dir / "dergipark_article_file_report_tr.md",
        "Deney 15 - DergiPark Article-file Resolver",
        [
            f"- Deney 14 sonrasi baz: {summary['base_found_before_experiment15']} ({summary['base_found_before_experiment15_rate_percent']}%)",
            f"- Article-file hedefi: {summary['dergipark_article_file_targets']}",
            f"- Strong: {summary['dergipark_article_file_strong_matches']}",
            f"- Possible: {summary['dergipark_article_file_possible_matches']}",
            f"- Yeni toplam: {summary['experiment15_auto_resolved_found']} ({summary['experiment15_auto_resolved_rate_percent']}%)",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return found_after_experiment15(base_found, argparse.Namespace(experiment15_csv=out_dir / "dergipark_article_file_matches.csv"))


def isbn_digits(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def valid_isbn10(value: str) -> bool:
    if len(value) != 10:
        return False
    total = 0
    for index, char in enumerate(value):
        if char == "X":
            digit = 10
        elif char.isdigit():
            digit = int(char)
        else:
            return False
        total += digit * (10 - index)
    return total % 11 == 0


def valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit() or not value.startswith(("978", "979")):
        return False
    total = sum((int(char) * (1 if index % 2 == 0 else 3)) for index, char in enumerate(value[:12]))
    check = (10 - (total % 10)) % 10
    return check == int(value[-1])


def extract_isbns(context: str) -> List[str]:
    isbns: List[str] = []
    for match in ISBN_RE.finditer(context or ""):
        value = isbn_digits(match.group(1))
        if (valid_isbn13(value) or valid_isbn10(value)) and value not in isbns:
            isbns.append(value)
    return isbns


def normalize_for_match(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def text_match_score(title: str, context: str) -> Tuple[float, float]:
    title_norm = normalize_for_match(title)
    context_norm = normalize_for_match(context)
    if not title_norm or not context_norm:
        return 0.0, 0.0
    similarity = SequenceMatcher(None, title_norm, context_norm).ratio()
    title_tokens = [token for token in title_norm.split() if len(token) > 2]
    context_tokens = set(context_norm.split())
    coverage = len([token for token in title_tokens if token in context_tokens]) / max(1, len(title_tokens))
    return round(similarity, 4), round(coverage, 4)


def fetch_opencitations_isbn(key: str, timeout: float, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_json_session(f"trdizin-isbn-opencitations/0.1 (mailto:{CONTACT_EMAIL})")
    try:
        response = session.get(OPENCITATIONS_META_URL.format(isbn=quote(key, safe="")), timeout=timeout)
        if response.status_code == 429:
            return key, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        payload = response.json()
        return key, {"status": "ok", "items": payload if isinstance(payload, list) else [], "http_status": response.status_code}
    except Exception as error:
        return key, {"status": "error", "error": str(error)}


def fill_key_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    keys: List[str],
    worker_fn: Callable[[str, float, RateLimiter], Tuple[str, Dict[str, Any]]],
    workers: int,
    timeout: float,
    max_start_rate: float,
    save_every: int,
) -> None:
    missing = [key for key in keys if key not in cache]
    if not missing:
        return
    limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker_fn, key, timeout, limiter): key for key in missing}
        for future in as_completed(futures):
            key, result = future.result()
            cache[key] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} requests for {cache_path.name}", flush=True)
    save_cache(cache_path, cache)


def run_experiment16(args: argparse.Namespace, sample_rows: List[Dict[str, str]], base_found: set[str]) -> set[str]:
    out_dir = args.out_dir / "experiment16_isbn_book"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for row in remaining_sample_rows(sample_rows, base_found):
        isbns = extract_isbns(row.get("context") or "")
        if isbns:
            targets.append({**row, "isbns": isbns})

    cache_path = out_dir / "isbn_opencitations_cache.json"
    cache = load_cache(cache_path)
    all_isbns = sorted({isbn for row in targets for isbn in row["isbns"]})
    fill_key_cache(cache_path, cache, all_isbns, fetch_opencitations_isbn, args.workers, args.timeout, args.opencitations_rate, args.save_every)

    rows = []
    for row in targets:
        best_item: Dict[str, Any] = {}
        best_isbn = ""
        best_similarity = 0.0
        best_coverage = 0.0
        for isbn in row["isbns"]:
            result = cache.get(isbn) or {}
            for item in result.get("items") or []:
                if not isinstance(item, dict):
                    continue
                similarity, coverage = text_match_score(item.get("title") or "", row.get("context") or "")
                if (coverage, similarity) > (best_coverage, best_similarity):
                    best_item = item
                    best_isbn = isbn
                    best_similarity = similarity
                    best_coverage = coverage
        status = "no_match"
        if best_item and best_coverage >= 0.55:
            status = "strong"
        elif best_item:
            status = "possible"
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "isbn_candidates": ";".join(row["isbns"]),
                "isbn_status": status,
                "matched_isbn": best_isbn,
                "opencitations_id": best_item.get("id") if best_item else "",
                "opencitations_title": best_item.get("title") if best_item else "",
                "opencitations_type": best_item.get("type") if best_item else "",
                "opencitations_pub_date": best_item.get("pub_date") if best_item else "",
                "opencitations_venue": best_item.get("venue") if best_item else "",
                "opencitations_publisher": best_item.get("publisher") if best_item else "",
                "title_similarity": best_similarity if best_item else "",
                "title_coverage": best_coverage if best_item else "",
                "context": row.get("context", ""),
            }
        )

    strong = sum(1 for row in rows if row["isbn_status"] == "strong")
    possible = sum(1 for row in rows if row["isbn_status"] == "possible")
    found = len(base_found) + strong
    summary = {
        "experiment_label": "Deney 16 - ISBN / book resolver",
        "sampled_references": len(sample_rows),
        "base_found_before_experiment16": len(base_found),
        "base_found_before_experiment16_rate_percent": percent(len(base_found), len(sample_rows)),
        "isbn_targets": len(targets),
        "isbn_unique_candidates": len(all_isbns),
        "isbn_strong_matches": strong,
        "isbn_possible_matches": possible,
        "isbn_no_match": sum(1 for row in rows if row["isbn_status"] == "no_match"),
        "experiment16_auto_resolved_found": found,
        "experiment16_auto_resolved_rate_percent": percent(found, len(sample_rows)),
        "complete": True,
    }
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "isbn_candidates",
        "isbn_status",
        "matched_isbn",
        "opencitations_id",
        "opencitations_title",
        "opencitations_type",
        "opencitations_pub_date",
        "opencitations_venue",
        "opencitations_publisher",
        "title_similarity",
        "title_coverage",
        "context",
    ]
    write_csv(out_dir / "isbn_book_matches.csv", fieldnames, rows)
    write_jsonl(out_dir / "isbn_book_matches.jsonl", rows)
    write_json(out_dir / "isbn_book_summary.json", summary)
    write_report(
        out_dir / "isbn_book_report_tr.md",
        "Deney 16 - ISBN / Book Resolver",
        [
            f"- Deney 15 sonrasi baz: {summary['base_found_before_experiment16']} ({summary['base_found_before_experiment16_rate_percent']}%)",
            f"- ISBN hedefi: {summary['isbn_targets']}",
            f"- Strong ISBN/OpenCitations eslesme: {summary['isbn_strong_matches']}",
            f"- Possible: {summary['isbn_possible_matches']}",
            f"- Yeni toplam: {summary['experiment16_auto_resolved_found']} ({summary['experiment16_auto_resolved_rate_percent']}%)",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return found_after_experiment16(base_found, argparse.Namespace(experiment16_csv=out_dir / "isbn_book_matches.csv"))


def run_experiment17(args: argparse.Namespace, sample_rows: List[Dict[str, str]], base_found: set[str]) -> None:
    out_dir = args.out_dir / "experiment17_doi_eligible_denominator"
    out_dir.mkdir(parents=True, exist_ok=True)
    remaining_rows = remaining_sample_rows(sample_rows, base_found)
    classified = classify_remaining(remaining_rows)
    categories = {}
    for row in classified:
        categories[row["exclusive_category"]] = categories.get(row["exclusive_category"], 0) + 1
    doi_unlikely_categories = {"book_or_chapter", "url_web", "thesis", "report_policy_legal", "conference"}
    doi_unlikely_remaining = sum(categories.get(category, 0) for category in doi_unlikely_categories)
    operational_denominator = len(sample_rows) - doi_unlikely_remaining
    summary = {
        "experiment_label": "Deney 17 - DOI eligible denominator",
        "sampled_references": len(sample_rows),
        "auto_resolved_before_experiment17": len(base_found),
        "auto_resolved_before_experiment17_rate_percent": percent(len(base_found), len(sample_rows)),
        "remaining_before_experiment17": len(remaining_rows),
        "remaining_doi_unlikely_count": doi_unlikely_remaining,
        "remaining_doi_unlikely_rate_percent": percent(doi_unlikely_remaining, len(remaining_rows)),
        "operational_doi_eligible_denominator": operational_denominator,
        "operational_doi_eligible_resolution_rate_percent": percent(len(base_found), operational_denominator),
        "remaining_category_counts": categories,
        "note": "Denominator, cozulmeyen kalan setten kitap/web/tez/rapor/konferans gibi DOI beklenmesi zayif kategorileri cikarir; otomatik strong eslesme sayisini degistirmez.",
    }
    write_json(out_dir / "doi_eligible_denominator_summary.json", summary)
    write_report(
        out_dir / "doi_eligible_denominator_report_tr.md",
        "Deney 17 - DOI Eligible Denominator",
        [
            f"- Mevcut auto-resolved: {summary['auto_resolved_before_experiment17']} ({summary['auto_resolved_before_experiment17_rate_percent']}%)",
            f"- Kalan: {summary['remaining_before_experiment17']}",
            f"- Kalan DOI-unlikely: {summary['remaining_doi_unlikely_count']} ({summary['remaining_doi_unlikely_rate_percent']}% kalan)",
            f"- Operasyonel DOI-eligible denominator: {summary['operational_doi_eligible_denominator']}",
            f"- Bu denominator ile resolved oranı: {summary['operational_doi_eligible_resolution_rate_percent']}%",
            "- Not: Bu deney yeni eslesme eklemez, denominator raporu uretir.",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


def parse_volume_first_page(context: str) -> Tuple[str, str]:
    patterns = [
        r"\b(?P<volume>\d{1,4})\s*\([^)]{0,25}\)\s*[:,]\s*(?P<page>\d{1,6})",
        r"\b(?P<volume>\d{1,4})\s*[:,]\s*(?P<page>\d{1,6})",
        r"\b(?P<volume>\d{1,4})\s*;\s*\d{0,4}\s*:?\s*(?P<page>\d{1,6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, context or "")
        if match:
            return match.group("volume"), match.group("page")
    return "", ""


def first_author_for_pubmed(value: str) -> str:
    author = (value or "").split(",", 1)[0].strip()
    parts = author.split()
    return parts[-1] if parts else ""


def pubmed_bdata(row: Dict[str, Any]) -> str:
    journal = row.get("parsed_journal") or ""
    year = row.get("parsed_year") or ""
    volume, page = parse_volume_first_page(row.get("context") or "")
    author = first_author_for_pubmed(row.get("parsed_authors") or "")
    return f"{journal}|{year}|{volume}|{page}|{author}||"


def fetch_pubmed_ecitmatch(key: str, timeout: float, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_json_session(f"trdizin-pubmed-ecitmatch/0.1 (mailto:{CONTACT_EMAIL})")
    try:
        response = session.get(ECITMATCH_URL, params={"db": "pubmed", "retmode": "xml", "bdata": key}, timeout=timeout)
        if response.status_code == 429:
            return key, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        text = response.text.strip()
        pmid = ""
        if text:
            parts = text.split("|")
            if parts and parts[-1].strip().isdigit():
                pmid = parts[-1].strip()
        return key, {"status": "ok", "pmid": pmid, "raw": text}
    except Exception as error:
        return key, {"status": "error", "error": str(error)}


def fetch_pubmed_metadata(key: str, timeout: float, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_json_session(f"trdizin-pubmed-efetch/0.1 (mailto:{CONTACT_EMAIL})")
    try:
        response = session.get(EFETCH_URL, params={"db": "pubmed", "retmode": "xml", "id": key}, timeout=timeout)
        if response.status_code == 429:
            return key, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        root = ET.fromstring(response.text)
        article = root.find(".//Article")
        title = " ".join("".join(article.find(".//ArticleTitle").itertext()).split()) if article is not None and article.find(".//ArticleTitle") is not None else ""
        journal = root.findtext(".//Journal/Title", default="") or root.findtext(".//Journal/ISOAbbreviation", default="")
        year = root.findtext(".//PubDate/Year", default="")
        doi = ""
        for node in root.findall(".//ArticleId"):
            if node.get("IdType") == "doi":
                doi = normalize_doi(node.text or "")
                break
        return key, {"status": "ok", "pmid": key, "title": title, "journal": journal, "year": year, "doi": doi}
    except Exception as error:
        return key, {"status": "error", "error": str(error)}


def run_experiment18(args: argparse.Namespace, sample_rows: List[Dict[str, str]], base_found: set[str]) -> set[str]:
    out_dir = args.out_dir / "experiment18_pubmed_citation_matcher"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = []
    for row in remaining_sample_rows(sample_rows, base_found):
        context = row.get("context") or ""
        parsed = parse_reference(context)
        if not parsed.title or not parsed.year or not parsed.journal:
            continue
        volume, page = parse_volume_first_page(context)
        if not page:
            continue
        if not BIOMEDICAL_RE.search(context):
            continue
        target = {
            **row,
            "parsed_title": parsed.title,
            "parsed_journal": parsed.journal,
            "parsed_year": parsed.year,
            "parsed_authors": parsed.authors,
            "volume": volume,
            "first_page": page,
        }
        target["bdata"] = pubmed_bdata(target)
        targets.append(target)

    match_cache_path = out_dir / "pubmed_ecitmatch_cache.json"
    metadata_cache_path = out_dir / "pubmed_metadata_cache.json"
    match_cache = load_cache(match_cache_path)
    metadata_cache = load_cache(metadata_cache_path)
    bdata_keys = sorted({row["bdata"] for row in targets})
    fill_key_cache(match_cache_path, match_cache, bdata_keys, fetch_pubmed_ecitmatch, min(args.workers, 3), args.timeout, args.pubmed_rate, args.save_every)
    pmids = sorted({result.get("pmid") for result in match_cache.values() if result.get("pmid")})
    fill_key_cache(metadata_cache_path, metadata_cache, pmids, fetch_pubmed_metadata, min(args.workers, 3), args.timeout, args.pubmed_rate, args.save_every)

    rows = []
    for row in targets:
        match = match_cache.get(row["bdata"]) or {}
        pmid = str(match.get("pmid") or "")
        metadata = metadata_cache.get(pmid) if pmid else None
        title = (metadata or {}).get("title") or ""
        year = str((metadata or {}).get("year") or "")
        title_cov = title_coverage(title, row.get("context") or "") if title else 0.0
        title_sim = title_similarity(title, row.get("context") or "") if title else 0.0
        year_match = bool(year and year in context_years(row.get("context") or ""))
        status = "no_match"
        if pmid and metadata and title and title_cov >= 0.88 and year_match:
            status = "strong"
        elif pmid and metadata:
            status = "possible"
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "pubmed_status": status,
                "pmid": pmid,
                "pubmed_doi": (metadata or {}).get("doi") or "",
                "pubmed_title": title,
                "pubmed_journal": (metadata or {}).get("journal") or "",
                "pubmed_year": year,
                "title_coverage": round(title_cov, 4),
                "title_similarity": round(title_sim, 4),
                "year_match": year_match,
                "bdata": row.get("bdata", ""),
                "context": row.get("context", ""),
            }
        )

    strong = sum(1 for row in rows if row["pubmed_status"] == "strong")
    possible = sum(1 for row in rows if row["pubmed_status"] == "possible")
    found = len(base_found) + strong
    summary = {
        "experiment_label": "Deney 18 - PubMed Citation Matcher",
        "sampled_references": len(sample_rows),
        "base_found_before_experiment18": len(base_found),
        "base_found_before_experiment18_rate_percent": percent(len(base_found), len(sample_rows)),
        "pubmed_targets": len(targets),
        "pubmed_unique_citations": len(bdata_keys),
        "pubmed_pmids_found": len(pmids),
        "pubmed_strong_matches": strong,
        "pubmed_possible_matches": possible,
        "pubmed_strong_with_doi": sum(1 for row in rows if row["pubmed_status"] == "strong" and row.get("pubmed_doi")),
        "pubmed_no_match": sum(1 for row in rows if row["pubmed_status"] == "no_match"),
        "experiment18_auto_resolved_found": found,
        "experiment18_auto_resolved_rate_percent": percent(found, len(sample_rows)),
        "complete": True,
    }
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "pubmed_status",
        "pmid",
        "pubmed_doi",
        "pubmed_title",
        "pubmed_journal",
        "pubmed_year",
        "title_coverage",
        "title_similarity",
        "year_match",
        "bdata",
        "context",
    ]
    write_csv(out_dir / "pubmed_citation_matches.csv", fieldnames, rows)
    write_jsonl(out_dir / "pubmed_citation_matches.jsonl", rows)
    write_csv(out_dir / "pubmed_citation_review_candidates.csv", fieldnames, [row for row in rows if row["pubmed_status"] == "possible"])
    write_json(out_dir / "pubmed_citation_summary.json", summary)
    write_report(
        out_dir / "pubmed_citation_report_tr.md",
        "Deney 18 - PubMed Citation Matcher",
        [
            f"- Deney 16 sonrasi baz: {summary['base_found_before_experiment18']} ({summary['base_found_before_experiment18_rate_percent']}%)",
            f"- PubMed hedefi: {summary['pubmed_targets']}",
            f"- PMID bulunan: {summary['pubmed_pmids_found']}",
            f"- Strong: {summary['pubmed_strong_matches']}",
            f"- Possible: {summary['pubmed_possible_matches']}",
            f"- Yeni toplam: {summary['experiment18_auto_resolved_found']} ({summary['experiment18_auto_resolved_rate_percent']}%)",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return found_after_experiment18(base_found, argparse.Namespace(experiment18_csv=out_dir / "pubmed_citation_matches.csv"))


def write_remaining_after_experiment18(args: argparse.Namespace, sample_rows: List[Dict[str, str]], found: set[str]) -> Dict[str, Any]:
    out_dir = args.out_dir / "remaining_after_experiment18"
    out_dir.mkdir(parents=True, exist_ok=True)
    remaining_rows = remaining_sample_rows(sample_rows, found)
    classified = classify_remaining(remaining_rows)
    total = len(sample_rows)
    remaining = len(classified)
    exclusive = []
    for category in [
        "hidden_doi",
        "dergipark_file",
        "thesis",
        "report_policy_legal",
        "url_web",
        "conference",
        "book_or_chapter",
        "journal_like_left",
        "other",
    ]:
        count = sum(1 for row in classified if row["exclusive_category"] == category)
        exclusive.append(
            {
                "category": category,
                "label": {
                    "hidden_doi": "Gizli DOI",
                    "dergipark_file": "DergiPark article-file",
                    "thesis": "Tez",
                    "report_policy_legal": "Rapor / mevzuat / hukuk",
                    "url_web": "Web / haber / video",
                    "conference": "Konferans / bildiri",
                    "book_or_chapter": "Kitap / kitap bolumu",
                    "journal_like_left": "Journal-like kalan",
                    "other": "Diger / zayif parse",
                }[category],
                "count": count,
                "remaining_rate_percent": percent(count, remaining),
                "total_rate_percent": percent(count, total),
            }
        )
    doi_unlikely = sum(row["count"] for row in exclusive if row["category"] in {"book_or_chapter", "url_web", "thesis", "report_policy_legal", "conference"})
    summary = {
        "experiment_label": "Deney 18 sonrasi kalan referans siniflandirmasi",
        "sampled_references": total,
        "found_after_experiment18": len(found),
        "found_after_experiment18_rate_percent": percent(len(found), total),
        "remaining_after_experiment18": remaining,
        "remaining_after_experiment18_rate_percent": percent(remaining, total),
        "doi_unlikely_exclusive_count": doi_unlikely,
        "doi_unlikely_exclusive_remaining_rate_percent": percent(doi_unlikely, remaining),
        "exclusive_categories": exclusive,
    }
    write_json(out_dir / "remaining_after_experiment18_summary.json", summary)
    write_jsonl(out_dir / "remaining_after_experiment18_references.jsonl", classified)
    write_csv(
        out_dir / "remaining_after_experiment18_references.csv",
        [
            "sample_index",
            "publication_id",
            "reference_id",
            "reference_order",
            "exclusive_category",
            "exclusive_category_label",
            *[f"flag_{key}" for key in PATTERNS],
            "context",
        ],
        classified,
    )
    write_csv(out_dir / "remaining_after_experiment18_exclusive_categories.csv", ["category", "label", "count", "remaining_rate_percent", "total_rate_percent"], exclusive)
    write_report(
        out_dir / "remaining_after_experiment18_report_tr.md",
        "Deney 18 Sonrasi Kalan Referans Istatistigi",
        [
            f"- Deney 18 sonrasi bulunan: {summary['found_after_experiment18']} ({summary['found_after_experiment18_rate_percent']}%)",
            f"- Kalan: {summary['remaining_after_experiment18']} ({summary['remaining_after_experiment18_rate_percent']}%)",
            f"- DOI beklenmesi zayif: {summary['doi_unlikely_exclusive_count']} ({summary['doi_unlikely_exclusive_remaining_rate_percent']}% kalan)",
        ],
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run experiments 14-18 over TR Dizin reference matching sample.")
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
    parser.add_argument("--experiment13-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment13_trdizin_title_search/trdizin_title_search_matches.csv"), type=Path)
    parser.add_argument("--experiment14-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment14_hidden_doi/hidden_doi_matches.csv"), type=Path)
    parser.add_argument("--experiment15-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment15_dergipark_article_file/dergipark_article_file_matches.csv"), type=Path)
    parser.add_argument("--experiment16-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment16_isbn_book/isbn_book_matches.csv"), type=Path)
    parser.add_argument("--experiment18-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment18_pubmed_citation_matcher/pubmed_citation_matches.csv"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k"), type=Path)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--save-every", default=20, type=int)
    parser.add_argument("--crossref-rate", default=5.0, type=float)
    parser.add_argument("--opencitations-rate", default=2.0, type=float)
    parser.add_argument("--pubmed-rate", default=2.0, type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_rows = read_csv(args.sample_csv)
    found13 = current_base_found(args, sample_rows)
    found14 = run_experiment14(args, sample_rows, found13)
    found15 = run_experiment15(args, sample_rows, found14)
    found16 = run_experiment16(args, sample_rows, found15)
    run_experiment17(args, sample_rows, found16)
    found18 = run_experiment18(args, sample_rows, found16)
    remaining_summary = write_remaining_after_experiment18(args, sample_rows, found18)
    print(json.dumps({"final_found_after_experiment18": len(found18), "remaining_summary": remaining_summary}, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
