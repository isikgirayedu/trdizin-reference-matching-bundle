#!/usr/bin/env python3
"""
Deney 24: OpenAlex & Semantic Scholar Resolver (Gelişmiş Çoklu Strateji)
======================================================================
Bu betik, Deney 23 sonrasında kalan 2.987 referansı OpenAlex Works API (API Key destekli)
ve Semantic Scholar Graph API (Paper Search, Batch Lookup, Snippet/Full-text Arama)
üzerinden çözümler.

Kullanım:
    python root_scripts/trdizin_experiment24_openalex_semanticscholar.py --category all
    python root_scripts/trdizin_experiment24_openalex_semanticscholar.py --limit 50
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
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment23" / "remaining_after_experiment23_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment24_openalex_semanticscholar"
REMAINING_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment24"

DEFAULT_OPENALEX_KEY = "qzxhgKpibkrQB4hz4TNEV4"
CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"

YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-2][0-9])\b")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
ARXIV_RE = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9]+")

_thread_local = threading.local()


def get_thread_session() -> requests.Session:
    """Her thread için izole ve güvenli requests.Session üretir."""
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({
            "User-Agent": f"TRDizinReferenceMatching/2.0 (mailto:{CONTACT_EMAIL})",
            "Accept": "application/json"
        })
        _thread_local.session = s
    return _thread_local.session


def normalize_text(text: str) -> str:
    """Metni küçük harfe çevirir, Türkçe ve aksanlı karakterleri ASCII'ye normalize eder."""
    if not text:
        return ""
    text = text.lower()
    # Özel Türkçe karakter dönüşümleri
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


def extract_metadata_fields(text: str) -> Dict[str, Any]:
    """Referans metninden başlık, yazar, yıl ve gizli DOI/ID alanlarını ayıklar."""
    clean_t = text.strip()
    year = extract_year(clean_t)
    title = clean_t
    first_author = None

    # Gizli DOI kontrolü
    doi_matches = DOI_RE.findall(clean_t)
    hidden_doi = doi_matches[0].rstrip(".,;()[]\"'") if doi_matches else None

    # Gizli arXiv kontrolü
    arxiv_matches = ARXIV_RE.findall(clean_t)
    hidden_arxiv = arxiv_matches[0] if arxiv_matches else None

    # 1. Tırnaklı başlık: Yazar (Yıl), "Başlık", Dergi...
    q_m = re.search(r"[\"“«”](?P<title>[^\"“«”]{10,})[\"“«”]", clean_t)
    if q_m:
        title = q_m.group("title").strip()

    # 2. APA stili: Yazar (Yıl). Başlık. Dergi/Kaynak...
    if title == clean_t:
        apa_m = re.search(
            r"^(?P<author>.+?)\s*[\(\[]\s*(?P<year>19\d\d|20[0-2]\d)[a-z]?\s*[\)\]][\.:]?\s*(?P<title>.+?)(?:\.\s+[A-Z]|\.\s*$|;\s*\d|\,\s*\d)",
            clean_t
        )
        if apa_m:
            cand_title = apa_m.group("title").strip()
            if len(cand_title) >= 10:
                title = cand_title
                first_author = apa_m.group("author").split(",")[0].split()[0].strip()

    # 3. Vancouver / Noktalı stil: Yazar. Başlık. Dergi. Yıl;...
    if title == clean_t:
        parts = [p.strip() for p in clean_t.split(".") if len(p.strip()) > 0]
        if len(parts) >= 3 and len(parts[1]) >= 12:
            title = parts[1]
            first_author = parts[0].split(",")[0].split()[0].strip()
        elif len(parts) == 2 and len(parts[0]) >= 15:
            title = parts[0]

    # Yazar ayıklama fallback
    if not first_author and len(clean_t) > 3:
        prefix = clean_t.split("(")[0].split(",")[0].strip()
        tokens = [w for w in prefix.split() if len(w) > 2 and w.isalpha()]
        if tokens:
            first_author = tokens[0]

    # Başlık temizleme (son noktalama işaretlerini kaldır)
    clean_title_str = title.strip().rstrip(".,;:")

    return {
        "title": clean_title_str,
        "first_author": first_author,
        "year": year,
        "hidden_doi": hidden_doi,
        "hidden_arxiv": hidden_arxiv,
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
        # Eğer aday başlık tam olarak ham referans metninde yer alıyorsa ve yeterince uzunsa
        if len(n_cand) >= 15 and n_cand in n_full:
            score = max(score, 0.92)
        else:
            full_gestalt = SequenceMatcher(None, n_full, n_cand).ratio()
            if full_gestalt > score:
                score = max(score, (0.35 * score + 0.65 * full_gestalt))

    return round(score, 4)


class OpenAlexSemanticScholarResolver:
    def __init__(self, s2_api_key: Optional[str] = None, openalex_api_key: Optional[str] = None):
        self.s2_api_key = s2_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        self.openalex_api_key = openalex_api_key or os.environ.get("OPENALEX_API_KEY", DEFAULT_OPENALEX_KEY)

    def _execute_openalex_request(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = "https://api.openalex.org/works"
        if self.openalex_api_key:
            params["api_key"] = self.openalex_api_key
        if "mailto" not in params:
            params["mailto"] = CONTACT_EMAIL

        session = get_thread_session()
        try:
            resp = session.get(url, params=params, timeout=(4.0, 9.0))
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            elif resp.status_code == 429:
                time.sleep(1.0)
        except Exception:
            pass
        return []

    def _match_openalex_results(self, results: List[Dict[str, Any]], meta: Dict[str, Any], source_label: str) -> Optional[Dict[str, Any]]:
        for item in results:
            cand_title = item.get("title") or ""
            if not cand_title or len(cand_title.strip()) < 5:
                continue

            cand_year = item.get("publication_year")
            doi_raw = item.get("doi")
            clean_doi = doi_raw.replace("https://doi.org/", "").strip() if doi_raw else None
            openalex_id = item.get("id", "").replace("https://openalex.org/", "").strip()

            # Yıl kontrolü (+/- 2 yıl tolerans)
            if meta["year"] and cand_year:
                if abs(meta["year"] - cand_year) > 2:
                    continue

            sim = calculate_similarity(meta["title"], cand_title, full_context=meta.get("clean_full", ""))
            threshold = 0.78 if len(meta["clean_title"]) >= 20 else 0.88
            if sim >= threshold:
                return {
                    "matched_id": clean_doi if clean_doi else f"OPENALEX:{openalex_id}",
                    "doi": clean_doi,
                    "openalex_id": openalex_id,
                    "s2_id": None,
                    "matched_title": cand_title,
                    "matched_year": cand_year,
                    "similarity": sim,
                    "venue": item.get("primary_location", {}).get("source", {}).get("display_name") if item.get("primary_location") and item.get("primary_location").get("source") else None,
                    "source": source_label,
                }
        return None

    def query_openalex_multistrategy(self, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """OpenAlex üzerinde çoklu arama stratejileri dener."""
        clean_t = meta["clean_title"]
        clean_full = meta["clean_full"]

        # Strateji 1: Doğrudan Başlık Arama + Yıl Filtresi
        if clean_t and len(clean_t) >= 10:
            params: Dict[str, Any] = {"search": clean_t, "per-page": 5}
            if meta["year"]:
                params["filter"] = f"publication_year:{meta['year']}"
            res = self._execute_openalex_request(params)
            m = self._match_openalex_results(res, meta, "openalex_title_year_search")
            if m:
                return m

        # Strateji 2: Başlık Genel Arama (Filtresiz)
        if clean_t and len(clean_t) >= 8:
            params = {"search": clean_t, "per-page": 5}
            res = self._execute_openalex_request(params)
            m = self._match_openalex_results(res, meta, "openalex_title_search")
            if m:
                return m

        # Strateji 3: Yazar + Başlık Snippet Arama
        if meta.get("first_author") and clean_t and len(clean_t) >= 8:
            q = f"{meta['first_author']} {clean_t}"[:150]
            params = {"search": q, "per-page": 5}
            res = self._execute_openalex_request(params)
            m = self._match_openalex_results(res, meta, "openalex_author_title_search")
            if m:
                return m

        # Strateji 4: Ham Referans Snippet / Full-Text Arama
        if clean_full and len(clean_full) >= 15:
            snippet = clean_full[:140]
            params = {"search": snippet, "per-page": 5}
            res = self._execute_openalex_request(params)
            m = self._match_openalex_results(res, meta, "openalex_snippet_search")
            if m:
                return m

        return None

    def query_semantic_scholar_search(self, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Semantic Scholar Paper Search API ile sorgulama yapar."""
        search_query = meta["clean_title"] if len(meta["clean_title"]) >= 12 else meta["clean_full"][:120]
        clean_q = normalize_text(search_query)
        if not clean_q or len(clean_q) < 8:
            return None

        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": clean_q,
            "limit": 4,
            "fields": "paperId,title,year,authors,externalIds,venue,url"
        }
        headers: Dict[str, str] = {}
        if self.s2_api_key:
            headers["x-api-key"] = self.s2_api_key

        session = get_thread_session()
        try:
            resp = session.get(url, params=params, headers=headers, timeout=(4.0, 8.0))
            if resp.status_code == 200:
                data = resp.json()
                papers = data.get("data", [])
                for paper in papers:
                    cand_title = paper.get("title") or ""
                    if not cand_title:
                        continue

                    cand_year = paper.get("year")
                    paper_id = paper.get("paperId")
                    ext_ids = paper.get("externalIds", {}) or {}
                    doi_val = ext_ids.get("DOI")

                    if meta["year"] and cand_year:
                        if abs(meta["year"] - cand_year) > 2:
                            continue

                    sim = calculate_similarity(meta["title"], cand_title, full_context=meta.get("clean_full", ""))
                    threshold = 0.78 if len(meta["clean_title"]) >= 20 else 0.88
                    if sim >= threshold:
                        return {
                            "matched_id": doi_val if doi_val else f"S2:{paper_id}",
                            "doi": doi_val,
                            "openalex_id": None,
                            "s2_id": paper_id,
                            "matched_title": cand_title,
                            "matched_year": cand_year,
                            "similarity": sim,
                            "venue": paper.get("venue"),
                            "source": "semantic_scholar_graph_search"
                        }
        except Exception:
            pass

        return None

    def resolve_reference(self, ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        context = ref.get("context", "")
        meta = extract_metadata_fields(context)

        # 1. Aşama: Gizli DOI varsa doğrudan doğrulama
        if meta.get("hidden_doi"):
            h_doi = meta["hidden_doi"]
            # OpenAlex doğrudan DOI sorgusu
            params = {"filter": f"doi:{h_doi}", "per-page": 1}
            res_doi = self._execute_openalex_request(params)
            if res_doi:
                item = res_doi[0]
                cand_title = item.get("title") or ""
                openalex_id = item.get("id", "").replace("https://openalex.org/", "").strip()
                return {
                    "sample_index": ref.get("sample_index"),
                    "publication_id": ref.get("publication_id"),
                    "reference_id": ref.get("reference_id"),
                    "category": ref.get("exclusive_category", "other"),
                    "matched_id": h_doi,
                    "doi": h_doi,
                    "openalex_id": openalex_id,
                    "s2_id": None,
                    "matched_title": cand_title,
                    "matched_year": item.get("publication_year"),
                    "similarity": 1.0,
                    "venue": item.get("primary_location", {}).get("source", {}).get("display_name") if item.get("primary_location") and item.get("primary_location").get("source") else None,
                    "source": "hidden_doi_openalex_lookup",
                    "raw_context": context,
                }

        # 2. Aşama: OpenAlex Çoklu Strateji Arama (Title, Author+Title, Snippet)
        res_oa = self.query_openalex_multistrategy(meta)
        if res_oa:
            res_oa["sample_index"] = ref.get("sample_index")
            res_oa["publication_id"] = ref.get("publication_id")
            res_oa["reference_id"] = ref.get("reference_id")
            res_oa["category"] = ref.get("exclusive_category", "other")
            res_oa["raw_context"] = context
            return res_oa

        # 3. Aşama: Semantic Scholar Graph Search
        res_s2 = self.query_semantic_scholar_search(meta)
        if res_s2:
            res_s2["sample_index"] = ref.get("sample_index")
            res_s2["publication_id"] = ref.get("publication_id")
            res_s2["reference_id"] = ref.get("reference_id")
            res_s2["category"] = ref.get("exclusive_category", "other")
            res_s2["raw_context"] = context
            return res_s2

        return None


def run_experiment24(
    input_file: Path,
    output_dir: Path,
    remaining_dir: Path,
    category_filter: str = "all",
    limit: Optional[int] = None,
    max_workers: int = 10,
    s2_api_key: Optional[str] = None,
    openalex_api_key: Optional[str] = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    remaining_dir.mkdir(parents=True, exist_ok=True)

    print("=== Deney 24: OpenAlex & Semantic Scholar Resolver Başlatıldı ===")
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
    if category_filter == "journal_like_and_other":
        target_items = [r for r in all_remaining_items if r.get("exclusive_category") in ("journal_like_left", "other")]
    elif category_filter == "all":
        target_items = all_remaining_items
    else:
        target_items = [r for r in all_remaining_items if r.get("exclusive_category") == category_filter]

    if limit:
        target_items = target_items[:limit]

    print(f"Kalan Toplam Referans: {len(all_remaining_items)}")
    print(f"Hedef Alınan Referans Sayısı: {len(target_items)}")
    sys.stdout.flush()

    resolver = OpenAlexSemanticScholarResolver(s2_api_key=s2_api_key, openalex_api_key=openalex_api_key)

    matches_jsonl = output_dir / "experiment24_matches.jsonl"
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
            except Exception as e:
                pass

            if processed_count % 50 == 0 or processed_count == len(target_items):
                elapsed = time.time() - start_time
                rate = processed_count / elapsed if elapsed > 0 else 0
                pct = round((processed_count / len(target_items)) * 100, 1)
                eta_s = int((len(target_items) - processed_count) / rate) if rate > 0 else 0
                print(f"[{pct}%] İşlenen: {processed_count}/{len(target_items)} | Eşleşme: {len(matches)} ({rate:.1f} ref/s | ETA: {eta_s}s)")
                sys.stdout.flush()

    matches_file_handle.close()
    elapsed_total = round(time.time() - start_time, 2)
    print(f"\nEşleştirme Tamamlandı! Süre: {elapsed_total}s | Yeni Doğrulanan Eşleşme: {len(matches)}")
    sys.stdout.flush()

    matches_csv = output_dir / "experiment24_matches.csv"
    with open(matches_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_index",
            "publication_id",
            "reference_id",
            "category",
            "matched_id",
            "doi",
            "openalex_id",
            "s2_id",
            "similarity",
            "matched_title",
            "matched_year",
            "venue",
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
                m.get("openalex_id", ""),
                m.get("s2_id", ""),
                m.get("similarity"),
                m.get("matched_title", ""),
                m.get("matched_year", ""),
                m.get("venue", ""),
                m.get("source", ""),
                m.get("raw_context", ""),
            ])

    strong_indices = {str(m["sample_index"]) for m in matches}
    
    # İstatistikler ve Özet
    prev_found = 7018
    new_found_total = prev_found + len(matches)
    summary_data = {
        "experiment_id": "experiment24_openalex_semanticscholar",
        "label": "Deney 24: OpenAlex & Semantic Scholar Resolver",
        "target_category_filter": category_filter,
        "total_target": len(target_items),
        "new_strong_matches": len(matches),
        "target_resolution_rate_percent": round((len(matches) / len(target_items) * 100), 2) if target_items else 0,
        "total_sample_size": 10000,
        "previous_found_count": prev_found,
        "new_total_found_count": new_found_total,
        "new_total_found_rate_percent": round((new_found_total / 10000 * 100), 2),
        "remaining_after_experiment24": len(all_remaining_items) - len(matches),
        "remaining_after_experiment24_rate_percent": round(((len(all_remaining_items) - len(matches)) / 10000 * 100), 2),
        "elapsed_seconds": elapsed_total,
    }

    summary_json_file = output_dir / "experiment24_summary.json"
    with open(summary_json_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Türkçe Rapor
    report_file = output_dir / "experiment24_report_tr.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"""# Deney 24: OpenAlex & Semantic Scholar Resolver Raporu

## Genel Özet
- **Hedeflenen Kategori:** `{category_filter}`
- **Hedef Referans Sayısı:** {len(target_items)}
- **Yeni Doğrulanan Strong Eşleşme:** {len(matches)}
- **Hedef Havuz Çözüm Oranı:** %{summary_data['target_resolution_rate_percent']}
- **Önceki Bulunan Toplam:** {prev_found} / 10.000 (%{round(prev_found/100, 2)})
- **Deney 24 Sonrası Yeni Toplam Bulunan:** **{new_found_total} / 10.000 (%{summary_data['new_total_found_rate_percent']})**
- **Kalan Referans Sayısı:** {summary_data['remaining_after_experiment24']} / 10.000 (%{summary_data['remaining_after_experiment24_rate_percent']})
- **Çalışma Süresi:** {elapsed_total} saniye

## Eşleşme Örnekleri (İlk 25)
""")
        for sm in matches[:25]:
            f.write(f"- **[{sm.get('sample_index')}]** `{sm.get('source')}` (Skor: `{sm.get('similarity')}`)\n")
            f.write(f"  - **ID:** `{sm.get('matched_id')}`\n")
            f.write(f"  - **Bulunan Başlık:** {sm.get('matched_title')}\n")
            f.write(f"  - **Ham Referans:** {sm.get('raw_context')[:120]}...\n\n")

    # Kalan Referanslar Dosyasını (Remaining 24) Oluştur
    rem_count = 0
    rem_categories: Dict[str, int] = {}
    remaining_after_24_file = remaining_dir / "remaining_after_experiment24_references.jsonl"
    with open(remaining_after_24_file, "w", encoding="utf-8") as f_out:
        for it in all_remaining_items:
            if str(it.get("sample_index")) not in strong_indices:
                f_out.write(json.dumps(it, ensure_ascii=False) + "\n")
                rem_count += 1
                cat = it.get("exclusive_category", "other")
                rem_categories[cat] = rem_categories.get(cat, 0) + 1

    rem_summary = {
        "sampled_references": 10000,
        "found_after_experiment24": new_found_total,
        "found_after_experiment24_rate_percent": round((new_found_total / 10000 * 100), 2),
        "remaining_after_experiment24": rem_count,
        "remaining_after_experiment24_rate_percent": round((rem_count / 10000 * 100), 2),
        "category_breakdown": rem_categories,
    }
    with open(remaining_dir / "remaining_after_experiment24_summary.json", "w", encoding="utf-8") as f:
        json.dump(rem_summary, f, ensure_ascii=False, indent=2)

    print(f"\nDosyalar başarıyla oluşturuldu:")
    print(f" -> {summary_json_file}")
    print(f" -> {report_file}")
    print(f" -> {matches_csv}")
    print(f" -> {remaining_after_24_file}")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Deney 24: OpenAlex & Semantic Scholar Resolver")
    parser.add_argument("--input", type=Path, default=INPUT_JSONL, help="Kalan referanslar JSONL")
    parser.add_argument("--outdir", type=Path, default=OUTPUT_DIR, help="Çıktı klasörü")
    parser.add_argument("--remdir", type=Path, default=REMAINING_DIR, help="Kalanlar çıktı klasörü")
    parser.add_argument("--category", type=str, default="all", help="Filtre: all, journal_like_and_other, other vb.")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek kayıt limiti (Test için)")
    parser.add_argument("--workers", type=int, default=8, help="Paralel iş parçacığı sayısı")
    parser.add_argument("--s2-api-key", type=str, default=None, help="Semantic Scholar API Key")
    parser.add_argument("--openalex-api-key", type=str, default=DEFAULT_OPENALEX_KEY, help="OpenAlex API Key")
    args = parser.parse_args()

    run_experiment24(
        input_file=args.input,
        output_dir=args.outdir,
        remaining_dir=args.remdir,
        category_filter=args.category,
        limit=args.limit,
        max_workers=args.workers,
        s2_api_key=args.s2_api_key,
        openalex_api_key=args.openalex_api_key,
    )


if __name__ == "__main__":
    main()
