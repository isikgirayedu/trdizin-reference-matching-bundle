#!/usr/bin/env python3
"""
Deney 23: URL & Web Kaynakları / Wayback Machine Resolver
=========================================================
Bu script, TR Dizin referans veri setinde kalan web sayfaları, resmi kurum raporları,
haberler, video ve online veri kaynaklarını (473+ adet) URL ayıklama, canlı HTTP
doğrulama ve Internet Archive Wayback Machine kurtarma motoru üzerinden eşleştirir.

Kullanım:
    python root_scripts/trdizin_experiment23_url_web_resolver.py --limit 30
    python root_scripts/trdizin_experiment23_url_web_resolver.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bs4
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# SSL uyarılarını bastır (resmi gov.tr sitelerindeki sertifika zincirleri için)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_JSONL = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment22" / "remaining_after_experiment22_references.jsonl"
OUTPUT_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "experiment23_url_web"
REMAINING_DIR = BASE_DIR / "trdizin_crossref_doi_stats_10k" / "remaining_after_experiment23"

TRAILING_WORDS_RE = re.compile(
    r"\s+(?:on|at|retrieved|accessed|erişim|tarihinde|tarih|alınmıştır|alinmistir|adresinden|linkinden|from|viewed)\b.*$",
    re.IGNORECASE
)

URL_CLEAN_RE = re.compile(r"(https?://[^\s\"'<>]+(?:\s+[^\s\"'<>]*)?)", re.IGNORECASE)


def extract_clean_url(text: str) -> Optional[str]:
    if not text:
        return None

    m = URL_CLEAN_RE.search(text)
    cand = None
    if m:
        cand = m.group(1).strip()
    else:
        m_www = re.search(r"(www\.[^\s\"'<>]+)", text, re.IGNORECASE)
        if m_www:
            cand = "https://" + m_www.group(1).strip()

    if not cand:
        return None

    # URL sonundaki erişim tarihi / kelimelerini temizle
    cand = TRAILING_WORDS_RE.sub("", cand).strip()

    # PDF satır sonu boşluklarını temizle (örn. "wp- content" veya "status /123")
    cand = re.sub(r"/\s+", "/", cand)
    cand = re.sub(r"\s+/", "/", cand)
    cand = re.sub(r"-\s+", "-", cand)
    cand = re.sub(r"\s+", "", cand)

    # Noktalama işaretlerini temizle
    cand = cand.rstrip(".,:;()[]\"'<>`\\")

    # Temel URL format doğrulaması
    if not (cand.startswith("http://") or cand.startswith("https://")):
        return None
    if "." not in cand.split("/")[2]:
        return None

    return cand


class WebUrlResolver:
    def __init__(self, rate_limit: float = 5.0) -> None:
        self.rate_limit = rate_limit
        self.last_req = 0.0
        self.session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
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

    def check_live_url(self, url: str) -> Dict[str, Any]:
        self._wait()
        try:
            r = self.session.get(url, timeout=9, allow_redirects=True, verify=False)
            status_code = r.status_code
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip()

            title = ""
            if "html" in content_type.lower():
                soup = bs4.BeautifulSoup(r.content[:100000], "html.parser")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                elif soup.find("meta", property="og:title"):
                    title = soup.find("meta", property="og:title").get("content", "").strip()

            is_success = (200 <= status_code < 400)
            return {
                "live": is_success,
                "status_code": status_code,
                "final_url": r.url,
                "content_type": content_type,
                "title": title,
                "is_pdf": ("pdf" in content_type.lower() or r.url.lower().endswith(".pdf")),
            }
        except Exception as e:
            return {
                "live": False,
                "status_code": None,
                "error": str(e)[:100],
            }

    def check_wayback_machine(self, url: str) -> Optional[Dict[str, Any]]:
        self._wait()
        api_url = f"https://archive.org/wayback/available?url={urllib.parse.quote(url)}"
        try:
            r = self.session.get(api_url, timeout=10, verify=False)
            if r.status_code != 200:
                return None
            data = r.json()
            closest = data.get("archived_snapshots", {}).get("closest", {})
            if closest.get("available"):
                return {
                    "available": True,
                    "archive_url": closest.get("url"),
                    "timestamp": closest.get("timestamp"),
                    "original_status": closest.get("status"),
                }
        except Exception:
            pass
        return None


def process_single_reference(
    item: Dict[str, Any],
    resolver: WebUrlResolver,
    cache: Dict[str, Any]
) -> Dict[str, Any]:
    sample_index = str(item.get("sample_index"))
    raw_context = item.get("context", "")

    if sample_index in cache:
        return cache[sample_index]

    extracted_url = extract_clean_url(raw_context)

    if not extracted_url:
        res = {
            "sample_index": sample_index,
            "publication_id": item.get("publication_id"),
            "reference_id": item.get("reference_id"),
            "category": item.get("exclusive_category"),
            "context": raw_context,
            "extracted_url": None,
            "match_status": "no_match",
            "match_type": "no_url_found",
            "match_score": 0.0,
            "resolved_url": None,
            "title": "",
        }
        cache[sample_index] = res
        return res

    # 1. Canlı URL Kontrolü
    live_res = resolver.check_live_url(extracted_url)

    if live_res.get("live"):
        res = {
            "sample_index": sample_index,
            "publication_id": item.get("publication_id"),
            "reference_id": item.get("reference_id"),
            "category": item.get("exclusive_category"),
            "context": raw_context,
            "extracted_url": extracted_url,
            "match_status": "strong",
            "match_type": "live_url_verified",
            "match_score": 1.0,
            "resolved_url": live_res.get("final_url"),
            "status_code": live_res.get("status_code"),
            "content_type": live_res.get("content_type"),
            "title": live_res.get("title"),
            "is_pdf": live_res.get("is_pdf"),
        }
        cache[sample_index] = res
        return res

    # 2. Wayback Machine Kurtarma
    wb_res = resolver.check_wayback_machine(extracted_url)
    if wb_res and wb_res.get("available"):
        res = {
            "sample_index": sample_index,
            "publication_id": item.get("publication_id"),
            "reference_id": item.get("reference_id"),
            "category": item.get("exclusive_category"),
            "context": raw_context,
            "extracted_url": extracted_url,
            "match_status": "strong",
            "match_type": "wayback_archived_verified",
            "match_score": 0.95,
            "resolved_url": wb_res.get("archive_url"),
            "archive_timestamp": wb_res.get("timestamp"),
            "status_code": live_res.get("status_code"),
            "title": "Internet Archive Wayback Snapshot",
        }
        cache[sample_index] = res
        return res

    # 3. Canlı değil ve arşivde yok
    res = {
        "sample_index": sample_index,
        "publication_id": item.get("publication_id"),
        "reference_id": item.get("reference_id"),
        "category": item.get("exclusive_category"),
        "context": raw_context,
        "extracted_url": extracted_url,
        "match_status": "no_match",
        "match_type": "url_dead_and_not_archived",
        "match_score": 0.0,
        "resolved_url": None,
        "status_code": live_res.get("status_code"),
        "error": live_res.get("error"),
    }
    cache[sample_index] = res
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Deney 23: URL & Web / Wayback Machine Resolver")
    parser.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum referans sayısı")
    parser.add_argument("--rate-limit", type=float, default=6.0, help="Saniye başına maksimum HTTP isteği")
    parser.add_argument("--overwrite", action="store_true", help="Cache'i temizleyip yeniden çalıştır")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REMAINING_DIR.mkdir(parents=True, exist_ok=True)

    cache_file = OUTPUT_DIR / "url_cache.json"
    cache: Dict[str, Any] = {}
    if not args.overwrite and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Yüklendi: {len(cache)} kayıt cache'te mevcut.")
        except Exception:
            cache = {}

    print(f"Girdi dosyası okunuyor: {INPUT_JSONL}")
    url_target_items: List[Dict[str, Any]] = []
    all_remaining_items: List[Dict[str, Any]] = []

    with open(INPUT_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            all_remaining_items.append(obj)
            cat = obj.get("exclusive_category")
            ctx = obj.get("context", "")
            # url_web kategorisi veya içinde http://, https://, www. geçenler
            if cat == "url_web" or "http://" in ctx or "https://" in ctx or "www." in ctx:
                url_target_items.append(obj)

    print(f"Toplam kalan referans: {len(all_remaining_items)}")
    print(f"URL taranacak hedef referans sayısı: {len(url_target_items)}")

    if args.limit:
        url_target_items = url_target_items[:args.limit]
        print(f"Limit uygulandı: {len(url_target_items)} referans işlenecek.")

    resolver = WebUrlResolver(rate_limit=args.rate_limit)

    results: List[Dict[str, Any]] = []
    strong_matches: List[Dict[str, Any]] = []
    live_count = 0
    wayback_count = 0
    no_matches: List[Dict[str, Any]] = []

    print(f"\n--- URL Doğrulama ve Kurtarma Başlatılıyor ({len(url_target_items)} kayıt) ---")
    start_time = time.time()

    for i, item in enumerate(url_target_items, 1):
        res = process_single_reference(item, resolver, cache)
        results.append(res)

        status = res["match_status"]
        mtype = res.get("match_type", "")
        if status == "strong":
            strong_matches.append(res)
            if mtype == "live_url_verified":
                live_count += 1
                t_snippet = f" | Title: {res.get('title')[:40]}" if res.get('title') else ""
                print(f"[{i}/{len(url_target_items)}] [LIVE 200] [{res.get('sample_index')}] {res.get('resolved_url')[:65]}...{t_snippet}")
            elif mtype == "wayback_archived_verified":
                wayback_count += 1
                print(f"[{i}/{len(url_target_items)}] [WAYBACK RECOVERED] [{res.get('sample_index')}] {res.get('resolved_url')[:65]}...")
        else:
            no_matches.append(res)
            if i % 30 == 0:
                print(f"[{i}/{len(url_target_items)}] [NO MATCH / OFFLINE] İşleniyor...")

        if i % 30 == 0 or i == len(url_target_items):
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    print(f"\nİşlem tamamlandı! Geçen süre: {elapsed:.1f} sn")
    print(f"Toplam Doğrulanan Strong Eşleşme: {len(strong_matches)}")
    print(f" - Canlı Aktif URL (HTTP 200): {live_count}")
    print(f" - Wayback Machine ile Kurtarılan: {wayback_count}")
    print(f"Doğrulanamayan / Kapalı URL: {len(no_matches)}")

    matches_jsonl = OUTPUT_DIR / "url_matches.jsonl"
    with open(matches_jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    matches_csv = OUTPUT_DIR / "url_matches.csv"
    with open(matches_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "sample_index",
            "publication_id",
            "reference_id",
            "category",
            "match_status",
            "match_type",
            "match_score",
            "extracted_url",
            "resolved_url",
            "status_code",
            "title",
            "raw_context",
        ])
        for r in results:
            writer.writerow([
                r.get("sample_index"),
                r.get("publication_id"),
                r.get("reference_id"),
                r.get("category"),
                r.get("match_status"),
                r.get("match_type"),
                r.get("match_score"),
                r.get("extracted_url", ""),
                r.get("resolved_url", ""),
                r.get("status_code", ""),
                r.get("title", ""),
                r.get("context", ""),
            ])

    strong_indices = {r["sample_index"] for r in strong_matches}
    summary_data = {
        "experiment_id": "experiment23_url_web",
        "label": "Deney 23: URL & Web / Wayback Machine Resolver",
        "total_target": len(url_target_items),
        "new_strong_matches": len(strong_matches),
        "live_url_verified_count": live_count,
        "wayback_archived_count": wayback_count,
        "no_match_count": len(no_matches),
        "target_resolution_rate_percent": round((len(strong_matches) / len(url_target_items) * 100) if url_target_items else 0.0, 2),
        "total_sample_size": 10000,
        "previous_found_count": 6701,
        "new_total_found_count": 6701 + len(strong_matches),
        "new_total_found_rate_percent": round(((6701 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment23": len(all_remaining_items) - len(strong_matches),
    }

    summary_json_file = OUTPUT_DIR / "url_summary.json"
    with open(summary_json_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    report_file = OUTPUT_DIR / "url_report_tr.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"""# Deney 23: URL & Web / Wayback Machine Resolver Raporu

## Özet
- **Hedef Web / URL Referansı:** {len(url_target_items)}
- **Doğrulanan Strong Eşleşme:** {len(strong_matches)}
  - **Canlı Aktif Link (HTTP 200):** {live_count}
  - **Wayback Machine Kurtarma:** {wayback_count}
- **Eşleşmeyen / Kırık:** {len(no_matches)}
- **URL Havuzu Çözüm Oranı:** %{summary_data['target_resolution_rate_percent']}
- **Genel 10k Havuzundaki Yeni Toplam:** {summary_data['new_total_found_count']} / 10.000 (%{summary_data['new_total_found_rate_percent']})

## Örnek Doğrulanan Web Kaynakları
""")
        for sm in strong_matches[:30]:
            f.write(f"- **[{sm.get('sample_index')}]** `{sm.get('match_type')}`\n")
            f.write(f"  - **URL:** {sm.get('resolved_url')}\n")
            if sm.get("title"):
                f.write(f"  - **Başlık:** {sm.get('title')}\n")
            f.write(f"  - **Ham Metin:** {sm.get('context')[:120]}...\n\n")

    remaining_after_23_file = REMAINING_DIR / "remaining_after_experiment23_references.jsonl"
    rem_count = 0
    rem_categories: Dict[str, int] = {}
    with open(remaining_after_23_file, "w", encoding="utf-8") as f_out:
        for it in all_remaining_items:
            if str(it.get("sample_index")) not in strong_indices:
                f_out.write(json.dumps(it, ensure_ascii=False) + "\n")
                rem_count += 1
                cat = it.get("exclusive_category", "other")
                rem_categories[cat] = rem_categories.get(cat, 0) + 1

    rem_summary = {
        "sampled_references": 10000,
        "found_after_experiment23": 6701 + len(strong_matches),
        "found_after_experiment23_rate_percent": round(((6701 + len(strong_matches)) / 10000 * 100), 2),
        "remaining_after_experiment23": rem_count,
        "remaining_after_experiment23_rate_percent": round((rem_count / 10000 * 100), 2),
        "category_breakdown": rem_categories,
    }
    with open(REMAINING_DIR / "remaining_after_experiment23_summary.json", "w", encoding="utf-8") as f:
        json.dump(rem_summary, f, ensure_ascii=False, indent=2)

    print(f"\nDosyalar başarıyla kaydedildi:")
    print(f" - {summary_json_file}")
    print(f" - {report_file}")
    print(f" - {matches_csv}")
    print(f" - {remaining_after_23_file}")


if __name__ == "__main__":
    main()
