#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


SERPAPI_URL = "https://serpapi.com/search.json"
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
LEADING_REFNO_RE = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)])\s*")
ACCESS_TAIL_RE = re.compile(
    r"\b(?:retrieved|accessed|erişim|erisim)\b.*$",
    re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")


@dataclass
class ReferenceRow:
    sample_index: str
    publication_id: str
    reference_id: str
    reference_order: str
    category: str
    reference_text: str
    query: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_query(reference_text: str, max_chars: int) -> str:
    query = reference_text or ""
    query = URL_RE.sub(" ", query)
    query = ACCESS_TAIL_RE.sub(" ", query)
    query = LEADING_REFNO_RE.sub("", query)
    query = query.replace("\u00ad", "")
    query = SPACE_RE.sub(" ", query).strip(" .;,")
    if max_chars > 0 and len(query) > max_chars:
        query = query[:max_chars].rsplit(" ", 1)[0].strip(" .;,")
    return query


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_csv(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return read_jsonl(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    raise ValueError(f"unsupported input extension: {path.suffix}")


def coalesce(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def make_reference_rows(args: argparse.Namespace) -> List[ReferenceRow]:
    rows = load_rows(args.input)
    categories = set(args.category or [])
    sample_indexes = set(args.sample_index or [])
    output: List[ReferenceRow] = []
    for row in rows:
        sample_index = coalesce(row, "sample_index", "sampleIndex")
        category = coalesce(row, "exclusive_category", "category")
        if categories and category not in categories:
            continue
        if sample_indexes and sample_index not in sample_indexes:
            continue

        reference_text = coalesce(row, "context", "reference_text", "text", "grobid_raw_reference")
        if not reference_text:
            continue
        query = clean_query(reference_text, args.max_query_chars)
        if len(query) < args.min_query_chars:
            continue
        output.append(
            ReferenceRow(
                sample_index=sample_index,
                publication_id=coalesce(row, "publication_id", "publicationId"),
                reference_id=coalesce(row, "reference_id", "referenceId"),
                reference_order=coalesce(row, "reference_order", "referenceOrder"),
                category=category,
                reference_text=reference_text,
                query=query,
            )
        )
    return output[: args.limit] if args.limit else output


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scholar_reference_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_index TEXT NOT NULL,
            publication_id TEXT,
            reference_id TEXT,
            reference_order TEXT,
            category TEXT,
            reference_text TEXT NOT NULL,
            query TEXT NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            result_count INTEGER NOT NULL,
            selected_link TEXT,
            selected_title TEXT,
            results_json TEXT NOT NULL,
            error TEXT,
            searched_at TEXT NOT NULL,
            UNIQUE(sample_index, provider)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scholar_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            input_path TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            requested_rows INTEGER NOT NULL,
            processed_rows INTEGER NOT NULL DEFAULT 0,
            unique_results INTEGER NOT NULL DEFAULT 0,
            null_results INTEGER NOT NULL DEFAULT 0,
            error_results INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    return conn


def existing_sample_indexes(conn: sqlite3.Connection, provider: str) -> set[str]:
    cursor = conn.execute("SELECT sample_index FROM scholar_reference_links WHERE provider = ?", (provider,))
    return {str(row[0]) for row in cursor.fetchall()}


def save_result(
    conn: sqlite3.Connection,
    ref: ReferenceRow,
    provider: str,
    status: str,
    result_count: int,
    selected_link: Optional[str],
    selected_title: Optional[str],
    results: List[Dict[str, Any]],
    error: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO scholar_reference_links (
            sample_index,
            publication_id,
            reference_id,
            reference_order,
            category,
            reference_text,
            query,
            provider,
            status,
            result_count,
            selected_link,
            selected_title,
            results_json,
            error,
            searched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sample_index, provider) DO UPDATE SET
            publication_id = excluded.publication_id,
            reference_id = excluded.reference_id,
            reference_order = excluded.reference_order,
            category = excluded.category,
            reference_text = excluded.reference_text,
            query = excluded.query,
            status = excluded.status,
            result_count = excluded.result_count,
            selected_link = excluded.selected_link,
            selected_title = excluded.selected_title,
            results_json = excluded.results_json,
            error = excluded.error,
            searched_at = excluded.searched_at
        """,
        (
            ref.sample_index,
            ref.publication_id,
            ref.reference_id,
            ref.reference_order,
            ref.category,
            ref.reference_text,
            ref.query,
            provider,
            status,
            result_count,
            selected_link,
            selected_title,
            json.dumps(results, ensure_ascii=False, sort_keys=True),
            error,
            utc_now(),
        ),
    )


def compact_serpapi_result(item: Dict[str, Any]) -> Dict[str, Any]:
    resources = item.get("resources") if isinstance(item.get("resources"), list) else []
    return {
        "title": item.get("title") or "",
        "link": item.get("link") or "",
        "result_id": item.get("result_id") or "",
        "publication_info": item.get("publication_info") if isinstance(item.get("publication_info"), dict) else {},
        "snippet": item.get("snippet") or "",
        "resources": resources[:3],
    }


def search_serpapi_scholar(session: requests.Session, api_key: str, query: str, timeout: float) -> List[Dict[str, Any]]:
    response = session.get(
        SERPAPI_URL,
        params={
            "engine": "google_scholar",
            "q": query,
            "api_key": api_key,
            "num": 2,
            "hl": "tr",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    organic = payload.get("organic_results") if isinstance(payload, dict) else []
    if not isinstance(organic, list):
        return []
    return [compact_serpapi_result(item) for item in organic[:2] if isinstance(item, dict)]


def mock_search(query: str) -> List[Dict[str, Any]]:
    if "unique" in query.lower():
        return [{"title": "Mock unique result", "link": "https://example.org/mock", "result_id": "mock-1"}]
    if "empty" in query.lower():
        return []
    return [
        {"title": "Mock result 1", "link": "https://example.org/mock-1", "result_id": "mock-1"},
        {"title": "Mock result 2", "link": "https://example.org/mock-2", "result_id": "mock-2"},
    ]


def classify_results(results: List[Dict[str, Any]]) -> tuple[str, Optional[str], Optional[str]]:
    if len(results) == 1:
        link = results[0].get("link") or None
        title = results[0].get("title") or None
        if link:
            return "unique_result", link, title
        return "unique_no_link", None, title
    if not results:
        return "no_result", None, None
    return "ambiguous", None, None


def run(args: argparse.Namespace) -> Dict[str, Any]:
    refs = make_reference_rows(args)
    conn = connect_db(args.db)
    run_started = utc_now()
    run_cursor = conn.execute(
        """
        INSERT INTO scholar_runs (provider, input_path, started_at, requested_rows)
        VALUES (?, ?, ?, ?)
        """,
        (args.provider, str(args.input), run_started, len(refs)),
    )
    run_id = int(run_cursor.lastrowid)
    conn.commit()

    api_key = args.api_key or os.getenv("SERPAPI_KEY", "")
    if args.provider == "serpapi" and not api_key:
        raise SystemExit("SERPAPI_KEY env var ya da --api-key gerekli.")

    already_done = existing_sample_indexes(conn, args.provider) if not args.overwrite else set()
    session = requests.Session()
    processed = 0
    unique = 0
    nulls = 0
    errors = 0

    for index, ref in enumerate(refs, start=1):
        if ref.sample_index in already_done:
            continue
        try:
            if args.provider == "mock":
                results = mock_search(ref.query)
            else:
                results = search_serpapi_scholar(session, api_key, ref.query, args.timeout)
            status, link, title = classify_results(results)
            save_result(conn, ref, args.provider, status, len(results), link, title, results)
            if status == "unique_result":
                unique += 1
            else:
                nulls += 1
        except Exception as error:
            save_result(conn, ref, args.provider, "error", 0, None, None, [], str(error))
            errors += 1

        processed += 1
        if processed % args.commit_every == 0:
            conn.commit()
            print(f"processed {processed}/{len(refs)}", flush=True)
        if args.sleep > 0:
            time.sleep(args.sleep)

    conn.commit()
    conn.execute(
        """
        UPDATE scholar_runs
        SET finished_at = ?, processed_rows = ?, unique_results = ?, null_results = ?, error_results = ?
        WHERE id = ?
        """,
        (utc_now(), processed, unique, nulls, errors, run_id),
    )
    conn.commit()
    summary = {
        "run_id": run_id,
        "provider": args.provider,
        "input": str(args.input),
        "db": str(args.db),
        "requested_rows": len(refs),
        "processed_rows": processed,
        "skipped_existing": len(refs) - processed if not args.overwrite else 0,
        "unique_results_saved_with_link": unique,
        "null_results": nulls,
        "error_results": errors,
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Google Scholar via a provider and store exactly-one-result links in SQLite."
    )
    parser.add_argument(
        "--input",
        default=Path("trdizin_crossref_doi_stats_10k/remaining_after_experiment19/remaining_after_experiment19_references.jsonl"),
        type=Path,
        help="Input JSONL/CSV with reference rows.",
    )
    parser.add_argument(
        "--db",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite"),
        type=Path,
        help="SQLite output path.",
    )
    parser.add_argument("--provider", choices=("serpapi", "mock"), default="serpapi")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--category", action="append", help="Filter exclusive_category/category; can be repeated.")
    parser.add_argument("--sample-index", action="append", help="Filter specific sample_index; can be repeated.")
    parser.add_argument("--limit", default=0, type=int)
    parser.add_argument("--max-query-chars", default=240, type=int)
    parser.add_argument("--min-query-chars", default=12, type=int)
    parser.add_argument("--timeout", default=25.0, type=float)
    parser.add_argument("--sleep", default=2.0, type=float, help="Delay between provider requests.")
    parser.add_argument("--commit-every", default=20, type=int)
    parser.add_argument("--overwrite", action="store_true", help="Re-query rows already present for this provider.")
    parser.add_argument(
        "--summary-json",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links_summary.json"),
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
