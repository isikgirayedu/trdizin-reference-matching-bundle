#!/usr/bin/env python3
"""
Deney 20: Fuzzy Matching & Esnek Arama Resolver
==============================================
Bu script, Deney 19 sonrasında kalan 3.590 referans üzerinde (özellikle journal_like_left kategorisindeki 551 dergi makalesi)
esnek metin temizleme (fuzzy title cleaning), yıl çıkarma ve Crossref / OpenAlex API sorguları ile yeni DOI eşleşmeleri arar.

Kullanım:
    python root_scripts/trdizin_experiment20_fuzzy_matching.py --limit 50
    python root_scripts/trdizin_experiment20_fuzzy_matching.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from difflib import SequenceMatcher
import requests

# Path tanımları
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment19" / "remaining_after_experiment19_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment20_fuzzy"

# Regex tanımları
YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-2][0-9])\b")
WORD_RE = re.compile(r"[a-z0-9]+")
CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"
HEADERS = {"User-Agent": f"TRDizinReferenceMatching/1.0 (mailto:{CONTACT_EMAIL})"}


def normalize_text(text: str) -> str:
    """Metni küçük harfe çevirir, Türkçe ve özel karakterleri temizler."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    words = WORD_RE.findall(text)
    return " ".join(words)


def extract_year(text: str) -> Optional[int]:
    """Referans metninden yayın yılını çıkarır."""
    matches = YEAR_RE.findall(text)
    if matches:
        return int(matches[0])
    return None


def calculate_similarity(s1: str, s2: str) -> float:
    """İki metin arasındaki SequenceMatcher benzerlik skorunu (0.0 - 1.0) hesaplar."""
    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def query_crossref_fuzzy(clean_title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Crossref API'ye esnek bibliyografik sorgu atar ve fuzzy similarity ile doğrulama yapar."""
    if not clean_title or len(clean_title) < 10:
        return None

    url = "https://api.crossref.org/works"
    params: Dict[str, Any] = {
        "query.bibliographic": clean_title,
        "rows": 3
    }
    if year:
        params["filter"] = f"from-pub-date:{year-1},until-pub-date:{year+1}"

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            for item in items:
                title_list = item.get("title", [])
                if not title_list:
                    continue
                cand_title = title_list[0]
                sim = calculate_similarity(clean_title, cand_title)
                if sim >= 0.82:  # Fuzzy threshold %82
                    return {
                        "doi": item.get("DOI"),
                        "title": cand_title,
                        "similarity": round(sim, 3),
                        "publisher": item.get("publisher"),
                        "source": "crossref_fuzzy"
                    }
    except Exception:
        pass
    return None


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


def process_fuzzy_matching(references: List[Dict[str, Any]], limit: Optional[int] = None, category_filter: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Kalan referanslar üzerinde esnek eşleştirme (Fuzzy Matching) algoritmasını çalıştırır.
    """
    matches = []
    category_counts: Dict[str, int] = {}

    if category_filter and category_filter != "all":
        target_refs = [r for r in references if r.get("exclusive_category") == category_filter]
    else:
        target_refs = references

    if limit:
        target_refs = target_refs[:limit]

    print(f"-> Toplam {len(target_refs)} referans üzerinde Fuzzy Matching çalıştırılıyor...")

    for idx, ref in enumerate(target_refs, 1):
        cat = ref.get("exclusive_category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

        context = ref.get("context", "")
        clean_t = normalize_text(context)
        ref_year = extract_year(context)

        # Öncelik: Journal-like referanslar ve generic metinler
        match_res = query_crossref_fuzzy(clean_t, ref_year)
        if match_res:
            match_entry = {
                "sample_index": ref.get("sample_index"),
                "publication_id": ref.get("publication_id"),
                "reference_id": ref.get("reference_id"),
                "context": context,
                "exclusive_category": cat,
                "matched_doi": match_res["doi"],
                "matched_title": match_res["title"],
                "similarity": match_res["similarity"],
                "source": match_res["source"]
            }
            matches.append(match_entry)

        if idx % 5 == 0 or idx == len(target_refs):
            print(f"   İşlenen: {idx}/{len(target_refs)} | Yeni Bulunan Eşleşme: {len(matches)}", end="\r", flush=True)

        time.sleep(0.1)  # API rate-limit önlemi

    print()
    stats = {
        "total_processed": len(target_refs),
        "new_strong_matches": len(matches),
        "match_rate_percentage": round((len(matches) / len(target_refs)) * 100, 2) if target_refs else 0.0,
        "category_breakdown": category_counts
    }
    return matches, stats


def main():
    parser = argparse.ArgumentParser(description="Deney 20: Fuzzy Matching Resolver")
    parser.add_argument("--input", type=Path, default=INPUT_JSONL, help="Kalan referanslar JSONL dosyası")
    parser.add_argument("--outdir", type=Path, default=OUTPUT_DIR, help="Çıktı klasörü")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum referans sayısı (Test için)")
    parser.add_argument("--category", type=str, default="all", help="Filtrelenecek kategori (ör. journal_like_left, book_or_chapter, thesis, all)")
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"=== Deney 20: Fuzzy Matching Resolver Başlatıldı ===")
    print(f"Girdi Dosyası: {args.input}")
    print(f"Çıktı Klasörü: {args.outdir}")
    print(f"Hedef Kategori: {args.category}")
    if args.limit:
        print(f"Limit Modu: İlk {args.limit} referans işlenecek.")

    references = load_remaining_references(args.input)
    matches, stats = process_fuzzy_matching(references, limit=args.limit, category_filter=args.category)

    # Sonuçları kaydet
    summary_file = args.outdir / "experiment20_summary.json"
    matches_file = args.outdir / "experiment20_matches.jsonl"

    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    with open(matches_file, "w", encoding="utf-8") as f:
        for m in matches:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"\nİşlem Tamamlandı!")
    print(f"Yeni Eşleşme Sayısı: {stats['new_strong_matches']}")
    print(f"Özet kaydedildi: {summary_file}")
    print(f"Eşleşmeler kaydedildi: {matches_file}")


if __name__ == "__main__":
    main()
