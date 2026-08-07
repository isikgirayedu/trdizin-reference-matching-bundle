#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from trdizin_experiment13_trdizin_title_search import base_found_after_experiment12
from trdizin_experiment12_trdizin_target_publication import percent, read_csv, write_csv, write_json, write_jsonl
from trdizin_remaining_after_experiment10_stats import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    PATTERNS,
    classify_remaining,
)


def experiment13_found(path: Path) -> set[str]:
    return {
        str(row.get("sample_index"))
        for row in read_csv(path)
        if row.get("trdizin_title_status") == "strong"
    }


def category_rows(classified: List[Dict[str, Any]], total: int) -> List[Dict[str, Any]]:
    remaining = len(classified)
    rows: List[Dict[str, Any]] = []
    descriptions = dict(CATEGORY_DESCRIPTIONS)
    descriptions[
        "journal_like_left"
    ] = "Cilt/sayi/sayfa formati var ama Crossref/STQ/OpenAlex/Europe PMC/DergiPark/TR Dizin ile guvenli eslesmedi."
    for category in CATEGORY_ORDER:
        count = sum(1 for row in classified if row["exclusive_category"] == category)
        rows.append(
            {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "count": count,
                "remaining_rate_percent": percent(count, remaining),
                "total_rate_percent": percent(count, total),
                "description": descriptions[category],
            }
        )
    return rows


def overlap_rows(classified: List[Dict[str, Any]], total: int) -> List[Dict[str, Any]]:
    remaining = len(classified)
    rows: List[Dict[str, Any]] = []
    for category in [key for key in CATEGORY_ORDER if key != "other"]:
        count = sum(1 for row in classified if row.get(f"flag_{category}"))
        rows.append(
            {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "count": count,
                "remaining_rate_percent": percent(count, remaining),
                "total_rate_percent": percent(count, total),
                "description": CATEGORY_DESCRIPTIONS[category],
            }
        )
    return rows


def build_summary(total: int, found_count: int, classified: List[Dict[str, Any]]) -> Dict[str, Any]:
    remaining = len(classified)
    exclusive = category_rows(classified, total)
    overlap = overlap_rows(classified, total)
    unlikely_categories = {"book_or_chapter", "url_web", "thesis", "report_policy_legal", "conference"}
    doi_unlikely = sum(row["count"] for row in exclusive if row["category"] in unlikely_categories)
    return {
        "experiment_label": "Deney 13 sonrasi kalan referans siniflandirmasi",
        "sampled_references": total,
        "found_after_experiment13": found_count,
        "found_after_experiment13_rate_percent": percent(found_count, total),
        "remaining_after_experiment13": remaining,
        "remaining_after_experiment13_rate_percent": percent(remaining, total),
        "doi_unlikely_exclusive_count": doi_unlikely,
        "doi_unlikely_exclusive_remaining_rate_percent": percent(doi_unlikely, remaining),
        "journal_like_left_exclusive_count": next(row["count"] for row in exclusive if row["category"] == "journal_like_left"),
        "other_or_weak_parse_exclusive_count": next(row["count"] for row in exclusive if row["category"] == "other"),
        "exclusive_categories": exclusive,
        "overlap_flags": overlap,
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Deney 13 Sonrasi Kalan Referans Istatistigi",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 13 sonrasi bulunan: {summary['found_after_experiment13']} ({summary['found_after_experiment13_rate_percent']}%)",
        f"- Deney 13 sonrasi kalan: {summary['remaining_after_experiment13']} ({summary['remaining_after_experiment13_rate_percent']}%)",
        f"- DOI beklenmesi zayif kategori toplamı: {summary['doi_unlikely_exclusive_count']} ({summary['doi_unlikely_exclusive_remaining_rate_percent']}% of remaining)",
        "",
        "## Exclusive Kategori Dagilimi",
        "",
    ]
    for row in summary["exclusive_categories"]:
        lines.append(
            f"- {row['label']}: {row['count']} ({row['remaining_rate_percent']}% kalan, {row['total_rate_percent']}% toplam)"
        )
    lines.extend(["", "## Overlap Sinyalleri", ""])
    for row in summary["overlap_flags"]:
        lines.append(
            f"- {row['label']}: {row['count']} ({row['remaining_rate_percent']}% kalan, {row['total_rate_percent']}% toplam)"
        )
    lines.extend(
        [
            "",
            "Not: Exclusive kategoriler oncelik sirasi ile atanir; overlap sinyalleri ayni referansin birden cok isaret tasimasina izin verir.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify references still unmatched after experiment 13.")
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
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/remaining_after_experiment13"), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sample_rows = read_csv(args.sample_csv)
    found_sets = base_found_after_experiment12(args, sample_rows)
    found = found_sets["base_after_experiment12"] | experiment13_found(args.experiment13_csv)
    remaining_rows = [row for row in sample_rows if row["sample_index"] not in found]
    classified = classify_remaining(remaining_rows)
    summary = build_summary(len(sample_rows), len(found), classified)

    write_json(args.out_dir / "remaining_after_experiment13_summary.json", summary)
    write_jsonl(args.out_dir / "remaining_after_experiment13_references.jsonl", classified)
    write_csv(
        args.out_dir / "remaining_after_experiment13_references.csv",
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
    write_csv(
        args.out_dir / "remaining_after_experiment13_exclusive_categories.csv",
        ["category", "label", "count", "remaining_rate_percent", "total_rate_percent", "description"],
        summary["exclusive_categories"],
    )
    write_csv(
        args.out_dir / "remaining_after_experiment13_overlap_flags.csv",
        ["category", "label", "count", "remaining_rate_percent", "total_rate_percent", "description"],
        summary["overlap_flags"],
    )
    write_report(args.out_dir / "remaining_after_experiment13_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
