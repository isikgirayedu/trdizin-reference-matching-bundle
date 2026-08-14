#!/usr/bin/env python3
"""
Deney 21: YÖK Ulusal Tez Merkezi Resolver (Thesis Matching)
===========================================================
Bu script, TR Dizin referans eşleştirme pipeline'ında kalan referanslar içindeki
lisansüstü tezleri (Yüksek Lisans, Doktora, Tıpta Uzmanlık, Sanatta Yeterlik)
YÖK Ulusal Tez Merkezi (tez.yok.gov.tr) üzerinden arar, doğrular ve eşleştirir.

Kullanım:
    python root_scripts/trdizin_experiment21_yok_tez_resolver.py --limit 30
    python root_scripts/trdizin_experiment21_yok_tez_resolver.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Path tanımları
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment19" / "remaining_after_experiment19_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment21_yok_tez"
REMAINING_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment21"

YEAR_RE = re.compile(r"\b(19[5-9][0-9]|20[0-2][0-9])\b")
TEZ_NO_RE = re.compile(r"(?:tez\s*no\.?|tez\s*numaras[ıi]\.?|y[öo]k\s*tez\s*no\.?)\s*:?\s*(\d{5,8})", re.IGNORECASE)
WORD_RE = re.compile(r"[a-z0-9]+")

DEGREE_PATTERNS = [
    r"yüksek\s+lisans\s+tezi",
    r"yayı?mlanmamış\s+yüksek\s+lisans\s+tezi",
    r"doktora\s+tezi",
    r"yayı?mlanmamış\s+doktora\s+tezi",
    r"tıpta\s+uzmanlık\s+tezi",
    r"sanatta\s+yeterlik\s+tezi",
    r"uzmanlık\s+tezi",
    r"master(?:'s)?\s+thesis",
    r"unpublished\s+master(?:'s)?\s+thesis",
    r"ph\.?d\.?\s+(?:thesis|dissertation)",
    r"doctoral\s+dissertation",
    r"master\s+tezi",
    r"lisans\s+tezi"
]
DEGREE_RE = re.compile(r"\(?\s*\[?\s*(?:" + "|".join(DEGREE_PATTERNS) + r")[^()\[\]]*\)?\s*\]?", re.IGNORECASE)
UNIV_RE = re.compile(r"([A-Za-zÇĞİÖŞÜçğıöşü\s]+(?:Üniversitesi|Universitesi|University|Enstitüsü|Enstitusu|Yüksekokulu|Fakültesi))", re.IGNORECASE)

STOPWORDS = {
    "ve", "ile", "bir", "icin", "için", "uzerine", "üzerine", "gore", "göre",
    "the", "and", "of", "in", "on", "for", "with", "a", "an", "to"
}


def normalize_text(text: str) -> str:
    """Metni küçük harfe çevirir, Türkçe karakterleri normalize eder."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    words = WORD_RE.findall(text)
    return " ".join(words)


def extract_year(text: str) -> Optional[int]:
    matches = YEAR_RE.findall(text)
    if matches:
        return int(matches[0])
    return None


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


def parse_thesis_reference(text: str) -> Dict[str, Any]:
    """Referans metninden tez künye bileşenlerini ayrıştırır."""
    tez_no_m = TEZ_NO_RE.search(text)
    tez_no = tez_no_m.group(1) if tez_no_m else None

    year_m = YEAR_RE.search(text)
    year = int(year_m.group(1)) if year_m else None

    degree_m = DEGREE_RE.search(text)
    degree_text = degree_m.group(0) if degree_m else None

    univ_m = UNIV_RE.search(text)
    univ_text = univ_m.group(1).strip() if univ_m else None

    cleaned = text
    cleaned = re.sub(r"^\s*\[?\d+\]?\.?\s*", "", cleaned)

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

    if degree_m:
        title_cand = re.split(DEGREE_RE, rest)[0]
    elif univ_m:
        idx = rest.find(univ_m.group(1))
        # Üniversiteden önceki kısmı al
        title_cand = rest[:idx]
    else:
        title_cand = rest

    # Şehir ve Yayınevi/Üniversite kalıntısı varsa temizle (örn. "Samsun: Samsun Ondokuz Mayıs...")
    if ":" in title_cand:
        cands = title_cand.split(":")
        if len(cands) == 2 and ("." in cands[0] or len(cands[0].split()) > 2):
            # İlk kısım başlık, ikinci kısım yer/üniversite
            title_cand = cands[0]

    title_cand = re.sub(r"\[.*?\]", "", title_cand).strip().strip("\"'.,:;()[]")

    return {
        "raw": text,
        "tez_no": tez_no,
        "author": author,
        "year": year,
        "degree": degree_text,
        "univ": univ_text,
        "title": title_cand,
    }


class YokTezClient:
    """YÖK Ulusal Tez Merkezi HTTP İstemcisi."""

    BASE_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi/"
    SEARCH_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi/SearchTez"

    def __init__(self, rate_limit: float = 2.0) -> None:
        self.session = requests.Session()
        self.rate_limit = rate_limit
        self.last_req_time = 0.0

        retries = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self._init_session()

    def _init_session(self) -> None:
        try:
            self.session.get(self.BASE_URL, timeout=15)
        except Exception:
            pass

    def _wait_rate(self) -> None:
        if self.rate_limit <= 0:
            return
        now = time.monotonic()
        elapsed = now - self.last_req_time
        target_interval = 1.0 / self.rate_limit
        if elapsed < target_interval:
            time.sleep(target_interval - elapsed)
        self.last_req_time = time.monotonic()

    def search(self, query: str, nevi: str = "7") -> List[Dict[str, Any]]:
        """YÖK Tez Merkezi'nde arama yapar ve dönen sonuç listesini ayrıştırır."""
        self._wait_rate()
        clean_q = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ ]", " ", query).strip()
        clean_q = " ".join(clean_q.split())
        if len(clean_q) < 3:
            return []

        payload = {
            "izin": "0",
            "tur": "0",
            "neden": clean_q,
            "islem": "1",
            "nevi": nevi,
        }

        try:
            resp = self.session.post(self.SEARCH_URL, data=payload, timeout=20)
            if resp.status_code != 200:
                return []

            html = resp.content.decode("utf-8", errors="replace")
            return self._parse_search_response(html)
        except Exception:
            return []

    def _parse_search_response(self, html: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        m = re.search(r"const referenceData\s*=\s*(\{.*?\n\s*\});", html, re.DOTALL)
        ref_data: Dict[str, Any] = {}
        if m:
            raw_js = m.group(1)
            clean_json = re.sub(r",\s*\}", "}", raw_js)
            try:
                ref_data = json.loads(clean_json)
            except Exception:
                ref_data = {}

        card_re = re.compile(
            r'<div class="result-card"[^>]*data-index="(\d+)"[^>]*data-kayitno="([^"]*)"[^>]*data-tezno="([^"]*)"',
            re.IGNORECASE,
        )
        tezno_re = re.compile(r"<strong>\s*Tez No:\s*</strong>\s*(\d+)", re.IGNORECASE)

        cards = card_re.findall(html)
        tez_numbers = tezno_re.findall(html)

        for i, (idx_str, kayitno, tezno_tok) in enumerate(cards):
            tez_num = tez_numbers[i] if i < len(tez_numbers) else None
            meta = ref_data.get(idx_str, {}).get("meta", {})

            item = {
                "index": int(idx_str),
                "yok_tez_no": tez_num,
                "kayit_no": kayitno,
                "tez_token": tezno_tok,
                "author": meta.get("author", ""),
                "year": int(meta["year"]) if meta.get("year", "").isdigit() else None,
                "subject": meta.get("subject", ""),
                "degree_type": meta.get("type", ""),
                "lang": meta.get("lang", ""),
                "yer": meta.get("yer", ""),
                "title": meta.get("title", ""),
                "yok_url": f"https://tez.yok.gov.tr/UlusalTezMerkezi/tezDetay.jsp?id={kayitno}" if kayitno else "",
            }
            results.append(item)

        return results


def evaluate_thesis_match(
    parsed: Dict[str, Any],
    candidate: Dict[str, Any]
) -> Tuple[str, float, Dict[str, Any]]:
    """Aday tez kaydının referans ile eşleşme kalitesini ölçer."""
    score_details: Dict[str, Any] = {}

    # 1. Tez No Eşleşmesi
    ref_tez_no = str(parsed.get("tez_no") or "").strip()
    cand_tez_no = str(candidate.get("yok_tez_no") or "").strip()
    if ref_tez_no and cand_tez_no and ref_tez_no == cand_tez_no:
        score_details["reason"] = "exact_tez_no_match"
        score_details["tez_no"] = ref_tez_no
        return "strong", 1.0, score_details

    # 2. Başlık Benzerliği
    title_sim = sequence_similarity(parsed.get("title", ""), candidate.get("title", ""))
    token_sim = token_overlap_ratio(parsed.get("title", ""), candidate.get("title", ""))
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
        year_match = (year_diff <= 1)
        score_details["year_diff"] = year_diff

    # 5. Üniversite Uyumu
    ref_univ_norm = normalize_text(parsed.get("univ", ""))
    cand_yer_norm = normalize_text(candidate.get("yer", ""))
    univ_match = False
    if ref_univ_norm and cand_yer_norm:
        ref_words = set(ref_univ_norm.split()) - {"universitesi", "university", "enstitusu", "sosyal", "bilimler"}
        if ref_words and any(w in cand_yer_norm for w in ref_words if len(w) >= 4):
            univ_match = True
    score_details["univ_match"] = univ_match

    # Karar Mantığı
    if best_title_score >= 0.80 and (author_overlap or univ_match or year_match):
        score_details["reason"] = "high_title_and_metadata"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.90:
        score_details["reason"] = "very_high_title_similarity"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.70 and author_overlap and (year_match or univ_match):
        score_details["reason"] = "title_author_year_consensus"
        return "strong", best_title_score, score_details
    elif best_title_score >= 0.55 and author_overlap:
        score_details["reason"] = "moderate_title_author_overlap"
        return "possible", best_title_score, score_details

    return "no_match", best_title_score, score_details


def process_single_thesis(
    item: Dict[str, Any],
    client: YokTezClient,
    cache: Dict[str, Any]
) -> Dict[str, Any]:
    sample_index = str(item.get("sample_index"))
    raw_context = item.get("context", "")

    if sample_index in cache:
        return cache[sample_index]

    parsed = parse_thesis_reference(raw_context)
    candidates: List[Dict[str, Any]] = []

    # 1. Tez No ile ara
    if parsed.get("tez_no"):
        candidates = client.search(parsed["tez_no"], nevi="7")

    # 2. İlk 8 kelimelik temiz başlık ile ara
    if not candidates and parsed.get("title"):
        clean_title = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ ]", " ", parsed["title"]).strip()
        words = clean_title.split()[:8]
        if words:
            candidates = client.search(" ".join(words), nevi="7")

    # 3. İlk 5 kelimelik başlık ile ara
    if not candidates and parsed.get("title"):
        clean_title = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ ]", " ", parsed["title"]).strip()
        words = clean_title.split()[:5]
        if len(words) >= 3:
            candidates = client.search(" ".join(words), nevi="7")

    # 4. Yazar Soyadı + İlk 3 Kelime
    if not candidates and parsed.get("author") and parsed.get("title"):
        author_last = parsed["author"].split(",")[0].strip() if "," in parsed["author"] else parsed["author"].split()[-1]
        clean_author = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ]", "", author_last)
        title_words = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ ]", " ", parsed["title"]).split()[:3]
        if clean_author and title_words:
            candidates = client.search(f"{clean_author} {' '.join(title_words)}", nevi="7")

    best_status = "no_match"
    best_score = 0.0
    best_candidate: Optional[Dict[str, Any]] = None
    best_details: Dict[str, Any] = {}

    for cand in candidates:
        status, score, details = evaluate_thesis_match(parsed, cand)
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
        "matched_thesis": best_candidate,
    }

    cache[sample_index] = res
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Deney 21: YÖK Ulusal Tez Merkezi Resolver")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum tez referansı sayısı")
    parser.add_argument("--rate-limit", type=float, default=2.5, help="Saniye başına maksimum YÖK isteği")
    parser.add_argument("--overwrite", action="store_true", help="Cache'i temizleyip yeniden çalıştır")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REMAINING_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = OUTPUT_DIR / "yok_tez_cache.json"
    cache: Dict[str, Any] = {}
    if not args.overwrite and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Yüklendi: {len(cache)} kayıt cache'te mevcut.")
        except Exception:
            cache = {}

    print(f"Girdi dosyası okunuyor: {INPUT_JSONL}")
    thesis_items: List[Dict[str, Any]] = []
    all_remaining_items: List[Dict[str, Any]] = []

    with open(INPUT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            all_remaining_items.append(obj)
            if obj.get("exclusive_category") == "thesis":
                thesis_items.append(obj)

    print(f"Toplam kalan referans: {len(all_remaining_items)}")
    print(f"Hedef 'thesis' referans sayısı: {len(thesis_items)}")

    if args.limit:
        thesis_items = thesis_items[:args.limit]
        print(f"Limit uygulandı: {len(thesis_items)} tez işlenecek.")

    client = YokTezClient(rate_limit=args.rate_limit)

    results: List[Dict[str, Any]] = []
    strong_matches: List[Dict[str, Any]] = []
    possible_matches: List[Dict[str, Any]] = []
    no_matches: List[Dict[str, Any]] = []

    print(f"\n--- YÖK Tez Arama ve Doğrulama Başlatılıyor ({len(thesis_items)} kayıt) ---")
    start_time = time.time()

    for i, item in enumerate(thesis_items, 1):
        res = process_single_thesis(item, client, cache)
        results.append(res)

        status = res["match_status"]
        if status == "strong":
            strong_matches.append(res)
            cand = res["matched_thesis"] or {}
            print(f"[{i}/{len(thesis_items)}] [STRONG] {res['parsed'].get('author')} ({res['parsed'].get('year')}) -> Tez No: {cand.get('yok_tez_no')} | {cand.get('title')[:60]}...")
        elif status == "possible":
            possible_matches.append(res)
            print(f"[{i}/{len(thesis_items)}] [POSSIBLE] {res['parsed'].get('author')} -> {res['match_score']}")
        else:
            no_matches.append(res)
            if i % 15 == 0:
                print(f"[{i}/{len(thesis_items)}] [NO MATCH] İşleniyor...")

        if i % 20 == 0 or i == len(thesis_items):
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    print(f"\nİşlem tamamlandı! Geçen süre: {elapsed:.1f} sn")
    print(f"Strong Match: {len(strong_matches)}")
    print(f"Possible Match: {len(possible_matches)}")
    print(f"No Match: {len(no_matches)}")

    matches_jsonl = OUTPUT_DIR / "yok_tez_matches.jsonl"
    with open(matches_jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    matches_csv = OUTPUT_DIR / "yok_tez_matches.csv"
    with open(matches_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_index",
            "publication_id",
            "reference_id",
            "match_status",
            "match_score",
            "yok_tez_no",
            "yok_title",
            "yok_author",
            "yok_year",
            "yok_university",
            "yok_url",
            "raw_context",
        ])
        for r in results:
            cand = r.get("matched_thesis") or {}
            writer.writerow([
                r.get("sample_index"),
                r.get("publication_id"),
                r.get("reference_id"),
                r.get("match_status"),
                r.get("match_score"),
                cand.get("yok_tez_no", ""),
                cand.get("title", ""),
                cand.get("author", ""),
                cand.get("year", ""),
                cand.get("yer", ""),
                cand.get("yok_url", ""),
                r.get("context", ""),
            ])

    strong_indices = {r["sample_index"] for r in strong_matches}
    summary_data = {
        "experiment_id": "experiment21_yok_tez",
        "label": "Deney 21: YÖK Ulusal Tez Merkezi Resolver",
        "total_thesis_target": len(thesis_items),
        "new_strong_matches": len(strong_matches),
        "new_possible_matches": len(possible_matches),
        "no_match_count": len(no_matches),
        "target_resolution_rate_percent": round((len(strong_matches) / len(thesis_items) * 100) if thesis_items else 0.0, 2),
        "total_sample_size": 10000,
        "previous_found_count": 6410,
        "new_total_found_count": 6410 + len(strong_matches),
        "new_total_found_rate_percent": round(((6410 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment21": len(all_remaining_items) - len(strong_matches),
    }

    summary_json_file = OUTPUT_DIR / "yok_tez_summary.json"
    with open(summary_json_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    report_file = OUTPUT_DIR / "yok_tez_report_tr.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"""# Deney 21: YÖK Ulusal Tez Merkezi Resolver Raporu

## Özet
- **Hedef Tez Referansı:** {len(thesis_items)}
- **Doğrulanan Strong Eşleşme:** {len(strong_matches)}
- **Olası (Possible) Eşleşme:** {len(possible_matches)}
- **Eşleşmeyen:** {len(no_matches)}
- **Tez Havuzu Çözüm Oranı:** %{summary_data['target_resolution_rate_percent']}
- **Genel 10k Havuzundaki Yeni Toplam:** {summary_data['new_total_found_count']} / 10.000 (%{summary_data['new_total_found_rate_percent']})

## Örnek Güçlü Eşleşmeler
""")
        for sm in strong_matches[:20]:
            cand = sm.get("matched_thesis") or {}
            f.write(f"- **[{sm.get('sample_index')}]** `{cand.get('author')}` ({cand.get('year')}) - *{cand.get('title')}*\n")
            f.write(f"  - **YÖK Tez No:** {cand.get('yok_tez_no')} | **Üniversite:** {cand.get('yer')}\n")
            f.write(f"  - **URL:** {cand.get('yok_url')}\n\n")

    remaining_after_21_file = REMAINING_DIR / "remaining_after_experiment21_references.jsonl"
    rem_count = 0
    rem_categories: Dict[str, int] = {}
    with open(remaining_after_21_file, "w", encoding="utf-8") as f_out:
        for it in all_remaining_items:
            if str(it.get("sample_index")) not in strong_indices:
                f_out.write(json.dumps(it, ensure_ascii=False) + "\n")
                rem_count += 1
                cat = it.get("exclusive_category", "other")
                rem_categories[cat] = rem_categories.get(cat, 0) + 1

    rem_summary = {
        "sampled_references": 10000,
        "found_after_experiment21": 6410 + len(strong_matches),
        "found_after_experiment21_rate_percent": round(((6410 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment21": rem_count,
        "remaining_after_experiment21_rate_percent": round((rem_count / 10000 * 100), 2),
        "category_breakdown": rem_categories,
    }
    with open(REMAINING_DIR / "remaining_after_experiment21_summary.json", "w", encoding="utf-8") as f:
        json.dump(rem_summary, f, ensure_ascii=False, indent=2)

    print(f"\nDosyalar başarıyla kaydedildi:")
    print(f" - {summary_json_file}")
    print(f" - {report_file}")
    print(f" - {matches_csv}")
    print(f" - {remaining_after_21_file}")


if __name__ == "__main__":
    main()
