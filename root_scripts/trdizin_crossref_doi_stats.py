#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, unquote

import requests


DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
DOI_PREFIX_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi\s*[:.]?\s*)(10\.\d{4,9}/[^\s\"<>]+)",
    re.IGNORECASE,
)
DOI_TRAILING_ENDPOINT_RE = re.compile(
    r"/(?:bibtex|endnote|ris|reference-manager|full|abstract|pdf)$",
    re.IGNORECASE,
)


@dataclass
class Reference:
    publication_id: Optional[int]
    reference_id: Optional[int]
    order: Optional[int]
    context: str


def iter_references(path: Path) -> Iterable[Reference]:
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL line: {exc}") from exc

            metadata = record.get("metadata") if isinstance(record, dict) else None
            if not isinstance(metadata, dict):
                continue
            publication_id = as_int(metadata.get("id") or record.get("id"))
            references = metadata.get("references")
            if not isinstance(references, list):
                continue
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                context = reference.get("context")
                if not isinstance(context, str) or not context.strip():
                    continue
                yield Reference(
                    publication_id=publication_id,
                    reference_id=as_int(reference.get("id")),
                    order=as_int(reference.get("order")),
                    context=" ".join(context.split()),
                )


def as_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalize_doi(value: str) -> str:
    doi = html.unescape(unquote(value)).strip()
    doi = doi.replace("\u00a0", " ")
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*[:.]?\s*)", "", doi, flags=re.IGNORECASE)
    doi = doi.strip(" \t\r\n\"'<>[]{}")
    doi = re.split(r"[#?]", doi, maxsplit=1)[0]
    doi = DOI_TRAILING_ENDPOINT_RE.sub("", doi)
    doi = doi.rstrip(".,;:")
    while doi.endswith(")") and doi.count("(") < doi.count(")"):
        doi = doi[:-1]
    while doi.endswith("]") and doi.count("[") < doi.count("]"):
        doi = doi[:-1]
    return doi.lower()


def extract_doi_candidates(context: str) -> List[str]:
    text = html.unescape(context).replace("\u00a0", " ")
    candidates: List[str] = []
    for pattern in (DOI_PREFIX_RE, DOI_RE):
        for match in pattern.finditer(text):
            raw = match.group(1)
            add_candidate(candidates, raw)

            # TR Dizin/OCR occasionally splits article-number suffixes:
            # "10.1016/j.abrep.2018. 100148" or "...2022.10839 3".
            continuation = numeric_continuation(text, match.end(1))
            if continuation:
                add_candidate(candidates, raw + continuation)
        if candidates:
            break
    return candidates


def add_candidate(candidates: List[str], raw: str) -> None:
    doi = normalize_doi(raw)
    if DOI_RE.match(doi) and doi not in candidates:
        candidates.append(doi)


def numeric_continuation(text: str, offset: int) -> Optional[str]:
    match = re.match(r"\s+([0-9][0-9._;()/-]{0,20})", text[offset:])
    if not match:
        return None
    token = match.group(1).rstrip(".,;:")
    return token if token else None


def choose_sample(references: List[Reference], sample_size: int, sample_mode: str, seed: int) -> List[Reference]:
    if sample_size > len(references):
        raise ValueError(f"sample size {sample_size} exceeds available references {len(references)}")
    if sample_mode == "first":
        return references[:sample_size]
    rng = random.Random(seed)
    indexes = sorted(rng.sample(range(len(references)), sample_size))
    return [references[index] for index in indexes]


def query_crossref(
    session: requests.Session,
    doi: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    last_error: Optional[str] = None

    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt)))
        try:
            response = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue

        status_code = response.status_code
        if status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            message = payload.get("message") if isinstance(payload, dict) else {}
            if not isinstance(message, dict):
                message = {}
            return {
                "status": "found",
                "http_status": status_code,
                "crossref_doi": normalize_doi(str(message.get("DOI") or doi)),
                "crossref_title": first_text(message.get("title")),
                "crossref_publisher": message.get("publisher"),
            }
        if status_code == 404:
            return {"status": "not_found", "http_status": status_code}
        if status_code in {429, 500, 502, 503, 504}:
            last_error = f"HTTP {status_code}"
            continue
        return {"status": "error", "http_status": status_code, "error": response.text[:300]}

    return {"status": "error", "http_status": None, "error": last_error or "request failed"}


def check_crossref_candidates(
    session: requests.Session,
    candidates: List[str],
    cache: Dict[str, Dict[str, Any]],
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    if not candidates:
        return {
            "doi": None,
            "doi_candidates": [],
            "crossref_result": {"status": "no_doi", "http_status": None},
            "cache_dirty": False,
        }

    cache_dirty = False
    checked_results: List[tuple[str, Dict[str, Any]]] = []
    for doi in candidates:
        result = cache.get(doi) or {}
        if not result:
            result = query_crossref(
                session=session,
                doi=doi,
                timeout=timeout,
                retries=retries,
                sleep_seconds=sleep_seconds,
            )
            cache[doi] = result
            cache_dirty = True
            if sleep_seconds:
                time.sleep(sleep_seconds)
        checked_results.append((doi, result))
        if result.get("status") == "found":
            return {
                "doi": doi,
                "doi_candidates": candidates,
                "crossref_result": result,
                "cache_dirty": cache_dirty,
            }

    # Prefer a deterministic representative result for stats when no candidate is found.
    doi, result = checked_results[0]
    for candidate_doi, candidate_result in checked_results:
        if candidate_result.get("status") == "error":
            doi, result = candidate_doi, candidate_result
            break
    return {
        "doi": doi,
        "doi_candidates": candidates,
        "crossref_result": result,
        "cache_dirty": cache_dirty,
    }


def first_text(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return " ".join(value.split())
    return None


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


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def percent(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round((numerator / denominator) * 100.0, 2)


def build_summary(
    rows: List[Dict[str, Any]],
    source_path: Path,
    total_available_references: int,
    sample_mode: str,
    seed: int,
) -> Dict[str, Any]:
    total = len(rows)
    with_doi = sum(1 for row in rows if row["doi"])
    without_doi = total - with_doi
    found = sum(1 for row in rows if row["crossref_status"] == "found")
    not_found = sum(1 for row in rows if row["crossref_status"] == "not_found")
    errors = sum(1 for row in rows if row["crossref_status"] == "error")
    unique_dois = sorted({row["doi"] for row in rows if row["doi"]})
    found_unique = {
        row["doi"]
        for row in rows
        if row["doi"] and row["crossref_status"] == "found"
    }

    return {
        "source": str(source_path),
        "source_total_available_references": total_available_references,
        "sample_mode": sample_mode,
        "seed": seed if sample_mode == "random" else None,
        "sampled_references": total,
        "references_with_doi": with_doi,
        "references_without_doi": without_doi,
        "crossref_found_by_doi": found,
        "crossref_not_found_by_doi": not_found,
        "crossref_errors": errors,
        "unique_dois": len(unique_dois),
        "unique_dois_found_in_crossref": len(found_unique),
        "doi_presence_rate_percent": percent(with_doi, total),
        "crossref_found_rate_all_references_percent": percent(found, total),
        "crossref_found_rate_doi_references_percent": percent(found, with_doi),
        "crossref_not_found_rate_doi_references_percent": percent(not_found, with_doi),
        "crossref_error_rate_doi_references_percent": percent(errors, with_doi),
    }


def write_rows_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "doi",
        "crossref_status",
        "http_status",
        "crossref_doi",
        "crossref_title",
        "crossref_publisher",
        "context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def write_rows_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_summary_md(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# TR Dizin Crossref DOI Stats",
        "",
        f"- Source: `{summary['source']}`",
        f"- Available references in source: {summary['source_total_available_references']}",
        f"- Sample mode: {summary['sample_mode']}",
        f"- Seed: {summary['seed']}",
        f"- Sampled references: {summary['sampled_references']}",
        f"- References with DOI: {summary['references_with_doi']} ({summary['doi_presence_rate_percent']}%)",
        f"- References without DOI: {summary['references_without_doi']}",
        f"- Crossref found by DOI: {summary['crossref_found_by_doi']} ({summary['crossref_found_rate_all_references_percent']}% of all, {summary['crossref_found_rate_doi_references_percent']}% of DOI refs)",
        f"- Crossref not found by DOI: {summary['crossref_not_found_by_doi']} ({summary['crossref_not_found_rate_doi_references_percent']}% of DOI refs)",
        f"- Crossref errors: {summary['crossref_errors']} ({summary['crossref_error_rate_doi_references_percent']}% of DOI refs)",
        f"- Unique DOIs: {summary['unique_dois']}",
        f"- Unique DOIs found in Crossref: {summary['unique_dois_found_in_crossref']}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample TR Dizin references and check DOI presence in Crossref."
    )
    parser.add_argument("--source", default="veriler.jsonl", type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats"), type=Path)
    parser.add_argument("--sample-size", default=1000, type=int)
    parser.add_argument("--sample-mode", choices=("random", "first"), default="random")
    parser.add_argument("--seed", default=20260804, type=int)
    parser.add_argument("--timeout", default=20.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--sleep", default=0.1, type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    references = list(iter_references(args.source))
    sample = choose_sample(references, args.sample_size, args.sample_mode, args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cache_path = args.out_dir / "crossref_doi_cache.json"
    cache = load_cache(cache_path)

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "trdizin-crossref-doi-stats/0.1 (local research analysis)",
        }
    )

    rows: List[Dict[str, Any]] = []
    dirty_cache = False

    for sample_index, reference in enumerate(sample, start=1):
        doi_check = check_crossref_candidates(
            session=session,
            candidates=extract_doi_candidates(reference.context),
            cache=cache,
            timeout=args.timeout,
            retries=args.retries,
            sleep_seconds=args.sleep,
        )
        doi = doi_check["doi"]
        doi_candidates = doi_check["doi_candidates"]
        crossref_result = doi_check["crossref_result"]
        dirty_cache = dirty_cache or bool(doi_check["cache_dirty"])
        if dirty_cache and len(cache) % 25 == 0:
            save_cache(cache_path, cache)
            dirty_cache = False

        rows.append(
            {
                "sample_index": sample_index,
                "publication_id": reference.publication_id,
                "reference_id": reference.reference_id,
                "reference_order": reference.order,
                "context": reference.context,
                "doi": doi,
                "doi_candidates": doi_candidates,
                "crossref_status": crossref_result.get("status"),
                "http_status": crossref_result.get("http_status"),
                "crossref_doi": crossref_result.get("crossref_doi"),
                "crossref_title": crossref_result.get("crossref_title"),
                "crossref_publisher": crossref_result.get("crossref_publisher"),
                "crossref_error": crossref_result.get("error"),
            }
        )

    if dirty_cache:
        save_cache(cache_path, cache)

    summary = build_summary(
        rows=rows,
        source_path=args.source,
        total_available_references=len(references),
        sample_mode=args.sample_mode,
        seed=args.seed,
    )

    write_rows_csv(args.out_dir / "sample_references_crossref.csv", rows)
    write_rows_jsonl(args.out_dir / "sample_references_crossref.jsonl", rows)
    write_json(args.out_dir / "summary.json", summary)
    write_summary_md(args.out_dir / "summary.md", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
