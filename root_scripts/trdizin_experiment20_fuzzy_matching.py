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


def query_openalex_fuzzy(clean_title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """OpenAlex API'ye esnek arama sorgusu atar."""
    if not clean_title or len(clean_title) < 10:
        return None

    url = "https://api.openalex.org/works"
    params: Dict[str, Any] = {
        "search": clean_title,
        "per-page": 3,
        "mailto": CONTACT_EMAIL
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            for item in results:
                cand_title = item.get("title") or ""
                sim = calculate_similarity(clean_title, cand_title)
                doi = item.get("doi")
                if sim >= 0.80 and doi:
                    clean_doi = doi.replace("https://doi.org/", "")
                    return {
                        "doi": clean_doi,
                        "title": cand_title,
                        "similarity": round(sim, 3),
                        "publisher": item.get("host_venue", {}).get("publisher") if item.get("host_venue") else None,
                        "source": "openalex_fuzzy"
                    }
    except Exception:
        pass
    return None


def query_google_books_fuzzy(clean_title: str) -> Optional[Dict[str, Any]]:
    """Google Books API'ye kitap referansı için arama sorgusu atar."""
    if not clean_title or len(clean_title) < 10:
        return None

    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": clean_title, "maxResults": 3}
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                vinfo = item.get("volumeInfo", {})
                cand_title = vinfo.get("title", "")
                sim = calculate_similarity(clean_title, cand_title)
                if sim >= 0.75:
                    isbns = [id_obj.get("identifier") for id_obj in vinfo.get("industryIdentifiers", []) if id_obj.get("type") in ("ISBN_13", "ISBN_10")]
                    isbn_val = isbns[0] if isbns else None
                    return {
                        "doi": f"ISBN:{isbn_val}" if isbn_val else f"GBOOKS:{item.get('id')}",
                        "title": cand_title,
                        "similarity": round(sim, 3),
                        "publisher": vinfo.get("publisher"),
                        "source": "google_books_fuzzy"
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


from concurrent.futures import ThreadPoolExecutor, as_completed

def _process_single_ref(ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cat = ref.get("exclusive_category", "other")
    context = ref.get("context", "")
    clean_t = normalize_text(context)
    ref_year = extract_year(context)

    # 1. Crossref Fuzzy
    match_res = query_crossref_fuzzy(clean_t, ref_year)
    
    # 2. OpenAlex Fuzzy (Eğer Crossref bulamadıysa)
    if not match_res:
        match_res = query_openalex_fuzzy(clean_t, ref_year)

    # 3. Google Books Fuzzy (Kitaplar veya kalanlar için)
    if not match_res and cat in ("book_or_chapter", "other"):
        match_res = query_google_books_fuzzy(clean_t)

    if match_res:
        return {
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
    return None


def process_fuzzy_matching(references: List[Dict[str, Any]], limit: Optional[int] = None, category_filter: Optional[str] = None, max_workers: int = 12) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Kalan referanslar üzerinde paralel (multithreaded) esnek eşleştirme (Fuzzy Matching) çalıştırır.
    """
    matches = []
    category_counts: Dict[str, int] = {}

    if category_filter and category_filter != "all":
        target_refs = [r for r in references if r.get("exclusive_category") == category_filter]
    else:
        target_refs = references

    if limit:
        target_refs = target_refs[:limit]

    for r in target_refs:
        cat = r.get("exclusive_category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    print(f"-> Toplam {len(target_refs)} referans üzerinde {max_workers} paralel iş parçacığı (worker) ile Fuzzy Matching çalıştırılıyor...")

    completed_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ref = {executor.submit(_process_single_ref, ref): ref for ref in target_refs}
        for future in as_completed(future_to_ref):
            completed_count += 1
            res = future.result()
            if res:
                matches.append(res)
            if completed_count % 10 == 0 or completed_count == len(target_refs):
                print(f"   İşlenen: {completed_count}/{len(target_refs)} | Yeni Bulunan Eşleşme: {len(matches)}", end="\r", flush=True)

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
