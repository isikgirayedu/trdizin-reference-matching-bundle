#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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


def build_driver(args: argparse.Namespace) -> webdriver.Chrome:
    args.profile_dir.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.page_load_strategy = "eager"
    options.add_argument(f"--user-data-dir={args.profile_dir}")
    options.add_argument("--lang=tr-TR")
    options.add_argument("--window-size=1280,900")
    if args.headless:
        options.add_argument("--headless=new")
    if args.chrome_executable and args.chrome_executable.exists():
        options.binary_location = str(args.chrome_executable)
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(args.page_load_timeout)
    return driver


def compact_selenium_result(element: Any) -> Dict[str, str]:
    title = ""
    link = ""
    snippet = ""
    try:
        title = " ".join((element.find_element(By.CSS_SELECTOR, "h3.gs_rt").text or "").split())
    except NoSuchElementException:
        pass
    try:
        link = element.find_element(By.CSS_SELECTOR, "h3.gs_rt a").get_attribute("href") or ""
    except NoSuchElementException:
        pass
    try:
        snippet = " ".join((element.find_element(By.CSS_SELECTOR, ".gs_rs").text or "").split())
    except NoSuchElementException:
        pass
    return {"title": title, "link": link, "snippet": snippet}


def page_looks_blocked(driver: webdriver.Chrome) -> bool:
    url = (driver.current_url or "").lower()
    if "/sorry/" in url:
        return True
    try:
        text = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
    except NoSuchElementException:
        return False
    return any(marker in text for marker in CAPTCHA_MARKERS)


def wait_for_manual_captcha(driver: webdriver.Chrome, timeout_seconds: int) -> bool:
    print("CAPTCHA/block sayfasi gorundu. Tarayicida manuel coz; bekliyorum.", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not page_looks_blocked(driver):
            return True
        time.sleep(5)
    return not page_looks_blocked(driver)


def wait_for_page(driver: webdriver.Chrome, wait_ms: int) -> None:
    timeout = max((wait_ms / 1000) + 10, 20)
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") != "loading")
    except TimeoutException:
        pass
    if wait_ms > 0:
        time.sleep(wait_ms / 1000)


def scholar_search(
    driver: webdriver.Chrome,
    query: str,
    wait_ms: int,
    captcha_mode: str,
    captcha_timeout: int,
) -> tuple[str, int, Optional[str], Optional[str], List[Dict[str, str]], str]:
    url = SCHOLAR_URL.format(query=quote_plus(query))
    try:
        driver.get(url)
    except TimeoutException:
        pass
    wait_for_page(driver, wait_ms)

    if page_looks_blocked(driver):
        if captcha_mode == "wait" and wait_for_manual_captcha(driver, captcha_timeout):
            wait_for_page(driver, wait_ms)
        else:
            return "captcha", 0, None, None, [], "Google Scholar CAPTCHA/block page"

    result_elements = driver.find_elements(By.CSS_SELECTOR, "div.gs_r.gs_or.gs_scl")
    results = [compact_selenium_result(element) for element in result_elements[:2]]
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
    refs = make_reference_rows(args)
    conn = connect_db(args.db)
    provider = "selenium"
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
    processed = 0
    unique = 0
    nulls = 0
    errors = 0
    captcha_streak = 0
    stop_reason = ""
    driver = build_driver(args)

    try:
        for ref in refs:
            if ref.sample_index in already_done:
                continue
            status = ""
            try:
                status, result_count, link, title, results, error = scholar_search(
                    driver,
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
                if status == "captcha":
                    captcha_streak += 1
                else:
                    captcha_streak = 0
            except Exception as error:
                status = "error"
                save_result(conn, ref, provider, "error", 0, None, None, [], str(error))
                errors += 1
                captcha_streak = 0

            processed += 1
            if processed % args.commit_every == 0:
                conn.commit()
                print(f"processed {processed}/{len(refs)}", flush=True)
            if status == "captcha" and args.stop_on_captcha:
                conn.commit()
                stop_reason = "captcha"
                print("stopped_on_captcha", flush=True)
                break
            if args.max_captcha_streak and captcha_streak >= args.max_captcha_streak:
                conn.commit()
                stop_reason = f"captcha_streak_{captcha_streak}"
                print(f"stopped_on_{stop_reason}", flush=True)
                break
            if args.pause_ms > 0:
                time.sleep(args.pause_ms / 1000)
    finally:
        try:
            driver.quit()
        finally:
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
        "profile_dir": str(args.profile_dir),
        "requested_rows": len(refs),
        "processed_rows": processed,
        "skipped_existing": len(refs) - processed if not args.overwrite else 0,
        "unique_results_saved_with_link": unique,
        "null_results": nulls,
        "error_results": errors,
        "stop_reason": stop_reason,
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search Google Scholar with Selenium and store exactly-one-result links in SQLite.")
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
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/selenium_profile"),
        type=Path,
    )
    parser.add_argument("--chrome-executable", type=Path, default=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--category", action="append")
    parser.add_argument("--sample-index", action="append")
    parser.add_argument("--limit", default=0, type=int)
    parser.add_argument("--max-query-chars", default=220, type=int)
    parser.add_argument("--min-query-chars", default=12, type=int)
    parser.add_argument("--wait-ms", default=2200, type=int)
    parser.add_argument("--page-load-timeout", default=25, type=int)
    parser.add_argument("--pause-ms", default=7000, type=int)
    parser.add_argument("--commit-every", default=20, type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--captcha-mode", choices=("record", "wait"), default="record")
    parser.add_argument("--captcha-timeout", default=180, type=int)
    parser.add_argument("--stop-on-captcha", action="store_true")
    parser.add_argument("--max-captcha-streak", default=0, type=int)
    parser.add_argument(
        "--summary-json",
        default=Path("trdizin_crossref_doi_stats_10k/google_scholar_links/google_scholar_selenium_summary.json"),
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
