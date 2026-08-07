#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from trdizin_crossref_cleanup_fallback import read_csv, read_jsonl
from trdizin_dergipark_article_file_probe import build_found_after_experiment9
from trdizin_openalex_fallback import percent


CATEGORY_ORDER = [
    "hidden_doi",
    "dergipark_file",
    "thesis",
    "report_policy_legal",
    "url_web",
    "conference",
    "book_or_chapter",
    "journal_like_left",
    "other",
]

CATEGORY_LABELS = {
    "hidden_doi": "Gizli DOI",
    "dergipark_file": "DergiPark article-file",
    "thesis": "Tez",
    "report_policy_legal": "Rapor / mevzuat / hukuk",
    "url_web": "Web / haber / video",
    "conference": "Konferans / bildiri",
    "book_or_chapter": "Kitap / kitap bolumu",
    "journal_like_left": "Journal-like kalan",
    "other": "Diger / zayif parse",
}

CATEGORY_DESCRIPTIONS = {
    "hidden_doi": "Referans metninde DOI benzeri ifade var ama onceki DOI pipeline'ina temiz yakalanmamis.",
    "dergipark_file": "DergiPark download/article-file URL'si var; OAI article id kesin degil.",
    "thesis": "Tez veya dissertation referansi; Crossref DOI beklemek genelde dogru denominator degil.",
    "report_policy_legal": "Rapor, mevzuat, resmi belge, hukuk kaynagi veya kurum dokumani sinyali tasiyor.",
    "url_web": "Web sayfasi, haber, video, sosyal medya veya erisim URL'si agirlikli referans.",
    "conference": "Konferans, kongre, sempozyum veya bildiri sinyali tasiyor.",
    "book_or_chapter": "Kitap, yayinevi veya kitap bolumu sinyali tasiyor.",
    "journal_like_left": "Cilt/sayi/sayfa formati var ama Crossref/STQ/OpenAlex/Europe PMC/DergiPark ile guvenli eslesmedi.",
    "other": "Belirgin kategoriye dusmeyen veya parse kalitesi zayif kalan referans.",
}

PATTERNS = {
    "journal_like_left": re.compile(
        r"\b\d+\s*\([^)]{0,25}\)\s*[:,]\s*\d+\s*[-–]\s*\d+"
        r"|\b\d+\s*[:,]\s*\d+\s*[-–]\s*\d+",
        re.IGNORECASE,
    ),
    "book_or_chapter": re.compile(
        r"\b(Yayınları|Yay[ıi]n|Yay[ıi]nc[ıi]l[ıi]k|Yay[ıi]nevi|Kitap|Kitab[ıi]|Kitapları|"
        r"Kitabevi|Matbaa|Matbaas[ıi]|Bas[ıi]mevi|Bas[ıi]|Bası|Neşriyat|Nesriyat|Verlag|Books|"
        r"Press|Publisher|Publishing|Publications|University Press|Routledge|Springer|Sage|"
        r"Cambridge|Oxford|Wiley|Elsevier|Palgrave|Editore|Daru|Dâru|Pub\.?|In\s+[A-ZÇĞİÖŞÜ])\b",
        re.IGNORECASE,
    ),
    "url_web": re.compile(
        r"https?://|www\.|retrieved|accessed|erişim|erisim|YouTube|Twitter|Facebook|Instagram|gazete|haber",
        re.IGNORECASE,
    ),
    "thesis": re.compile(
        r"\b(thesis|dissertation|tez[ıi]?|yüksek lisans|yuksek lisans|doktora|master.?s thesis|unpublished master)\b",
        re.IGNORECASE,
    ),
    "report_policy_legal": re.compile(
        r"\b(report|rapor|OECD|World Bank|WHO|UNICEF|UNFCCC|TÜİK|TUİK|TUIK|Bakanlığı|Ministry|"
        r"Guideline|kılavuz|Kanun|Hukuk|Yarg[ıi]tay|Resmi Gazete|mevzuat)\b",
        re.IGNORECASE,
    ),
    "conference": re.compile(
        r"\b(conference|proceedings|symposium|kongre|sempozyum|bildiri|congress)\b",
        re.IGNORECASE,
    ),
    "dergipark_file": re.compile(r"dergipark\.org\.tr.*download/article-file", re.IGNORECASE),
    "hidden_doi": re.compile(r"\b10\.\d{4,9}\s*/\s*\S+", re.IGNORECASE),
}


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def build_found_after_experiment10(
    sample_rows: List[Dict[str, str]],
    stq_rows: List[Dict[str, str]],
    doi_fallback_rows: List[Dict[str, str]],
    no_doi_fallback_rows: List[Dict[str, str]],
    openalex_rows: List[Dict[str, Any]],
    dergipark_rows: List[Dict[str, Any]],
    experiment8_rows: List[Dict[str, Any]],
    europepmc_rows: List[Dict[str, Any]],
    article_file_rows: List[Dict[str, Any]],
) -> set[str]:
    found = build_found_after_experiment9(
        sample_rows=sample_rows,
        stq_rows=stq_rows,
        doi_fallback_rows=doi_fallback_rows,
        no_doi_fallback_rows=no_doi_fallback_rows,
        openalex_rows=openalex_rows,
        dergipark_rows=dergipark_rows,
        experiment8_rows=experiment8_rows,
        europepmc_rows=europepmc_rows,
    )
    found |= {
        str(row.get("sample_index"))
        for row in article_file_rows
        if row.get("probe_status") in {"strong", "possible"}
    }
    return found


def flags_for_context(context: str) -> Dict[str, bool]:
    compact_context = (context or "").replace(" ", "")
    flags: Dict[str, bool] = {}
    for category, pattern in PATTERNS.items():
        value = compact_context if category == "dergipark_file" else context
        flags[category] = bool(pattern.search(value or ""))
    return flags


def exclusive_category(flags: Dict[str, bool]) -> str:
    for category in CATEGORY_ORDER:
        if category == "other":
            continue
        if flags.get(category):
            return category
    return "other"


def classify_remaining(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    classified: List[Dict[str, Any]] = []
    for row in rows:
        flags = flags_for_context(row.get("context") or "")
        category = exclusive_category(flags)
        classified.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "exclusive_category": category,
                "exclusive_category_label": CATEGORY_LABELS[category],
                **{f"flag_{key}": value for key, value in flags.items()},
                "context": row.get("context", ""),
            }
        )
    return classified


def category_rows(classified: List[Dict[str, Any]], total: int) -> List[Dict[str, Any]]:
    remaining = len(classified)
    rows: List[Dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        count = sum(1 for row in classified if row["exclusive_category"] == category)
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
        "experiment_label": "Deney 10 sonrasi kalan referans siniflandirmasi",
        "sampled_references": total,
        "found_after_experiment10": found_count,
        "found_after_experiment10_rate_percent": percent(found_count, total),
        "remaining_after_experiment10": remaining,
        "remaining_after_experiment10_rate_percent": percent(remaining, total),
        "doi_unlikely_exclusive_count": doi_unlikely,
        "doi_unlikely_exclusive_remaining_rate_percent": percent(doi_unlikely, remaining),
        "journal_like_left_exclusive_count": next(row["count"] for row in exclusive if row["category"] == "journal_like_left"),
        "other_or_weak_parse_exclusive_count": next(row["count"] for row in exclusive if row["category"] == "other"),
        "exclusive_categories": exclusive,
        "overlap_flags": overlap,
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Deney 10 Sonrasi Kalan Referans Istatistigi",
        "",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 10 sonrasi bulunan: {summary['found_after_experiment10']} ({summary['found_after_experiment10_rate_percent']}%)",
        f"- Deney 10 sonrasi kalan: {summary['remaining_after_experiment10']} ({summary['remaining_after_experiment10_rate_percent']}%)",
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
    parser = argparse.ArgumentParser(description="Classify references still unmatched after experiment 10.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-jsonl", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.jsonl"), type=Path)
    parser.add_argument("--dergipark-jsonl", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.jsonl"), type=Path)
    parser.add_argument("--experiment8-jsonl", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/crossref_cleanup_matches.jsonl"), type=Path)
    parser.add_argument("--europepmc-jsonl", default=Path("trdizin_crossref_doi_stats_10k/europepmc_fallback/europepmc_fallback_matches.jsonl"), type=Path)
    parser.add_argument("--article-file-jsonl", default=Path("trdizin_crossref_doi_stats_10k/dergipark_article_file_probe/dergipark_article_file_probe_matches.jsonl"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/remaining_after_experiment10"), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sample_rows = read_csv(args.sample_csv)
    found = build_found_after_experiment10(
        sample_rows=sample_rows,
        stq_rows=read_csv(args.stq_csv),
        doi_fallback_rows=read_csv(args.doi_fallback_csv),
        no_doi_fallback_rows=read_csv(args.no_doi_fallback_csv),
        openalex_rows=read_jsonl(args.openalex_jsonl),
        dergipark_rows=read_jsonl(args.dergipark_jsonl),
        experiment8_rows=read_jsonl(args.experiment8_jsonl),
        europepmc_rows=read_jsonl(args.europepmc_jsonl),
        article_file_rows=read_jsonl(args.article_file_jsonl),
    )
    remaining_rows = [row for row in sample_rows if row["sample_index"] not in found]
    classified = classify_remaining(remaining_rows)
    summary = build_summary(len(sample_rows), len(found), classified)

    write_json(args.out_dir / "remaining_after_experiment10_summary.json", summary)
    write_jsonl(args.out_dir / "remaining_after_experiment10_references.jsonl", classified)
    write_csv(
        args.out_dir / "remaining_after_experiment10_references.csv",
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
        args.out_dir / "remaining_after_experiment10_exclusive_categories.csv",
        ["category", "label", "count", "remaining_rate_percent", "total_rate_percent", "description"],
        summary["exclusive_categories"],
    )
    write_csv(
        args.out_dir / "remaining_after_experiment10_overlap_flags.csv",
        ["category", "label", "count", "remaining_rate_percent", "total_rate_percent", "description"],
        summary["overlap_flags"],
    )
    write_report(args.out_dir / "remaining_after_experiment10_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
