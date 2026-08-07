#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from trdizin_google_scholar_link_collector import (
    connect_db,
    existing_sample_indexes,
    make_reference_rows,
    save_result,
    utc_now,
)


SCHOLAR_URL = "https://scholar.google.com/scholar?hl=tr&q={query}"
CAPTCHA_MARKERS = (
    "unusual traffic",
    "not a robot",
    "our systems have detected",
    "sorry",
    "captcha",
)


def import_playwright() -> Any:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit(
            "Playwright gerekli. Kurulum:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium"
        ) from error
    return sync_playwright, PlaywrightTimeoutError


def compact_browser_result(handle: Any) -> Dict[str, str]:
    title = ""
    link = ""
    snippet = ""
    title_node = handle.query_selector("h3.gs_rt")
    link_node = handle.query_selector("h3.gs_rt a")
    snippet_node = handle.query_selector(".gs_rs")
    if title_node:
        title = " ".join((title_node.inner_text() or "").split())
    if link_node:
        link = link_node.get_attribute("href") or ""
    if snippet_node:
        snippet = " ".join((snippet_node.inner_text() or "").split())
    return {"title": title, "link": link, "snippet": snippet}


def page_looks_blocked(page: Any) -> bool:
    url = (page.url or "").lower()
    if "/sorry/" in url:
        return True
    try:
        text = (page.locator("body").inner_text(timeout=2500) or "").lower()
    except Exception:
        return False
    return any(marker in text for marker in CAPTCHA_MARKERS)


def wait_for_manual_captcha(page: Any, timeout_seconds: int) -> bool:
    print("CAPTCHA/block sayfasi gorundu. Tarayicida manuel coz; bekliyorum.", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        if not page_looks_blocked(page):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(5000)


def scholar_search(page: Any, query: str, wait_ms: int, captcha_mode: str, captcha_timeout: int) -> tuple[str, int, Optional[str], Optional[str], List[Dict[str, str]], str]:
    url = SCHOLAR_URL.format(query=quote_plus(query))
    page.goto(url, wait_until="domcontentloaded", timeout=max(wait_ms + 10000, 20000))
    page.wait_for_timeout(wait_ms)

    if page_looks_blocked(page):
        if captcha_mode == "wait" and wait_for_manual_captcha(page, captcha_timeout):
            page.wait_for_timeout(wait_ms)
        else:
            return "captcha", 0, None, None, [], "Google Scholar CAPTCHA/block page"

    result_handles = page.query_selector_all("div.gs_r.gs_or.gs_scl")
    results = [compact_browser_result(handle) for handle in result_handles[:2]]
    results = [item for item in results if item.get("title") or item.get("link")]

    if len(results) == 1:
        link = results[0].get("link") or None
        title = results[0].get("title") or None
        if link:
            return "unique_result", 1, link, title, results, ""
        return "unique_no_link", 1, None, title, results, ""
    if not results:
        return "no_result", 0, None, None, [], ""
    return "ambiguous", 2, None, None, results, ""


def run(args: argparse.Namespace) -> Dict[str, Any]:
    sync_playwright, _ = import_playwright()
    refs = make_reference_rows(args)
    conn = connect_db(args.db)
    provider = "browser"
    run_cursor = conn.execute(
        """
        INSERT INTO scholar_runs (provider, input_path, started_at, requested_rows)
        VALUES (?, ?, ?, ?)
        """,
        (provider, str(args.input), utc_now(), len(refs)),
    )
    run_id = int(run_cursor.lastrowid)
    conn.commit()

    already_done = existing_sample_indexes(conn, provider) if not args.overwrite else set()
    profile_dir = args.profile_dir
    profile_dir.mkdir(parents=True, exist_ok=True)
    processed = 0
    unique = 0
    nulls = 0
    errors = 0

    with sync_playwright() as playwright:
        launch_kwargs: Dict[str, Any] = {
            "headless": args.headless,
            "viewport": {"width": 1280, "height": 900},
            "locale": "tr-TR",
        }
        if args.chrome_executable:
            launch_kwargs["executable_path"] = str(args.chrome_executable)

        context = playwright.chromium.launch_persistent_context(str(profile_dir), **launch_kwargs)
        page = context.pages[0] if context.pages else context.new_page()

        for ref in refs:
            if ref.sample_index in already_done:
                continue
            try:
                status, result_count, link, title, results, error = scholar_search(
                    page,
                    ref.query,
                    args.wait_ms,
                    args.captcha_mode,
                    args.captcha_timeout,
                )
                save_result(conn, ref, provider, status, result_count, link, title, results, error)
                if status == "unique_result":
                    unique += 1
                elif status == "error":
                    errors += 1
                else:
                    nulls += 1
            except Exception as error:
                save_result(conn, ref, provider, "error", 0, None, None, [], str(error))
                errors += 1

            processed += 1
            if processed % args.commit_every == 0:
                conn.commit()
                print(f"processed {processed}/{len(refs)}", flush=True)
            if args.pause_ms:
                page.wait_for_timeout(args.pause_ms)

        context.close()

    conn.commit()
    conn.execute(
        """
        UPDATE scholar_runs
        SET finished_at = ?, processed_rows = ?, unique_results = ?, null_results = ?, error_results = ?
        WHERE id = ?
        """,
        (utc_now(), processed, unique, nulls, errors, run_id),
    )
    conn.commit()

    summary = {
        "run_id": run_id,
        "provider": provider,
        "input": str(args.input),
        "db": str(args.db),
        "profile_dir": str(profile_dir),
        "requested_rows": len(refs),
        "processed_rows": processed,
        "skipped_existing": len(refs) - processed if not args.overwrite else 0,
        "unique_results_saved_with_link": unique,
        "null_results": nulls,
        "error_results": errors,
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search Google Scholar in a real browser and store links in SQLite.")
    parser.add_argument(
        "--input",
        default=Path("trdizin_crossref_doi_stats_10k/remaining_after_experiment19/remaining_after_experiment19_references.jsonl"),
        type=Path,
    )
    parser.add_argument(
        "--db",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_links.sqlite"),
        type=Path,
    )
    parser.add_argument(
        "--profile-dir",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/browser_profile"),
        type=Path,
        help="Persistent browser profile. Separate profile is safer than your active Chrome profile.",
    )
    parser.add_argument("--chrome-executable", type=Path, default=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--category", action="append")
    parser.add_argument("--sample-index", action="append")
    parser.add_argument("--limit", default=0, type=int)
    parser.add_argument("--max-query-chars", default=220, type=int)
    parser.add_argument("--min-query-chars", default=12, type=int)
    parser.add_argument("--wait-ms", default=2500, type=int)
    parser.add_argument("--pause-ms", default=9000, type=int)
    parser.add_argument("--commit-every", default=10, type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--captcha-mode", choices=("record", "wait"), default="record")
    parser.add_argument("--captcha-timeout", default=180, type=int)
    parser.add_argument(
        "--summary-json",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_browser_summary.json"),
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chrome_executable and not args.chrome_executable.exists():
        args.chrome_executable = None
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
