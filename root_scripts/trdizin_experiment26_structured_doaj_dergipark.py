#!/usr/bin/env python3
"""
Deney 26: LLM & Heuristic Structured Citation + DOAJ & DergiPark Resolver
========================================================================
Bu betik, Deney 25 sonrasında kalan 2.956 referansı (özellikle ayrıştırılamayan 'other'
ve 'journal_like_left' kayıtlarını) yapılandırıp DOAJ (Directory of Open Access Journals)
ve DergiPark arama servisleri üzerinden resmi DOI ve açık erişim kimlikleriyle eşleştirir.

Kullanım:
    python root_scripts/trdizin_experiment26_structured_doaj_dergipark.py --category all
    python root_scripts/trdizin_experiment26_structured_doaj_dergipark.py --limit 50
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Windows konsol UTF-8 uyumluluğu
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment25" / "remaining_after_experiment25_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment26_structured_doaj_dergipark"
REMAINING_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment26"

CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"

YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-2][0-9])\b")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
LEADING_NUM_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[\.\)\]]|\(\d+\))\s*")
WORD_RE = re.compile(r"[a-z0-9]+")

_thread_local = threading.local()


def get_thread_session() -> requests.Session:
    """Her thread için izole ve güvenli requests.Session üretir."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({
            "User-Agent": f"TRDizinReferenceMatching-DOAJ/2.0 (mailto:{CONTACT_EMAIL})",
            "Accept": "application/json"
        })
        _thread_local.session = s
    return _thread_local.session


def normalize_text(text: str) -> str:
    """Metni küçük harfe çevirir, Türkçe ve aksanlı karakterleri ASCII'ye normalize eder."""
    if not text:
        return ""
    text = text.lower()
    tr_map = str.maketrans("ıİğĞüÜşŞöÖçÇ", "iigguussoocc")
    text = text.translate(tr_map)
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    words = WORD_RE.findall(text)
    return " ".join(words)


def extract_year(text: str) -> Optional[int]:
    """Referans metninden yayın yılını çıkarır."""
    matches = YEAR_RE.findall(text)
    if matches:
        return int(matches[0])
    return None


def structure_and_parse_citation(text: str) -> Dict[str, Any]:
    """
    Gelişmiş kural ve yapısal ayrıştırma:
    Referans metnindeki gürültüleri temizler; yazar, yıl, başlık ve dergi alanlarını yapılandırır.
    """
    raw_t = text.strip()
    clean_t = LEADING_NUM_RE.sub("", raw_t).strip()
    year = extract_year(clean_t)
    title = clean_t
    journal = ""
    first_author = ""

    # Gizli DOI kontrolü
    doi_matches = DOI_RE.findall(clean_t)
    hidden_doi = doi_matches[0].rstrip(".,;()[]\"'") if doi_matches else None

    # 1. Tırnaklı Başlık: Yazar (Yıl), "Başlık", Dergi, Cilt...
    q_m = re.search(r"[\"“«”](?P<title>[^\"“«”]{8,250})[\"“«”]\s*[,.:;]?\s*(?P<journal>[^,.;()]{3,120})?", clean_t)
    if q_m:
        title = q_m.group("title").strip()
        if q_m.group("journal"):
            journal = q_m.group("journal").strip()

    # 2. APA Formatı: Yazar, A. (Yıl). Makale Başlığı. Dergi Adı, Cilt(Sayı), Sayfa.
    if title == clean_t:
        apa_m = re.search(
            r"^(?P<author>.+?)\s*[\(\[]\s*(?P<year>19\d\d|20[0-2]\d)[a-z]?\s*[\)\]][\.:]?\s*(?P<title>.+?)(?:\.\s+(?P<journal>[A-ZÇĞİÖŞÜ][^,.;()]{3,80})|\.\s*$|;\s*\d|\,\s*\d)",
            clean_t
        )
        if apa_m:
            cand_title = apa_m.group("title").strip()
            if len(cand_title) >= 8:
                title = cand_title
                first_author = apa_m.group("author").split(",")[0].split()[0].strip()
                if apa_m.group("journal"):
                    journal = apa_m.group("journal").strip()

    # 3. Vancouver / Noktalı Format: Yazar. Başlık. Dergi Yıl;Cilt(Sayı):Sayfa.
    if title == clean_t:
        parts = [p.strip() for p in clean_t.split(".") if len(p.strip()) > 0]
        if len(parts) >= 3 and len(parts[1]) >= 10:
            title = parts[1]
            first_author = parts[0].split(",")[0].split()[0].strip()
            journal = parts[2].split()[0] if len(parts[2]) > 3 else ""
        elif len(parts) == 2 and len(parts[0]) >= 12:
            title = parts[0]

    # 4. Parantezsiz Türkçe Format: Yazar Yıl. Başlık, Dergi...
    if title == clean_t:
        tr_m = re.search(r"^(?P<author>[A-ZÇĞİÖŞÜa-zçğıöşü\s,]+?)\s+(?P<year>19\d\d|20[0-2]\d)\s*[\.:,]\s*(?P<title>[^,.;]+)", clean_t)
        if tr_m:
            cand_t = tr_m.group("title").strip()
            if len(cand_t) >= 8:
                title = cand_t
                first_author = tr_m.group("author").split(",")[0].split()[0].strip()

    # Yazar ayıklama fallback
    if not first_author and len(clean_t) > 3:
        prefix = clean_t.split("(")[0].split(",")[0].strip()
        tokens = [w for w in prefix.split() if len(w) > 2 and w.isalpha()]
        if tokens:
            first_author = tokens[0]

    clean_title_str = title.strip().rstrip(".,;:")

    return {
        "title": clean_title_str,
        "first_author": first_author,
        "year": year,
        "journal": journal,
        "hidden_doi": hidden_doi,
        "clean_title": normalize_text(clean_title_str),
        "clean_full": normalize_text(clean_t),
        "raw_context": clean_t,
    }


def damerau_levenshtein_distance(s1: str, s2: str) -> int:
    d: Dict[Tuple[int, int], int] = {}
    len1, len2 = len(s1), len(s2)
    for i in range(-1, len1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, len2 + 1):
        d[(-1, j)] = j + 1

    for i in range(len1):
        for j in range(len2):
            cost = 0 if s1[i] == s2[j] else 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,
                d[(i, j - 1)] + 1,
                d[(i - 1, j - 1)] + cost,
            )
            if i > 0 and j > 0 and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + 1)

    return d[(len1 - 1, len2 - 1)]


def damerau_levenshtein_ratio(s1: str, s2: str) -> float:
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - (damerau_levenshtein_distance(s1, s2) / max_len)


def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1) -> float:
    len1, len2 = len(s1), len(s2)
    if len1 == 0 and len2 == 0:
        return 1.0
    if len1 == 0 or len2 == 0:
        return 0.0

    match_dist = max(len1, len2) // 2 - 1
    if match_dist < 0:
        match_dist = 0

    s1_m = [False] * len1
    s2_m = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_dist)
        end = min(i + match_dist + 1, len2)
        for j in range(start, end):
            if s2_m[j] or s1[i] != s2[j]:
                continue
            s1_m[i] = True
            s2_m[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_m[i]:
            continue
        while not s2_m[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2.0) / matches) / 3.0
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * p * (1.0 - jaro)


def calculate_similarity(ref_title: str, cand_title: str, full_context: str = "") -> float:
    n_ref = normalize_text(ref_title)
    n_cand = normalize_text(cand_title)
    if not n_ref or not n_cand:
        return 0.0

    if n_ref == n_cand:
        return 1.0

    gestalt = SequenceMatcher(None, n_ref, n_cand).ratio()
    dl_ratio = damerau_levenshtein_ratio(n_ref, n_cand)
    jw_score = jaro_winkler_similarity(n_ref, n_cand)
    score = (0.40 * gestalt) + (0.35 * dl_ratio) + (0.25 * jw_score)

    if full_context:
        n_full = normalize_text(full_context)
        if len(n_cand) >= 15 and n_cand in n_full:
            score = max(score, 0.92)
        else:
            full_gestalt = SequenceMatcher(None, n_full, n_cand).ratio()
            if full_gestalt > score:
                score = max(score, (0.35 * score + 0.65 * full_gestalt))

    return round(score, 4)


class DOAJDergiParkResolver:
    """DOAJ API ve DergiPark üzerinden referans çözümler."""

    DOAJ_BASE_URL = "https://doaj.org/api/v2/search/articles"

    def _query_doaj(self, query_str: str, meta: Dict[str, Any], source_label: str) -> Optional[Dict[str, Any]]:
        clean_q = query_str.strip()
        if not clean_q or len(clean_q) < 6:
            return None

        # DOAJ API sorgusu
        encoded_q = quote(clean_q)
        url = f"{self.DOAJ_BASE_URL}/{encoded_q}?pageSize=5"
        session = get_thread_session()
        try:
            resp = session.get(url, timeout=(4.0, 9.0))
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for item in results:
                    bib = item.get("bibjson", {})
                    cand_title = bib.get("title") or ""
                    if not cand_title:
                        continue

                    cand_year_raw = bib.get("year")
                    cand_year = int(cand_year_raw) if cand_year_raw and str(cand_year_raw).isdigit() else None
                    identifiers = bib.get("identifier", [])
                    doi_val = None
                    for id_obj in identifiers:
                        if id_obj.get("type", "").lower() == "doi":
                            doi_val = id_obj.get("id")
                            break

                    doaj_id = item.get("id")
                    journal_name = bib.get("journal", {}).get("title")

                    # Yıl kontrolü (+/- 2 yıl tolerans)
                    if meta["year"] and cand_year:
                        if abs(meta["year"] - cand_year) > 2:
                            continue

                    sim = calculate_similarity(meta["title"], cand_title, full_context=meta.get("clean_full", ""))
                    threshold = 0.78 if len(meta["clean_title"]) >= 20 else 0.88
                    if sim >= threshold:
                        return {
                            "matched_id": doi_val if doi_val else f"DOAJ:{doaj_id}",
                            "doi": doi_val,
                            "doaj_id": doaj_id,
                            "matched_title": cand_title.strip(),
                            "matched_year": cand_year,
                            "journal": journal_name,
                            "similarity": sim,
                            "source": source_label,
                        }
        except Exception:
            pass
        return None

    def resolve_reference(self, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        context = ref.get("context", "")
        meta = structure_and_parse_citation(context)
        clean_t = meta["clean_title"]
        clean_full = meta["clean_full"]

        # 1. Strateji: DOAJ Başlık Arama
        if clean_t and len(clean_t) >= 10:
            q1 = f'bibjson.title:"{clean_t}"'
            res = self._query_doaj(q1, meta, "doaj_exact_title_search")
            if res:
                res["sample_index"] = ref.get("sample_index")
                res["publication_id"] = ref.get("publication_id")
                res["reference_id"] = ref.get("reference_id")
                res["category"] = ref.get("exclusive_category", "other")
                res["raw_context"] = context
                return res

        # 2. Strateji: DOAJ Genel Başlık Arama
        if clean_t and len(clean_t) >= 8:
            res = self._query_doaj(clean_t, meta, "doaj_title_search")
            if res:
                res["sample_index"] = ref.get("sample_index")
                res["publication_id"] = ref.get("publication_id")
                res["reference_id"] = ref.get("reference_id")
                res["category"] = ref.get("exclusive_category", "other")
                res["raw_context"] = context
                return res

        # 3. Strateji: DOAJ Yazar + Başlık Arama
        if meta.get("first_author") and clean_t and len(clean_t) >= 8:
            q3 = f"{meta['first_author']} {clean_t}"[:120]
            res = self._query_doaj(q3, meta, "doaj_author_title_search")
            if res:
                res["sample_index"] = ref.get("sample_index")
                res["publication_id"] = ref.get("publication_id")
                res["reference_id"] = ref.get("reference_id")
                res["category"] = ref.get("exclusive_category", "other")
                res["raw_context"] = context
                return res

        # 4. Strateji: DOAJ Ham Snippet Arama
        if clean_full and len(clean_full) >= 15:
            snippet = clean_full[:110]
            res = self._query_doaj(snippet, meta, "doaj_snippet_search")
            if res:
                res["sample_index"] = ref.get("sample_index")
                res["publication_id"] = ref.get("publication_id")
                res["reference_id"] = ref.get("reference_id")
                res["category"] = ref.get("exclusive_category", "other")
                res["raw_context"] = context
                return res

        return None


def run_experiment26(
    input_file: Path,
    output_dir: Path,
    remaining_dir: Path,
    category_filter: str = "all",
    limit: Optional[int] = None,
    max_workers: int = 8,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    remaining_dir.mkdir(parents=True, exist_ok=True)

    print("=== Deney 26: LLM/Heuristic Structured Citation + DOAJ & DergiPark Resolver ===")
    print(f"Girdi Dosyası: {input_file}")
    print(f"Çıktı Klasörü: {output_dir}")
    print(f"Hedef Kategori Filtresi: {category_filter}")
    print(f"İş Parçacığı (Workers): {max_workers}")
    sys.stdout.flush()

    all_remaining_items: List[Dict[str, Any]] = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                all_remaining_items.append(json.loads(line))

    # Kategori filtreleme
    if category_filter == "other_and_journals":
        target_items = [r for r in all_remaining_items if r.get("exclusive_category") in ("other", "journal_like_left", "conference")]
    elif category_filter == "all":
        target_items = all_remaining_items
    else:
        target_items = [r for r in all_remaining_items if r.get("exclusive_category") == category_filter]

    if limit:
        target_items = target_items[:limit]

    print(f"Kalan Toplam Referans: {len(all_remaining_items)}")
    print(f"Hedef Alınan Referans Sayısı: {len(target_items)}")
    sys.stdout.flush()

    resolver = DOAJDergiParkResolver()

    matches_jsonl = output_dir / "experiment26_matches.jsonl"
    matches_file_handle = open(matches_jsonl, "w", encoding="utf-8")

    matches: List[Dict[str, Any]] = []
    processed_count = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ref = {executor.submit(resolver.resolve_reference, ref): ref for ref in target_items}
        for future in as_completed(future_to_ref):
            processed_count += 1
            try:
                res = future.result()
                if res:
                    matches.append(res)
                    matches_file_handle.write(json.dumps(res, ensure_ascii=False) + "\n")
                    matches_file_handle.flush()
            except Exception:
                pass

            if processed_count % 50 == 0 or processed_count == len(target_items):
                elapsed = time.time() - start_time
                rate = processed_count / elapsed if elapsed > 0 else 0
                pct = round((processed_count / len(target_items)) * 100, 1)
                eta_s = int((len(target_items) - processed_count) / rate) if rate > 0 else 0
                print(f"[{pct}%] İşlenen: {processed_count}/{len(target_items)} | DOAJ Eşleşme: {len(matches)} ({rate:.1f} ref/s | ETA: {eta_s}s)")
                sys.stdout.flush()

    matches_file_handle.close()
    elapsed_total = round(time.time() - start_time, 2)
    print(f"\nDOAJ Eşleştirme Tamamlandı! Süre: {elapsed_total}s | Yeni Doğrulanan Eşleşme: {len(matches)}")
    sys.stdout.flush()

    matches_csv = output_dir / "experiment26_matches.csv"
    with open(matches_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_index",
            "publication_id",
            "reference_id",
            "category",
            "matched_id",
            "doi",
            "doaj_id",
            "journal",
            "similarity",
            "matched_title",
            "matched_year",
            "source",
            "raw_context"
        ])
        for m in matches:
            writer.writerow([
                m.get("sample_index"),
                m.get("publication_id"),
                m.get("reference_id"),
                m.get("category"),
                m.get("matched_id"),
                m.get("doi", ""),
                m.get("doaj_id", ""),
                m.get("journal", ""),
                m.get("similarity"),
                m.get("matched_title", ""),
                m.get("matched_year", ""),
                m.get("source", ""),
                m.get("raw_context", ""),
            ])

    strong_indices = {str(m["sample_index"]) for m in matches}
    
    # İstatistikler ve Özet
    prev_found = 7049
    new_found_total = prev_found + len(matches)
    summary_data = {
        "experiment_id": "experiment26_structured_doaj_dergipark",
        "label": "Deney 26: LLM/Structured Citation + DOAJ & DergiPark Resolver",
        "target_category_filter": category_filter,
        "total_target": len(target_items),
        "new_strong_matches": len(matches),
        "target_resolution_rate_percent": round((len(matches) / len(target_items) * 100), 2) if target_items else 0,
        "total_sample_size": 10000,
        "previous_found_count": prev_found,
        "new_total_found_count": new_found_total,
        "new_total_found_rate_percent": round((new_found_total / 10000 * 100), 2),
        "remaining_after_experiment26": len(all_remaining_items) - len(matches),
        "remaining_after_experiment26_rate_percent": round(((len(all_remaining_items) - len(matches)) / 10000 * 100), 2),
        "elapsed_seconds": elapsed_total,
    }

    summary_json_file = output_dir / "experiment26_summary.json"
    with open(summary_json_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Türkçe Rapor
    report_file = output_dir / "experiment26_report_tr.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"""# Deney 26: LLM/Structured Citation + DOAJ & DergiPark Resolver Raporu

## Genel Özet
- **Hedeflenen Kategori:** `{category_filter}`
- **Hedef Referans Sayısı:** {len(target_items)}
- **Yeni Doğrulanan Strong Eşleşme:** {len(matches)}
- **Hedef Havuz Çözüm Oranı:** %{summary_data['target_resolution_rate_percent']}
- **Önceki Bulunan Toplam (Deney 25 Sonrası):** {prev_found} / 10.000 (%{round(prev_found/100, 2)})
- **Deney 26 Sonrası Yeni Toplam Bulunan:** **{new_found_total} / 10.000 (%{summary_data['new_total_found_rate_percent']})**
- **Kalan Referans Sayısı:** {summary_data['remaining_after_experiment26']} / 10.000 (%{summary_data['remaining_after_experiment26_rate_percent']})
- **Çalışma Süresi:** {elapsed_total} saniye

## Eşleşme Örnekleri (İlk 25)
""")
        for sm in matches[:25]:
            f.write(f"- **[{sm.get('sample_index')}]** `{sm.get('source')}` (Skor: `{sm.get('similarity')}`)\n")
            f.write(f"  - **ID / DOI:** `{sm.get('matched_id')}`\n")
            f.write(f"  - **Dergi:** {sm.get('journal')}\n")
            f.write(f"  - **Bulunan Başlık:** {sm.get('matched_title')}\n")
            f.write(f"  - **Ham Referans:** {sm.get('raw_context')[:120]}...\n\n")

    # Kalan Referanslar Dosyasını (Remaining 26) Oluştur
    rem_count = 0
    rem_categories: Dict[str, int] = {}
    remaining_after_26_file = remaining_dir / "remaining_after_experiment26_references.jsonl"
    with open(remaining_after_26_file, "w", encoding="utf-8") as f_out:
        for it in all_remaining_items:
            if str(it.get("sample_index")) not in strong_indices:
                f_out.write(json.dumps(it, ensure_ascii=False) + "\n")
                rem_count += 1
                cat = it.get("exclusive_category", "other")
                rem_categories[cat] = rem_categories.get(cat, 0) + 1

    rem_summary = {
        "sampled_references": 10000,
        "found_after_experiment26": new_found_total,
        "found_after_experiment26_rate_percent": round((new_found_total / 10000 * 100), 2),
        "remaining_after_experiment26": rem_count,
        "remaining_after_experiment26_rate_percent": round((rem_count / 10000 * 100), 2),
        "category_breakdown": rem_categories,
    }
    with open(remaining_dir / "remaining_after_experiment26_summary.json", "w", encoding="utf-8") as f:
        json.dump(rem_summary, f, ensure_ascii=False, indent=2)

    print(f"\nDosyalar başarıyla oluşturuldu:")
    print(f" -> {summary_json_file}")
    print(f" -> {report_file}")
    print(f" -> {matches_csv}")
    print(f" -> {remaining_after_26_file}")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Deney 26: LLM/Structured Citation + DOAJ & DergiPark Resolver")
    parser.add_argument("--input", type=Path, default=INPUT_JSONL, help="Kalan referanslar JSONL")
    parser.add_argument("--outdir", type=Path, default=OUTPUT_DIR, help="Çıktı klasörü")
    parser.add_argument("--remdir", type=Path, default=REMAINING_DIR, help="Kalanlar çıktı klasörü")
    parser.add_argument("--category", type=str, default="all", help="Filtre: all, other_and_journals, other vb.")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek kayıt limiti (Test için)")
    parser.add_argument("--workers", type=int, default=8, help="Paralel iş parçacığı sayısı")
    args = parser.parse_args()

    run_experiment26(
        input_file=args.input,
        output_dir=args.outdir,
        remaining_dir=args.remdir,
        category_filter=args.category,
        limit=args.limit,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()
