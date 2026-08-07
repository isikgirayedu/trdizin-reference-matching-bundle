#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CONTACT_EMAIL = "isik.onal@sabanciuniv.edu"
TRDIZIN_PUBLICATION_URL = "https://search.trdizin.gov.tr/api/publicationById/{publication_id}"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"
DOI_RE = re.compile(r"(10\.\d{4,9}\s*/\s*[^\s\"'<>]+)", re.IGNORECASE)
TRAILING_DOI_PUNCTUATION_RE = re.compile(r"[.,;:)\]}]+$")


class RateLimiter:
    def __init__(self, max_rate: float) -> None:
        self.interval = 1.0 / max_rate if max_rate > 0 else 0.0
        self.lock = threading.Lock()
        self.next_time = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval
        if wait_seconds:
            time.sleep(wait_seconds)


def percent(numerator: int, denominator: int) -> Optional[float]:
    return round((numerator / denominator) * 100.0, 2) if denominator else None


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def write_csv(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_cache(path: Path, cache: Dict[str, Dict[str, Any]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)


def normalize_doi(value: str) -> str:
    doi = unquote(value or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*[:.]?\s*)", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"\s*/\s*", "/", doi)
    doi = re.sub(r"\s+", "", doi)
    doi = doi.strip(" \t\r\n\"'<>[]{}")
    doi = re.split(r"[#?]", doi, maxsplit=1)[0]
    doi = TRAILING_DOI_PUNCTUATION_RE.sub("", doi)
    return doi.lower()


def extract_first_doi(value: str) -> str:
    match = DOI_RE.search(value or "")
    return normalize_doi(match.group(1)) if match else ""


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def sample_index_set_from_csv(path: Path, status_column: str, accepted: set[str]) -> set[str]:
    found: set[str] = set()
    for row in read_csv(path):
        if str(row.get(status_column, "")).strip() in accepted:
            found.add(str(row.get("sample_index", "")))
    return found


def build_base_found(args: argparse.Namespace, sample_rows: List[Dict[str, str]]) -> Dict[str, set[str]]:
    doi_found = {
        str(row.get("sample_index"))
        for row in sample_rows
        if str(row.get("crossref_status", "")).strip() == "found"
    }
    fallback_found = sample_index_set_from_csv(args.doi_fallback_csv, "fallback_status", {"strong", "possible"})
    fallback_found |= sample_index_set_from_csv(args.no_doi_fallback_csv, "fallback_status", {"strong", "possible"})

    stq_found = {
        str(row.get("sample_index"))
        for row in read_csv(args.stq_csv)
        if truthy(row.get("stq_found"))
    }
    openalex_found = sample_index_set_from_csv(args.openalex_csv, "openalex_status", {"strong", "possible"})
    dergipark_found = sample_index_set_from_csv(args.dergipark_csv, "dergipark_status", {"strong", "possible"})
    cleanup_found = sample_index_set_from_csv(args.cleanup_csv, "experiment8_status", {"strong", "possible"})
    europepmc_found = sample_index_set_from_csv(args.europepmc_csv, "europepmc_status", {"strong", "possible"})
    article_file_found = sample_index_set_from_csv(args.article_file_csv, "article_file_probe_status", {"strong", "possible"})
    experiment11_found = sample_index_set_from_csv(args.experiment11_csv, "final_status", {"strong", "possible"})

    crossref_union = doi_found | fallback_found | stq_found
    base = (
        crossref_union
        | openalex_found
        | dergipark_found
        | cleanup_found
        | europepmc_found
        | article_file_found
        | experiment11_found
    )
    return {
        "doi_only": doi_found,
        "fallback": fallback_found,
        "stq": stq_found,
        "crossref_union": crossref_union,
        "openalex": openalex_found,
        "dergipark": dergipark_found,
        "cleanup": cleanup_found,
        "europepmc": europepmc_found,
        "article_file": article_file_found,
        "experiment11": experiment11_found,
        "base": base,
    }


def compact_author_names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names: List[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(" ".join(item["name"].split()))
        elif isinstance(item, str):
            names.append(" ".join(item.split()))
    return "; ".join(name for name in names if name)


def target_publication_id(value: Any) -> str:
    if isinstance(value, int) and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0:
        return str(int(value.strip()))
    return ""


def load_target_references(veriler_jsonl: Path, sample_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_key: Dict[Tuple[str, str], Dict[str, str]] = {
        (str(row.get("publication_id")), str(row.get("reference_id"))): row
        for row in sample_rows
    }
    publication_ids = {key[0] for key in by_key}
    targets: List[Dict[str, Any]] = []

    with veriler_jsonl.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            publication_id = str(item.get("id") or item.get("publication_id") or "")
            if publication_id not in publication_ids:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else item
            if not isinstance(metadata, dict):
                continue
            for reference in metadata.get("references") or []:
                if not isinstance(reference, dict):
                    continue
                reference_id = str(reference.get("id") or "")
                sample = by_key.get((publication_id, reference_id))
                if not sample:
                    continue
                target_id = target_publication_id(reference.get("targetPublication"))
                if not target_id:
                    continue
                context = reference.get("context") or sample.get("context") or ""
                targets.append(
                    {
                        "sample_index": sample.get("sample_index", ""),
                        "publication_id": publication_id,
                        "reference_id": reference_id,
                        "reference_order": sample.get("reference_order", reference.get("order", "")),
                        "target_publication_id": target_id,
                        "reference_year": str(reference.get("year") or ""),
                        "reference_journal_code": str(reference.get("journalCode") or ""),
                        "reference_authors": compact_author_names(reference.get("authors")),
                        "source_doi": normalize_doi(sample.get("doi", "")),
                        "hidden_doi": extract_first_doi(context),
                        "context": context,
                    }
                )
    return sorted(targets, key=lambda row: int(row["sample_index"]))


def make_session(user_agent: str) -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": user_agent})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def extract_trdizin_source(payload: Any, publication_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    hits = ((payload.get("hits") or {}).get("hits") or [])
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if isinstance(source, dict) and str(source.get("id")) == publication_id:
            return source
    return None


def fetch_trdizin_publication(publication_id: str, timeout: float, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_session(f"trdizin-target-publication-resolver/0.1 (mailto:{CONTACT_EMAIL})")
    url = TRDIZIN_PUBLICATION_URL.format(publication_id=publication_id)
    try:
        response = session.get(url, timeout=timeout)
        if response.status_code == 404:
            return publication_id, {"status": "not_found", "http_status": 404}
        if response.status_code == 429:
            return publication_id, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        payload = response.json()
        source = extract_trdizin_source(payload, publication_id)
        if not source:
            return publication_id, {"status": "not_found", "http_status": response.status_code}
        return publication_id, {"status": "ok", "http_status": response.status_code, "source": source}
    except Exception as error:
        return publication_id, {"status": "error", "error": str(error)}


def fetch_crossref_doi(doi: str, timeout: float, rate_limiter: RateLimiter) -> Tuple[str, Dict[str, Any]]:
    rate_limiter.wait()
    session = make_session(f"trdizin-target-publication-crossref-verify/0.1 (mailto:{CONTACT_EMAIL})")
    url = CROSSREF_WORKS_URL.format(doi=quote(doi, safe=""))
    try:
        response = session.get(url, params={"mailto": CONTACT_EMAIL}, timeout=timeout)
        if response.status_code == 404:
            return doi, {"status": "not_found", "http_status": 404}
        if response.status_code == 429:
            return doi, {"status": "rate_limited", "http_status": 429}
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            return doi, {"status": "error", "error": "invalid Crossref payload", "http_status": response.status_code}
        crossref_doi = normalize_doi(str(message.get("DOI") or ""))
        return doi, {"status": "ok", "http_status": response.status_code, "doi": crossref_doi, "message": message}
    except Exception as error:
        return doi, {"status": "error", "error": str(error)}


def fill_missing_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    keys: List[str],
    worker_fn: Any,
    workers: int,
    timeout: float,
    max_start_rate: float,
    save_every: int,
) -> None:
    missing = [key for key in keys if key not in cache]
    if not missing:
        return
    rate_limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(worker_fn, key, timeout, rate_limiter): key
            for key in missing
        }
        for future in as_completed(futures):
            key, result = future.result()
            cache[str(key)] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} requests for {cache_path.name}", flush=True)
    save_cache(cache_path, cache)


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def compact_target_metadata(source: Dict[str, Any]) -> Dict[str, Any]:
    journal = source.get("journal") if isinstance(source.get("journal"), dict) else {}
    issue = source.get("issue") if isinstance(source.get("issue"), dict) else {}
    title = first_text(source.get("orderTitle")) or first_text(source.get("title"))
    return {
        "target_title": title,
        "target_doi": normalize_doi(str(source.get("doi") or "")),
        "target_year": str(source.get("publicationYear") or issue.get("year") or ""),
        "target_journal": str(journal.get("name") or ""),
        "target_journal_code": str(journal.get("id") or ""),
        "target_issn": str(journal.get("issn") or ""),
        "target_eissn": str(journal.get("eissn") or ""),
        "target_doc_type": str(source.get("docType") or source.get("publicationType") or ""),
    }


def score_row(row: Dict[str, Any], trdizin_cache: Dict[str, Dict[str, Any]], crossref_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    target_id = str(row.get("target_publication_id") or "")
    result = trdizin_cache.get(target_id)
    output = {
        **row,
        "trdizin_status": "not_checked",
        "target_doi": "",
        "target_crossref_status": "",
        "target_crossref_doi": "",
        "target_title": "",
        "target_year": "",
        "target_journal": "",
        "target_journal_code": "",
        "target_issn": "",
        "target_eissn": "",
        "target_doc_type": "",
        "request_error": "",
    }
    if not result:
        return output
    if result.get("status") != "ok":
        output["trdizin_status"] = str(result.get("status") or "error")
        output["request_error"] = str(result.get("error") or "")
        return output

    source = result.get("source")
    if not isinstance(source, dict):
        output["trdizin_status"] = "not_found"
        return output

    target_metadata = compact_target_metadata(source)
    output.update(target_metadata)
    doi = str(target_metadata.get("target_doi") or "")
    crossref_result = crossref_cache.get(doi) if doi else None
    if doi and crossref_result:
        output["target_crossref_status"] = str(crossref_result.get("status") or "")
        output["target_crossref_doi"] = normalize_doi(str(crossref_result.get("doi") or ""))
    elif doi:
        output["target_crossref_status"] = "not_checked"
    else:
        output["target_crossref_status"] = "no_doi"

    if doi and output["target_crossref_status"] == "ok":
        output["trdizin_status"] = "strong_doi_crossref"
    elif doi:
        output["trdizin_status"] = "strong_doi_not_crossref_verified"
    else:
        output["trdizin_status"] = "strong_trdizin_id"
    return output


def build_summary(
    sample_rows: List[Dict[str, str]],
    base_sets: Dict[str, set[str]],
    target_rows: List[Dict[str, Any]],
    candidate_rows: List[Dict[str, Any]],
    result_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total = len(sample_rows)
    base_found = len(base_sets["base"])
    strong_statuses = {"strong_doi_crossref", "strong_doi_not_crossref_verified", "strong_trdizin_id"}
    strong = sum(1 for row in result_rows if row.get("trdizin_status") in strong_statuses)
    crossref_doi = sum(1 for row in result_rows if row.get("trdizin_status") == "strong_doi_crossref")
    doi_not_crossref_verified = sum(
        1 for row in result_rows if row.get("trdizin_status") == "strong_doi_not_crossref_verified"
    )
    trdizin_id_only = sum(1 for row in result_rows if row.get("trdizin_status") == "strong_trdizin_id")
    metadata_errors = sum(1 for row in result_rows if row.get("trdizin_status") in {"error", "rate_limited"})
    metadata_not_found = sum(1 for row in result_rows if row.get("trdizin_status") == "not_found")
    target_with_doi = sum(1 for row in result_rows if row.get("target_doi"))
    target_without_doi = sum(1 for row in result_rows if row.get("trdizin_status") == "strong_trdizin_id")
    experiment_found = base_found + strong
    return {
        "experiment_label": "Deney 12 - TR Dizin targetPublication resolver",
        "sampled_references": total,
        "base_found_before_experiment12": base_found,
        "base_found_before_experiment12_rate_percent": percent(base_found, total),
        "target_publication_total": len(target_rows),
        "target_publication_already_found": len(target_rows) - len(candidate_rows),
        "target_publication_candidates_after_base": len(candidate_rows),
        "trdizin_target_strong_matches": strong,
        "trdizin_target_with_doi": target_with_doi,
        "trdizin_target_without_doi": target_without_doi,
        "trdizin_target_crossref_doi_found": crossref_doi,
        "trdizin_target_doi_not_crossref_verified": doi_not_crossref_verified,
        "trdizin_target_id_only_matches": trdizin_id_only,
        "trdizin_metadata_not_found": metadata_not_found,
        "trdizin_metadata_errors": metadata_errors,
        "experiment12_auto_resolved_found": experiment_found,
        "experiment12_auto_resolved_rate_percent": percent(experiment_found, total),
        "experiment12_new_auto_resolved_rate_percent": percent(strong, total),
        "complete": metadata_errors == 0 and metadata_not_found == 0,
        "component_counts": {
            "doi_only": len(base_sets["doi_only"]),
            "crossref_union": len(base_sets["crossref_union"]),
            "openalex": len(base_sets["openalex"]),
            "dergipark": len(base_sets["dergipark"]),
            "cleanup": len(base_sets["cleanup"]),
            "europepmc": len(base_sets["europepmc"]),
            "experiment11": len(base_sets["experiment11"]),
            "base_union_after_experiment11": base_found,
            "trdizin_target_crossref_doi": crossref_doi,
            "trdizin_target_id_only_or_unverified_doi": strong - crossref_doi,
        },
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    status = "tamamlandi" if summary["complete"] else "partial"
    lines = [
        "# Deney 12 - TR Dizin targetPublication Resolver",
        "",
        f"- Durum: {status}",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- Deney 11 sonrasi baz bulunan: {summary['base_found_before_experiment12']} ({summary['base_found_before_experiment12_rate_percent']}%)",
        f"- targetPublication toplam: {summary['target_publication_total']}",
        f"- Bazda zaten bulunan targetPublication: {summary['target_publication_already_found']}",
        f"- Deney 12 hedefi: {summary['target_publication_candidates_after_base']}",
        f"- Yeni TR Dizin strong resolved: {summary['trdizin_target_strong_matches']}",
        f"- Hedef metadata DOI var: {summary['trdizin_target_with_doi']}",
        f"- Hedef DOI Crossref'te dogrulandi: {summary['trdizin_target_crossref_doi_found']}",
        f"- DOI var ama Crossref dogrulanmadi: {summary['trdizin_target_doi_not_crossref_verified']}",
        f"- DOI yok, TR Dizin ID ile resolved: {summary['trdizin_target_id_only_matches']}",
        f"- Metadata bulunamadi: {summary['trdizin_metadata_not_found']}",
        f"- Metadata hata/rate-limit: {summary['trdizin_metadata_errors']}",
        "",
        "## Deney 12 Sonuc",
        "",
        f"- All strict resolved toplam: {summary['experiment12_auto_resolved_found']} ({summary['experiment12_auto_resolved_rate_percent']}%)",
        f"- Yeni resolved artis: {summary['trdizin_target_strong_matches']} ({summary['experiment12_new_auto_resolved_rate_percent']}% toplam)",
        "",
        "Not: Bu deney Crossref aramasini gevsetmez. TR Dizin'in kendi `targetPublication` alanini guvenli ic eslesme olarak kullanir; hedef metadata DOI icerirse DOI ayrica Crossref works endpoint'i ile dogrulanir.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experiment 12: resolve remaining references through TR Dizin targetPublication.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--veriler-jsonl", default=Path("veriler.jsonl"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-csv", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.csv"), type=Path)
    parser.add_argument("--dergipark-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.csv"), type=Path)
    parser.add_argument("--cleanup-csv", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/crossref_cleanup_matches.csv"), type=Path)
    parser.add_argument("--europepmc-csv", default=Path("trdizin_crossref_doi_stats_10k/europepmc_fallback/europepmc_fallback_matches.csv"), type=Path)
    parser.add_argument("--article-file-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_article_file_probe/dergipark_article_file_probe_matches.csv"), type=Path)
    parser.add_argument("--experiment11-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment11_journal_like/experiment11_matches.csv"), type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/experiment12_trdizin_target"), type=Path)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--max-start-rate", default=8.0, type=float)
    parser.add_argument("--save-every", default=20, type=int)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    trdizin_cache_path = args.out_dir / "trdizin_target_publication_cache.json"
    crossref_cache_path = args.out_dir / "trdizin_target_crossref_doi_cache.json"
    trdizin_cache = load_cache(trdizin_cache_path)
    crossref_cache = load_cache(crossref_cache_path)
    if args.retry_errors:
        for cache_path, cache in [(trdizin_cache_path, trdizin_cache), (crossref_cache_path, crossref_cache)]:
            retryable = [key for key, value in cache.items() if value.get("status") in {"error", "rate_limited"}]
            for key in retryable:
                del cache[key]
            if retryable:
                save_cache(cache_path, cache)
                print(f"removed {len(retryable)} retryable cached errors from {cache_path.name}", flush=True)

    sample_rows = read_csv(args.sample_csv)
    base_sets = build_base_found(args, sample_rows)
    target_rows = load_target_references(args.veriler_jsonl, sample_rows)
    base_found = base_sets["base"]
    candidate_rows = [row for row in target_rows if row["sample_index"] not in base_found]
    target_ids = sorted({row["target_publication_id"] for row in candidate_rows}, key=int)

    print(
        f"sample={len(sample_rows)} base_found={len(base_found)} targetPublication={len(target_rows)} candidates={len(candidate_rows)} unique_targets={len(target_ids)}",
        flush=True,
    )

    if not args.score_only:
        fill_missing_cache(
            cache_path=trdizin_cache_path,
            cache=trdizin_cache,
            keys=target_ids,
            worker_fn=fetch_trdizin_publication,
            workers=args.workers,
            timeout=args.timeout,
            max_start_rate=args.max_start_rate,
            save_every=args.save_every,
        )

        doi_keys: List[str] = []
        for target_id in target_ids:
            result = trdizin_cache.get(target_id)
            if not result or result.get("status") != "ok" or not isinstance(result.get("source"), dict):
                continue
            doi = compact_target_metadata(result["source"]).get("target_doi") or ""
            if doi and doi not in doi_keys:
                doi_keys.append(str(doi))
        fill_missing_cache(
            cache_path=crossref_cache_path,
            cache=crossref_cache,
            keys=doi_keys,
            worker_fn=fetch_crossref_doi,
            workers=max(1, min(args.workers, 6)),
            timeout=args.timeout,
            max_start_rate=max(1.0, min(args.max_start_rate, 6.0)),
            save_every=args.save_every,
        )

    result_rows = [score_row(row, trdizin_cache, crossref_cache) for row in candidate_rows]
    summary = build_summary(sample_rows, base_sets, target_rows, candidate_rows, result_rows)
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "target_publication_id",
        "reference_year",
        "reference_journal_code",
        "reference_authors",
        "source_doi",
        "hidden_doi",
        "trdizin_status",
        "target_doi",
        "target_crossref_status",
        "target_crossref_doi",
        "target_title",
        "target_year",
        "target_journal",
        "target_journal_code",
        "target_issn",
        "target_eissn",
        "target_doc_type",
        "request_error",
        "context",
    ]
    write_csv(args.out_dir / "trdizin_target_publication_matches.csv", fieldnames, result_rows)
    write_jsonl(args.out_dir / "trdizin_target_publication_matches.jsonl", result_rows)
    review_rows = [
        row for row in result_rows if row.get("trdizin_status") not in {"strong_doi_crossref", "strong_doi_not_crossref_verified", "strong_trdizin_id"}
    ]
    write_csv(args.out_dir / "trdizin_target_publication_review_candidates.csv", fieldnames, review_rows)
    write_json(args.out_dir / "trdizin_target_publication_summary.json", summary)
    write_report(args.out_dir / "trdizin_target_publication_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
