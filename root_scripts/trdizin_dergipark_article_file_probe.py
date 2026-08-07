#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from trdizin_crossref_cleanup_fallback import read_csv, read_jsonl
from trdizin_dergipark_oai_fallback import extract_dergipark_evidence, get_record, make_session, score_candidate
from trdizin_europepmc_fallback import build_found_after_experiment8
from trdizin_openalex_fallback import percent


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
        "article_file_id",
        "probe_status",
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


def build_found_after_experiment9(
    sample_rows: List[Dict[str, str]],
    stq_rows: List[Dict[str, str]],
    doi_fallback_rows: List[Dict[str, str]],
    no_doi_fallback_rows: List[Dict[str, str]],
    openalex_rows: List[Dict[str, Any]],
    dergipark_rows: List[Dict[str, Any]],
    experiment8_rows: List[Dict[str, Any]],
    europepmc_rows: List[Dict[str, Any]],
) -> set[str]:
    found = build_found_after_experiment8(
        sample_rows,
        stq_rows,
        doi_fallback_rows,
        no_doi_fallback_rows,
        openalex_rows,
        dergipark_rows,
        experiment8_rows,
    )
    found |= {
        str(row.get("sample_index"))
        for row in europepmc_rows
        if row.get("europepmc_status") in {"strong", "possible"}
    }
    return found


def build_targets(sample_rows: List[Dict[str, str]], found: set[str]) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for row in sample_rows:
        if row["sample_index"] in found:
            continue
        evidence = extract_dergipark_evidence(row.get("context") or "")
        if evidence.get("article_id") or not evidence.get("article_file_id"):
            continue
        targets.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "article_file_id": evidence["article_file_id"],
                "context": row.get("context", ""),
            }
        )
    return targets


def output_row(row: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    base = {
        "sample_index": row["sample_index"],
        "publication_id": row["publication_id"],
        "reference_id": row["reference_id"],
        "reference_order": row["reference_order"],
        "article_file_id": row["article_file_id"],
        "probe_status": "not_checked",
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
        "context": row["context"],
    }
    if result.get("status") != "ok":
        base["probe_status"] = "request_error"
        return base
    items = result.get("items") if isinstance(result.get("items"), list) else []
    if not items:
        base["probe_status"] = "no_match"
        return base
    score = max((score_candidate(item, row["context"]) for item in items), key=lambda item: item.confidence)
    candidate = score.candidate
    base.update(
        {
            "probe_status": score.match_status,
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
    return base


def build_summary(base_found: int, sampled: int, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    strong = sum(1 for row in rows if row["probe_status"] == "strong")
    possible = sum(1 for row in rows if row["probe_status"] == "possible")
    no_match = sum(1 for row in rows if row["probe_status"] == "no_match")
    errors = sum(1 for row in rows if row["probe_status"] == "request_error")
    strict = base_found + strong
    broad = base_found + strong + possible
    return {
        "experiment_label": "Deney 10 - DergiPark article-file id probe",
        "sampled_references": sampled,
        "base_found_before_article_file_probe": base_found,
        "base_found_before_article_file_probe_rate_percent": percent(base_found, sampled),
        "article_file_probe_targets": len(rows),
        "article_file_probe_strong_matches": strong,
        "article_file_probe_possible_matches": possible,
        "article_file_probe_no_match": no_match,
        "article_file_probe_request_errors": errors,
        "experiment10_strict_found": strict,
        "experiment10_strict_found_rate_percent": percent(strict, sampled),
        "experiment10_broad_found": broad,
        "experiment10_broad_found_rate_percent": percent(broad, sampled),
        "complete": errors == 0,
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# DergiPark Article-file Probe Deney 10",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 10 oncesi baz bulunan: {summary['base_found_before_article_file_probe']} ({summary['base_found_before_article_file_probe_rate_percent']}%)",
        f"- Article-file hedefi: {summary['article_file_probe_targets']}",
        f"- Strong eslesme: {summary['article_file_probe_strong_matches']}",
        f"- Possible eslesme: {summary['article_file_probe_possible_matches']}",
        f"- No match: {summary['article_file_probe_no_match']}",
        f"- Request error: {summary['article_file_probe_request_errors']}",
        "",
        "## Deney 10 Sonuc",
        "",
        f"- Strict toplam: {summary['experiment10_strict_found']} ({summary['experiment10_strict_found_rate_percent']}%)",
        f"- Broad toplam: {summary['experiment10_broad_found']} ({summary['experiment10_broad_found_rate_percent']}%)",
        "",
        "Not: Bu deney article-file id'yi OAI article id olarak dener; metadata donse bile title/year/author skoru gecmeden eslesme sayilmaz.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experiment 10: probe DergiPark article-file ids as possible OAI article ids.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-jsonl", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.jsonl"), type=Path)
    parser.add_argument("--dergipark-jsonl", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.jsonl"), type=Path)
    parser.add_argument("--experiment8-jsonl", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/crossref_cleanup_matches.jsonl"), type=Path)
    parser.add_argument("--europepmc-jsonl", default=Path("trdizin_crossref_doi_stats_10k/europepmc_fallback/europepmc_fallback_matches.jsonl"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/dergipark_article_file_probe"), type=Path)
    parser.add_argument("--timeout", default=35.0, type=float)
    parser.add_argument("--retries", default=0, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--fetch-mode", default="jina", choices=["direct", "auto", "jina"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sample_rows = read_csv(args.sample_csv)
    found = build_found_after_experiment9(
        sample_rows=sample_rows,
        stq_rows=read_csv(args.stq_csv),
        doi_fallback_rows=read_csv(args.doi_fallback_csv),
        no_doi_fallback_rows=read_csv(args.no_doi_fallback_csv),
        openalex_rows=read_jsonl(args.openalex_jsonl),
        dergipark_rows=read_jsonl(args.dergipark_jsonl),
        experiment8_rows=read_jsonl(args.experiment8_jsonl),
        europepmc_rows=read_jsonl(args.europepmc_jsonl),
    )
    targets = build_targets(sample_rows, found)
    cache_path = args.out_dir / "dergipark_article_file_probe_cache.json"
    cache = load_cache(cache_path)
    session = make_session()

    for index, row in enumerate(targets, start=1):
        key = f"file-as-article:{row['article_file_id']}"
        if key not in cache:
            cache[key] = get_record(
                session=session,
                slug="",
                article_id=row["article_file_id"],
                timeout=args.timeout,
                retries=args.retries,
                sleep_seconds=args.sleep,
                fetch_mode=args.fetch_mode,
            )
            save_cache(cache_path, cache)
            if args.sleep:
                time.sleep(args.sleep)
        print(f"checked {index}/{len(targets)} article-file probes", flush=True)

    rows = [output_row(row, cache.get(f"file-as-article:{row['article_file_id']}", {})) for row in targets]
    summary = build_summary(len(found), len(sample_rows), rows)
    write_csv(args.out_dir / "dergipark_article_file_probe_matches.csv", rows)
    write_jsonl(args.out_dir / "dergipark_article_file_probe_matches.jsonl", rows)
    write_json(args.out_dir / "dergipark_article_file_probe_summary.json", summary)
    write_report(args.out_dir / "dergipark_article_file_probe_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
