#!/usr/bin/env python3
"""
Deney 20: Fuzzy Matching & Esnek Arama Resolver
==============================================
Bu script, Deney 19 sonrasında kalan 3.590 referans üzerinde esnek metin eşleştirme (Fuzzy String Matching),
n-gram temizliği ve gelişmiş Crossref / OpenAlex sorguları kullanarak yeni DOI ve kaynak eşleşmeleri arar.

Kullanım:
    python root_scripts/trdizin_experiment20_fuzzy_matching.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from difflib import SequenceMatcher

# Path tanımları
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment19" / "remaining_after_experiment19_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment20_fuzzy"


def normalize_text(text: str) -> str:
    """Metni küçük harfe çevirir, Türkçe karakterleri ve noktalama işaretlerini temizler."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def calculate_similarity(s1: str, s2: str) -> float:
    """İki metin arasındaki SequenceMatcher benzerlik skorunu (0.0 - 1.0) hesaplar."""
    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def load_remaining_references(input_path: Path) -> List[Dict[str, Any]]:
    """Deney 19 sonrası kalan referansları yükler."""
    references = []
    if not input_path.exists():
        print(f"[HATA] Girdi dosyası bulunamadı: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                references.append(json.loads(line))
    return references


def process_fuzzy_matching(references: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Kalan referanslar üzerinde esnek eşleştirme mantığını çalıştırır.
    Geliştirici buraya kendi fuzzy / LLM / API sorgu mantığını ekleyebilir.
    """
    matches = []
    category_counts: Dict[str, int] = {}

    for ref in references:
        cat = ref.get("exclusive_category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

        context = ref.get("context", "")
        # Örnek fuzzy kontrol mantığı taslağı:
        # TODO: İstediğiniz ek API (OpenAlex, Crossref, Google Books) sorgularını buraya ekleyebilirsiniz.

    stats = {
        "total_remaining_input": len(references),
        "total_new_matches": len(matches),
        "category_breakdown": category_counts
    }
    return matches, stats


def main():
    parser = argparse.ArgumentParser(description="Deney 20: Fuzzy Matching Resolver")
    parser.add_argument("--input", type=Path, default=INPUT_JSONL, help="Kalan referanslar JSONL dosyası")
    parser.add_argument("--outdir", type=Path, default=OUTPUT_DIR, help="Çıktı klasörü")
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"=== Deney 20: Fuzzy Matching Resolver Başlatıldı ===")
    print(f"Girdi Dosyası: {args.input}")
    print(f"Çıktı Klasörü: {args.outdir}")

    references = load_remaining_references(args.input)
    print(f"Yüklenen kalan referans sayısı: {len(references)}")

    matches, stats = process_fuzzy_matching(references)

    summary_file = args.outdir / "experiment20_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\nİşlem Tamamlandı!")
    print(f"Özet kaydedildi: {summary_file}")


if __name__ == "__main__":
    main()
