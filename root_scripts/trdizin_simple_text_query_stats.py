#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


STQ_URL = "https://apps.crossref.org/SimpleTextQuery"
DOI_LINK_RE = re.compile(r"https?://doi\.org/(10\.\S+)", re.IGNORECASE)
LEADING_REFNO_RE = re.compile(r"^\s*(?:\[[0-9]+\]|[0-9]+[.)])\s*")


def normalize_doi(value: str) -> str:
    doi = unquote(value).strip()
    doi = re.sub(r"^(?:https?://doi\.org/|doi\s*[:.]?\s*)", "", doi, flags=re.IGNORECASE)
    doi = doi.strip(" \t\r\n\"'<>[]{}")
    doi = re.split(r"[#?]", doi, maxsplit=1)[0]
    return doi.rstrip(".,;:").lower()


def clean_reference(value: str) -> str:
    value = " ".join((value or "").split())
    value = LEADING_REFNO_RE.sub("", value)
    return value.strip()


def read_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def chunked(rows: List[Dict[str, str]], size: int) -> Iterable[List[Dict[str, str]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def extract_key(html: str) -> str:
    match = re.search(r'name="key"\s*\n?\s*value=\s*"([^"]+)"', html)
    return match.group(1) if match else ""


def batch_payload(rows: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. {clean_reference(row.get('context') or '')}")
    return "\n".join(lines)


def cache_key(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_stq_result(html: str, expected_count: int) -> List[Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    text_lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
    results: List[Optional[str]] = [None] * expected_count
    current_index: Optional[int] = None

    for line in text_lines:
        ref_match = re.match(r"^([0-9]{1,4})\.\s+", line)
        if ref_match:
            index = int(ref_match.group(1))
            current_index = index - 1 if 1 <= index <= expected_count else None
            continue

        doi_match = DOI_LINK_RE.search(line)
        if doi_match and current_index is not None and results[current_index] is None:
            results[current_index] = normalize_doi(doi_match.group(1))

    # The text parser above is enough for normal output. Fall back to href order if
    # Crossref changes whitespace but still returns one DOI link per matched ref.
    if all(result is None for result in results):
        dois = []
        for anchor in soup.find_all("a"):
            href = anchor.get("href") or ""
            parsed = urlparse(href)
            if parsed.netloc.lower() == "doi.org" and parsed.path.startswith("/10."):
                dois.append(normalize_doi(parsed.path.lstrip("/")))
        for index, doi in enumerate(dois[:expected_count]):
            results[index] = doi

    return results


def submit_batch(session: requests.Session, rows: List[Dict[str, str]], timeout: float) -> List[Optional[str]]:
    landing = session.get(STQ_URL, timeout=timeout)
    landing.raise_for_status()
    key = extract_key(landing.text)
    payload = batch_payload(rows)
    response = session.post(
        STQ_URL,
        data={
            "command": "Submit",
            "key": key,
            "freetext": payload,
            "submitButton": "Submit",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_stq_result(response.text, len(rows))


def resolve_batch(
    session: requests.Session,
    rows: List[Dict[str, str]],
    timeout: float,
    cache: Dict[str, Any],
    cache_path: Path,
    min_batch_size: int,
    retries: int,
) -> List[Optional[str]]:
    payload = batch_payload(rows)
    key = cache_key(payload)
    if key in cache:
        return cache[key]

    last_error: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            dois = submit_batch(session, rows, timeout)
            cache[key] = dois
            save_cache(cache_path, cache)
            return dois
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))

    if len(rows) <= min_batch_size:
        raise RuntimeError(f"SimpleTextQuery batch failed at size {len(rows)}: {last_error}") from last_error

    midpoint = len(rows) // 2
    left = resolve_batch(session, rows[:midpoint], timeout, cache, cache_path, min_batch_size, retries)
    right = resolve_batch(session, rows[midpoint:], timeout, cache, cache_path, min_batch_size, retries)
    dois = left + right
    cache[key] = dois
    save_cache(cache_path, cache)
    return dois


def load_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def save_cache(path: Path, cache: Dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "source_crossref_status",
        "source_doi",
        "stq_doi",
        "stq_found",
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


def percent(numerator: int, denominator: int) -> Optional[float]:
    return round((numerator / denominator) * 100.0, 2) if denominator else None


def build_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    found = sum(1 for row in rows if row.get("stq_found"))
    with_source_doi = sum(1 for row in rows if row.get("source_doi"))
    no_source_doi = total - with_source_doi
    found_with_source_doi = sum(1 for row in rows if row.get("source_doi") and row.get("stq_found"))
    found_no_source_doi = sum(1 for row in rows if not row.get("source_doi") and row.get("stq_found"))
    return {
        "sampled_references": total,
        "simple_text_query_found": found,
        "simple_text_query_found_rate_percent": percent(found, total),
        "references_with_source_doi": with_source_doi,
        "references_without_source_doi": no_source_doi,
        "stq_found_with_source_doi": found_with_source_doi,
        "stq_found_without_source_doi": found_no_source_doi,
        "stq_found_rate_without_source_doi_percent": percent(found_no_source_doi, no_source_doi),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Crossref SimpleTextQuery on sampled TR Dizin references.")
    parser.add_argument("--input-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query"), type=Path)
    parser.add_argument("--batch-size", default=1000, type=int)
    parser.add_argument("--offset", default=0, type=int)
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument("--timeout", default=180.0, type=float)
    parser.add_argument("--sleep", default=2.0, type=float)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--min-batch-size", default=125, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    source_rows = read_rows(args.input_csv)
    if args.offset:
        source_rows = source_rows[args.offset :]
    if args.limit is not None:
        source_rows = source_rows[: args.limit]
    cache_path = args.out_dir / "simple_text_query_cache.json"
    cache = load_cache(cache_path)
    session = requests.Session()
    session.headers.update({"User-Agent": "trdizin-simple-text-query/0.1 (mailto:isik.onal@sabanciuniv.edu)"})

    output_rows: List[Dict[str, Any]] = []
    for batch_number, rows in enumerate(chunked(source_rows, args.batch_size), start=1):
        dois = resolve_batch(
            session=session,
            rows=rows,
            timeout=args.timeout,
            cache=cache,
            cache_path=cache_path,
            min_batch_size=args.min_batch_size,
            retries=args.retries,
        )
        if args.sleep:
            time.sleep(args.sleep)
        if len(dois) != len(rows):
            raise RuntimeError(f"batch {batch_number}: expected {len(rows)} results, got {len(dois)}")
        print(f"batch {batch_number}: {sum(1 for doi in dois if doi)}/{len(rows)} found", flush=True)
        for row, stq_doi in zip(rows, dois):
            output_rows.append(
                {
                    "sample_index": row.get("sample_index"),
                    "publication_id": row.get("publication_id"),
                    "reference_id": row.get("reference_id"),
                    "reference_order": row.get("reference_order"),
                    "source_crossref_status": row.get("crossref_status"),
                    "source_doi": row.get("doi"),
                    "stq_doi": stq_doi,
                    "stq_found": bool(stq_doi),
                    "context": row.get("context"),
                }
            )

    summary = build_summary(output_rows)
    write_csv(args.out_dir / "simple_text_query_matches.csv", output_rows)
    write_json(args.out_dir / "simple_text_query_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
