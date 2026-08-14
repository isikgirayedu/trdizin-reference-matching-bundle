#!/usr/bin/env python3
"""
Deney 22: Kitap ve Kitap Bölümü Resolver (Book & Chapter Matching)
=================================================================
Bu script, TR Dizin referans eşleştirme pipeline'ında kalan referanslar içindeki
basılı ve elektronik kitapları / kitap bölümlerini (949 adet) çoklu kaynak
(OpenLibrary API, Toplu Katalog TO-KAT / Milli Kütüphane ve Crossref Books)
üzerinden arar, doğrular ve ISBN / kalıcı katalog kaydı ile eşleştirir.

Kullanım:
    python root_scripts/trdizin_experiment22_book_resolver.py --limit 30
    python root_scripts/trdizin_experiment22_book_resolver.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Path tanımları
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment21" / "remaining_after_experiment21_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment22_books"
REMAINING_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment22"

YEAR_RE = re.compile(r"\b(19[4-9][0-9]|20[0-2][0-9])\b")
ISBN_RE = re.compile(r"(?:ISBN(?:-1[03])?:?\s*)?([0-9Xx]{10,13}|97[89][0-9\-]{10,14})", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "ve", "ile", "bir", "icin", "için", "uzerine", "üzerine", "gore", "göre",
    "the", "and", "of", "in", "on", "for", "with", "a", "an", "to", "ed", "eds", "der", "haz"
}

PUBLISHER_KEYWORDS = [
    "yayınları", "yayinlari", "yayınevi", "yayinevi", "yayıncılık", "yayincilik",
    "kitabevi", "basımevi", "basimevi", "press", "publishing", "publisher",
    "publications", "verlag", "academic", "akademik", "nobel", "pegem", "iletişim",
    "metis", "remzi", "anı", "ani", "çolpan", "colpan", "der", "haz"
]


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    words = WORD_RE.findall(text)
    return " ".join(words)


def sequence_similarity(s1: str, s2: str) -> float:
    n1 = normalize_text(s1)
    n2 = normalize_text(s2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def token_overlap_ratio(s1: str, s2: str) -> float:
    w1 = set(normalize_text(s1).split()) - STOPWORDS
    w2 = set(normalize_text(s2).split()) - STOPWORDS
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


def parse_book_reference(text: str) -> Dict[str, Any]:
    cleaned = re.sub(r"^\s*\[?\d+\]?\.?\s*", "", text)
    year_m = YEAR_RE.search(cleaned)
    year = int(year_m.group(1)) if year_m else None

    # ISBN
    isbn_m = ISBN_RE.search(cleaned)
    isbn = isbn_m.group(1).replace("-", "") if isbn_m else None

    # Yazar ve Gövde
    author = ""
    rest = cleaned
    if year_m:
        y_str = year_m.group(1)
        if f"({y_str})" in cleaned:
            parts = cleaned.split(f"({y_str})", 1)
            author = parts[0].strip().rstrip(".,")
            rest = parts[1].strip().lstrip(".,: ")
        elif f"({y_str})." in cleaned:
            parts = cleaned.split(f"({y_str}).", 1)
            author = parts[0].strip().rstrip(".,")
            rest = parts[1].strip().lstrip(".,: ")
    if not author:
        parts = cleaned.split(".", 1)
        if len(parts) > 1:
            author = parts[0].strip()
            rest = parts[1].strip()

    # Kitap Başlığı ve Bölüm Başlığı
    # Bölüm formatı: "Chapter Title. In Editor (Ed.), Book Title (pp. X-Y)..."
    book_title = ""
    in_m = re.search(r"\bIn\b\s+([^,]+(?:Ed\.|Eds\.)?,\s*)?([^(,]+)", rest, re.IGNORECASE)
    if in_m:
        book_title = in_m.group(2).strip().strip("\"'.,:;")

    title_cand = rest
    # Yayınevi ve basımevi kalıplarından öncesini al
    for pub in PUBLISHER_KEYWORDS:
        if pub in title_cand.lower():
            idx = title_cand.lower().find(pub)
            sub = title_cand[:idx].strip().rstrip(".,:; (")
            if "." in sub:
                title_cand = sub.rsplit(".", 1)[0]
            elif len(sub.split()) >= 2:
                title_cand = sub

    # Şehir ve Yayınevi ayrımı (örn. "Ankara: Pegem Akademi...")
    if ":" in title_cand:
        cands = title_cand.split(":")
        if len(cands) == 2 and ("." in cands[0] or len(cands[0].split()) > 2):
            title_cand = cands[0]

    title_cand = re.sub(r"\[.*?\]", "", title_cand).strip().strip("\"'.,:;()[]")
    if "." in title_cand and len(title_cand.split(".")[0].split()) >= 2:
        title_cand = title_cand.split(".")[0].strip()

    return {
        "raw": text,
        "author": author,
        "year": year,
        "isbn": isbn,
        "title": title_cand,
        "book_title": book_title,
    }


class BookSearchEngine:
    def __init__(self, rate_limit: float = 3.0) -> None:
        self.rate_limit = rate_limit
        self.last_req = 0.0
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1.0, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "TRDizinReferenceMatching/1.0 (mailto:isik.onal@sabanciuniv.edu)",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
        })

    def _wait(self) -> None:
        if self.rate_limit <= 0:
            return
        now = time.monotonic()
        elapsed = now - self.last_req
        target = 1.0 / self.rate_limit
        if elapsed < target:
            time.sleep(target - elapsed)
        self.last_req = time.monotonic()

    def search_openlibrary(self, title: str, author: str) -> List[Dict[str, Any]]:
        self._wait()
        author_last = author.split(",")[0].strip() if "," in author else author.split()[-1] if author else ""
        q = f"{title} {author_last}".strip()
        url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(q)}&limit=3"
        try:
            r = self.session.get(url, timeout=12)
            if r.status_code != 200:
                return []
            docs = r.json().get("docs", [])
            results = []
            for d in docs:
                isbns = d.get("isbn", [])
                results.append({
                    "source": "openlibrary",
                    "title": d.get("title", ""),
                    "author": ", ".join(d.get("author_name", [])),
                    "year": d.get("first_publish_year"),
                    "isbn": isbns[0] if isbns else None,
                    "publisher": ", ".join(d.get("publisher", [])[:2]),
                    "url": f"https://openlibrary.org{d.get('key')}" if d.get("key") else "",
                    "key": d.get("key", ""),
                })
            return results
        except Exception:
            return []

    def search_tokat(self, title: str) -> List[Dict[str, Any]]:
        self._wait()
        clean_title = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ ]", " ", title).strip()
        words = clean_title.split()[:7]
        if len(words) < 2:
            return []
        query_str = " ".join(words)

        params = {
            "_f": "1",
            "the_page": "",
            "cwid": "2",
            "keyword": query_str,
            "tokat_search_field": "1",  # Eser adı
            "order": "0",
            "command": "Tara",
        }
        try:
            r = self.session.get("http://www.toplukatalog.gov.tr/", params=params, timeout=15)
            if r.status_code != 200:
                return []

            html = r.content.decode("utf-8", errors="replace")
            # Parse TO-KAT rows
            results: List[Dict[str, Any]] = []
            # Find TR blocks containing Başlık and Yazar
            row_blocks = re.findall(r"Başlık:\s*([^<\n\r]+)(?:.*?Yazar:\s*([^<\n\r]+))?(?:.*?Yayın Yılı:\s*(\d{4}))?", html, re.DOTALL | re.IGNORECASE)

            for b_title, b_author, b_year in row_blocks[:5]:
                clean_bt = b_title.split("/")[0].strip().strip(":")
                isbn_m = re.search(r"ISBN:\s*([0-9Xx\-]+)", html)
                isbn = isbn_m.group(1).replace("-", "") if isbn_m else None

                results.append({
                    "source": "tokat",
                    "title": clean_bt,
                    "author": b_author.strip() if b_author else "",
                    "year": int(b_year) if b_year else None,
                    "isbn": isbn,
                    "publisher": "TO-KAT / Milli Kütüphane",
                    "url": "http://www.toplukatalog.gov.tr/",
                    "key": clean_bt,
                })
            return results
        except Exception:
            return []

    def search_crossref_books(self, title: str, author: str) -> List[Dict[str, Any]]:
        self._wait()
        author_last = author.split(",")[0].strip() if "," in author else author.split()[-1] if author else ""
        q = f"{title} {author_last}".strip()
        url = f"https://api.crossref.org/works?query.bibliographic={urllib.parse.quote(q)}&filter=type:book,type:book-chapter,type:monograph,type:reference-book&rows=3"
        try:
            r = self.session.get(url, timeout=12)
            if r.status_code != 200:
                return []
            items = r.json().get("message", {}).get("items", [])
            results = []
            for it in items:
                authors = []
                for a in it.get("author", []):
                    fn = a.get("family", "")
                    gn = a.get("given", "")
                    authors.append(f"{fn} {gn}".strip())
                year = None
                dp = it.get("issued", {}).get("date-parts", [[None]])[0]
                if dp and dp[0]:
                    year = int(dp[0])

                isbns = it.get("ISBN", [])
                results.append({
                    "source": "crossref_book",
                    "title": it.get("title", [""])[0],
                    "author": ", ".join(authors),
                    "year": year,
                    "isbn": isbns[0] if isbns else None,
                    "doi": it.get("DOI"),
                    "publisher": it.get("publisher", ""),
                    "url": f"https://doi.org/{it.get('DOI')}" if it.get("DOI") else "",
                    "key": it.get("DOI", ""),
                })
            return results
        except Exception:
            return []


def evaluate_book_match(
    parsed: Dict[str, Any],
    candidate: Dict[str, Any]
) -> Tuple[str, float, Dict[str, Any]]:
    score_details: Dict[str, Any] = {"source": candidate.get("source")}

    # 1. ISBN Eşleşmesi
    ref_isbn = parsed.get("isbn")
    cand_isbn = candidate.get("isbn")
    if ref_isbn and cand_isbn and (ref_isbn in cand_isbn or cand_isbn in ref_isbn):
        score_details["reason"] = "exact_isbn_match"
        score_details["isbn"] = ref_isbn
        return "strong", 1.0, score_details

    # 2. Başlık Benzerliği
    ref_title = parsed.get("title", "")
    cand_title = candidate.get("title", "")
    title_sim = sequence_similarity(ref_title, cand_title)
    token_sim = token_overlap_ratio(ref_title, cand_title)

    # Kitap bölümü varsa kitap başlığıyla da kıyasla
    if parsed.get("book_title"):
        bt_sim = sequence_similarity(parsed["book_title"], cand_title)
        bt_tok = token_overlap_ratio(parsed["book_title"], cand_title)
        title_sim = max(title_sim, bt_sim)
        token_sim = max(token_sim, bt_tok)

    best_title_score = max(title_sim, token_sim)
    score_details["title_sim"] = round(title_sim, 3)
    score_details["token_sim"] = round(token_sim, 3)

    # 3. Yazar Eşleşmesi
    ref_author_norm = normalize_text(parsed.get("author", ""))
    cand_author_norm = normalize_text(candidate.get("author", ""))
    author_tokens = set(ref_author_norm.split()) - STOPWORDS
    cand_tokens = set(cand_author_norm.split()) - STOPWORDS
    author_overlap = len(author_tokens & cand_tokens) > 0 if author_tokens and cand_tokens else False
    score_details["author_overlap"] = author_overlap

    # 4. Yıl Uyumu
    ref_year = parsed.get("year")
    cand_year = candidate.get("year")
    year_match = False
    if ref_year and cand_year:
        year_diff = abs(ref_year - cand_year)
        year_match = (year_diff <= 3)  # Kitaplarda baskı/yıl farkı daha geniştir
        score_details["year_diff"] = year_diff

    # Karar Mantığı
    if best_title_score >= 0.82 and (author_overlap or year_match):
        score_details["reason"] = "high_title_author_consensus"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.90:
        score_details["reason"] = "very_high_title_similarity"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.70 and author_overlap and year_match:
        score_details["reason"] = "moderate_title_with_author_and_year"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.60 and author_overlap:
        score_details["reason"] = "moderate_title_author_overlap"
        return "possible", best_title_score, score_details

    return "no_match", best_title_score, score_details


def process_single_book(
    item: Dict[str, Any],
    engine: BookSearchEngine,
    cache: Dict[str, Any]
) -> Dict[str, Any]:
    sample_index = str(item.get("sample_index"))
    raw_context = item.get("context", "")

    if sample_index in cache:
        return cache[sample_index]

    parsed = parse_book_reference(raw_context)
    title = parsed.get("title", "")
    author = parsed.get("author", "")

    candidates: List[Dict[str, Any]] = []

    # 1. OpenLibrary araması
    if title and len(title) >= 4:
        c_ol = engine.search_openlibrary(title, author)
        candidates.extend(c_ol)

    # 2. TO-KAT (Toplu Katalog) araması (Özellikle Türkçe kitaplar için)
    if not candidates and title and len(title) >= 4:
        c_tokat = engine.search_tokat(title)
        candidates.extend(c_tokat)

    # 3. Crossref Books araması
    if not candidates and title and len(title) >= 4:
        c_cr = engine.search_crossref_books(title, author)
        candidates.extend(c_cr)

    best_status = "no_match"
    best_score = 0.0
    best_candidate: Optional[Dict[str, Any]] = None
    best_details: Dict[str, Any] = {}

    for cand in candidates:
        status, score, details = evaluate_book_match(parsed, cand)
        if status == "strong":
            best_status = "strong"
            best_score = score
            best_candidate = cand
            best_details = details
            break
        elif status == "possible" and best_status != "strong" and score > best_score:
            best_status = "possible"
            best_score = score
            best_candidate = cand
            best_details = details

    res = {
        "sample_index": sample_index,
        "publication_id": item.get("publication_id"),
        "reference_id": item.get("reference_id"),
        "context": raw_context,
        "parsed": parsed,
        "match_status": best_status,
        "match_score": round(best_score, 3),
        "score_details": best_details,
        "matched_book": best_candidate,
    }

    cache[sample_index] = res
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Deney 22: Kitap ve Kitap Bölümü Resolver")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum kitap referansı sayısı")
    parser.add_argument("--rate-limit", type=float, default=3.0, help="Saniye başına maksimum istek")
    parser.add_argument("--overwrite", action="store_true", help="Cache'i temizleyip yeniden çalıştır")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REMAINING_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = OUTPUT_DIR / "book_cache.json"
    cache: Dict[str, Any] = {}
    if not args.overwrite and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Yüklendi: {len(cache)} kayıt cache'te mevcut.")
        except Exception:
            cache = {}

    print(f"Girdi dosyası okunuyor: {INPUT_JSONL}")
    book_items: List[Dict[str, Any]] = []
    all_remaining_items: List[Dict[str, Any]] = []

    with open(INPUT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            all_remaining_items.append(obj)
            if obj.get("exclusive_category") == "book_or_chapter":
                book_items.append(obj)

    print(f"Toplam kalan referans: {len(all_remaining_items)}")
    print(f"Hedef 'book_or_chapter' referans sayısı: {len(book_items)}")

    if args.limit:
        book_items = book_items[:args.limit]
        print(f"Limit uygulandı: {len(book_items)} kitap işlenecek.")

    engine = BookSearchEngine(rate_limit=args.rate_limit)

    results: List[Dict[str, Any]] = []
    strong_matches: List[Dict[str, Any]] = []
    possible_matches: List[Dict[str, Any]] = []
    no_matches: List[Dict[str, Any]] = []

    print(f"\n--- Kitap Arama ve Doğrulama Başlatılıyor ({len(book_items)} kayıt) ---")
    start_time = time.time()

    for i, item in enumerate(book_items, 1):
        res = process_single_book(item, engine, cache)
        results.append(res)

        status = res["match_status"]
        if status == "strong":
            strong_matches.append(res)
            cand = res["matched_book"] or {}
            print(f"[{i}/{len(book_items)}] [STRONG - {cand.get('source')}] {res['parsed'].get('author')} ({res['parsed'].get('year')}) -> {cand.get('title')[:55]}... [{cand.get('publisher')[:25]}]")
        elif status == "possible":
            possible_matches.append(res)
            print(f"[{i}/{len(book_items)}] [POSSIBLE] {res['parsed'].get('author')} -> {res['match_score']}")
        else:
            no_matches.append(res)
            if i % 25 == 0:
                print(f"[{i}/{len(book_items)}] [NO MATCH] İşleniyor...")

        if i % 30 == 0 or i == len(book_items):
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    print(f"\nİşlem tamamlandı! Geçen süre: {elapsed:.1f} sn")
    print(f"Strong Match: {len(strong_matches)}")
    print(f"Possible Match: {len(possible_matches)}")
    print(f"No Match: {len(no_matches)}")

    matches_jsonl = OUTPUT_DIR / "book_matches.jsonl"
    with open(matches_jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    matches_csv = OUTPUT_DIR / "book_matches.csv"
    with open(matches_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_index",
            "publication_id",
            "reference_id",
            "match_status",
            "match_score",
            "matched_source",
            "matched_title",
            "matched_author",
            "matched_year",
            "matched_publisher",
            "matched_isbn",
            "matched_url",
            "raw_context",
        ])
        for r in results:
            cand = r.get("matched_book") or {}
            writer.writerow([
                r.get("sample_index"),
                r.get("publication_id"),
                r.get("reference_id"),
                r.get("match_status"),
                r.get("match_score"),
                cand.get("source", ""),
                cand.get("title", ""),
                cand.get("author", ""),
                cand.get("year", ""),
                cand.get("publisher", ""),
                cand.get("isbn", ""),
                cand.get("url", ""),
                r.get("context", ""),
            ])

    strong_indices = {r["sample_index"] for r in strong_matches}
    summary_data = {
        "experiment_id": "experiment22_books",
        "label": "Deney 22: Kitap ve Kitap Bölümü Resolver",
        "total_book_target": len(book_items),
        "new_strong_matches": len(strong_matches),
        "new_possible_matches": len(possible_matches),
        "no_match_count": len(no_matches),
        "target_resolution_rate_percent": round((len(strong_matches) / len(book_items) * 100) if book_items else 0.0, 2),
        "total_sample_size": 10000,
        "previous_found_count": 6548,
        "new_total_found_count": 6548 + len(strong_matches),
        "new_total_found_rate_percent": round(((6548 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment22": len(all_remaining_items) - len(strong_matches),
    }

    summary_json_file = OUTPUT_DIR / "book_summary.json"
    with open(summary_json_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    report_file = OUTPUT_DIR / "book_report_tr.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"""# Deney 22: Kitap ve Kitap Bölümü Resolver Raporu

## Özet
- **Hedef Kitap / Bölüm Referansı:** {len(book_items)}
- **Doğrulanan Strong Eşleşme:** {len(strong_matches)}
- **Olası (Possible) Eşleşme:** {len(possible_matches)}
- **Eşleşmeyen:** {len(no_matches)}
- **Kitap Havuzu Çözüm Oranı:** %{summary_data['target_resolution_rate_percent']}
- **Genel 10k Havuzundaki Yeni Toplam:** {summary_data['new_total_found_count']} / 10.000 (%{summary_data['new_total_found_rate_percent']})

## Örnek Güçlü Eşleşmeler
""")
        for sm in strong_matches[:25]:
            cand = sm.get("matched_book") or {}
            f.write(f"- **[{sm.get('sample_index')}]** `{cand.get('author')}` ({cand.get('year')}) - *{cand.get('title')}*\n")
            f.write(f"  - **Kaynak:** {cand.get('source')} | **Yayınevi:** {cand.get('publisher')} | **ISBN:** {cand.get('isbn')}\n")
            f.write(f"  - **URL:** {cand.get('url')}\n\n")

    remaining_after_22_file = REMAINING_DIR / "remaining_after_experiment22_references.jsonl"
    rem_count = 0
    rem_categories: Dict[str, int] = {}
    with open(remaining_after_22_file, "w", encoding="utf-8") as f_out:
        for it in all_remaining_items:
            if str(it.get("sample_index")) not in strong_indices:
                f_out.write(json.dumps(it, ensure_ascii=False) + "\n")
                rem_count += 1
                cat = it.get("exclusive_category", "other")
                rem_categories[cat] = rem_categories.get(cat, 0) + 1

    rem_summary = {
        "sampled_references": 10000,
        "found_after_experiment22": 6548 + len(strong_matches),
        "found_after_experiment22_rate_percent": round(((6548 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment22": rem_count,
        "remaining_after_experiment22_rate_percent": round((rem_count / 10000 * 100), 2),
        "category_breakdown": rem_categories,
    }
    with open(REMAINING_DIR / "remaining_after_experiment22_summary.json", "w", encoding="utf-8") as f:
        json.dump(rem_summary, f, ensure_ascii=False, indent=2)

    print(f"\nDosyalar başarıyla kaydedildi:")
    print(f" - {summary_json_file}")
    print(f" - {report_file}")
    print(f" - {matches_csv}")
    print(f" - {remaining_after_22_file}")


if __name__ == "__main__":
    main()
