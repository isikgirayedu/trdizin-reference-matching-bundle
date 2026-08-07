#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import requests

from trdizin_openalex_fallback import (
    CONTACT_EMAIL,
    author_coverage,
    build_crossref_sets,
    context_years,
    normalize_doi,
    percent,
    read_csv,
    title_coverage,
    title_similarity,
    tokens,
)


OAI_BASE = "https://dergipark.org.tr/api/public/oai/"
OAI_ID_PREFIX = "oai:dergipark.org.tr:article/"
JINA_READER_PREFIX = "https://r.jina.ai/http://r.jina.ai/http://"
OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class CandidateScore:
    match_status: str
    confidence: float
    title_coverage: float
    title_similarity: float
    title_token_count: int
    author_coverage: float
    year_match: bool
    candidate: Dict[str, Any]


def normalize_url_text(context: str) -> str:
    compact = re.sub(r"\s+", "", context or "")
    return unquote(compact)


def extract_dergipark_evidence(context: str) -> Dict[str, str]:
    compact = normalize_url_text(context)
    evidence = {"article_id": "", "issue_id": "", "slug": "", "article_file_id": ""}

    article_match = re.search(
        r"dergipark\.(?:org|gov)\.tr/(?:tr|en)?/?pub/([^/\s]+)/issue/([0-9]+)/([0-9]+)",
        compact,
        re.IGNORECASE,
    )
    if article_match:
        evidence["slug"] = article_match.group(1).lower()
        evidence["issue_id"] = article_match.group(2)
        evidence["article_id"] = article_match.group(3)

    article_direct_match = re.search(
        r"dergipark\.(?:org|gov)\.tr/(?:tr|en)?/?pub/([^/\s]+)/article/([0-9]+)",
        compact,
        re.IGNORECASE,
    )
    if article_direct_match and not evidence["article_id"]:
        evidence["slug"] = article_direct_match.group(1).lower()
        evidence["article_id"] = article_direct_match.group(2)

    slug_match = re.search(r"dergipark\.(?:org|gov)\.tr/(?:tr|en)?/?pub/([^/\s?#.,)]+)", compact, re.IGNORECASE)
    if slug_match and not evidence["slug"]:
        evidence["slug"] = slug_match.group(1).lower()

    file_match = re.search(r"dergipark\.(?:org|gov)\.tr/(?:tr|en)?/?download/article-file/([0-9]+)", compact, re.IGNORECASE)
    if file_match:
        evidence["article_file_id"] = file_match.group(1)

    return evidence


def build_base_found(
    sample_rows: List[Dict[str, str]],
    stq_rows: List[Dict[str, str]],
    doi_fallback_rows: List[Dict[str, str]],
    no_doi_fallback_rows: List[Dict[str, str]],
    openalex_rows: List[Dict[str, str]],
) -> set[str]:
    crossref_sets = build_crossref_sets(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows)
    openalex_found = {
        row["sample_index"]
        for row in openalex_rows
        if row.get("openalex_status") in {"strong", "possible"}
    }
    return crossref_sets["union"] | openalex_found


def target_rows(sample_rows: List[Dict[str, str]], base_found: set[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in sample_rows:
        if row["sample_index"] in base_found:
            continue
        evidence = extract_dergipark_evidence(row.get("context") or "")
        query_mode = "no_oai_filter"
        if evidence["article_id"]:
            query_mode = "get_record"
        elif evidence["slug"]:
            query_mode = "list_records"
        elif evidence["article_file_id"]:
            query_mode = "file_url_only"
        rows.append(
            {
                "sample_index": row.get("sample_index", ""),
                "publication_id": row.get("publication_id", ""),
                "reference_id": row.get("reference_id", ""),
                "reference_order": row.get("reference_order", ""),
                "source_doi": normalize_doi(row.get("doi", "")),
                "dergipark_slug": evidence["slug"],
                "dergipark_article_id": evidence["article_id"],
                "dergipark_issue_id": evidence["issue_id"],
                "dergipark_article_file_id": evidence["article_file_id"],
                "query_mode": query_mode,
                "context": row.get("context", ""),
            }
        )
    return rows


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


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/xml,text/xml,*/*",
            "User-Agent": f"trdizin-dergipark-oai/0.1 (mailto:{CONTACT_EMAIL})",
        }
    )
    return session


def request_oai(
    session: requests.Session,
    base_url: str,
    params: Dict[str, str],
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt) if sleep_seconds else 1.0 + attempt))
        try:
            response = session.get(base_url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            continue
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            return {"status": "error", "error": f"xml parse error: {exc}", "http_status": 200}
        error_node = root.find("oai:error", OAI_NS)
        if error_node is not None:
            return {
                "status": "oai_error",
                "code": error_node.get("code") or "",
                "error": " ".join((error_node.text or "").split()),
                "http_status": 200,
            }
        return {"status": "ok", "root": root, "http_status": 200}
    return {"status": "request_error", "error": last_error or "request failed"}


def text_values(element: ET.Element, xpath: str) -> List[str]:
    values = []
    for node in element.findall(xpath, OAI_NS):
        text = " ".join((node.text or "").split())
        if text:
            values.append(text)
    return values


def record_from_element(record: ET.Element) -> Dict[str, Any]:
    header = record.find("oai:header", OAI_NS)
    metadata = record.find("oai:metadata", OAI_NS)
    identifier = ""
    datestamp = ""
    if header is not None:
        identifier = (header.findtext("oai:identifier", default="", namespaces=OAI_NS) or "").strip()
        datestamp = (header.findtext("oai:datestamp", default="", namespaces=OAI_NS) or "").strip()

    titles = text_values(record, ".//dc:title")
    creators = text_values(record, ".//dc:creator")
    identifiers = text_values(record, ".//dc:identifier")
    dates = text_values(record, ".//dc:date")
    publishers = text_values(record, ".//dc:publisher")
    sources = text_values(record, ".//dc:source")
    types = text_values(record, ".//dc:type")
    doi = ""
    url = ""
    for value in identifiers:
        normalized = normalize_doi(value)
        if normalized.startswith("10."):
            doi = normalized
        if value.startswith("http"):
            url = value

    article_id = ""
    match = re.search(r"article/([0-9]+)", identifier)
    if match:
        article_id = match.group(1)
    if not article_id:
        for value in identifiers:
            match = re.search(r"/(?:article|issue/[0-9]+)/([0-9]+)", value)
            if match:
                article_id = match.group(1)
                break

    year = ""
    for value in dates:
        match = re.search(r"(19[0-9]{2}|20[0-3][0-9])", value)
        if match:
            year = match.group(1)
            break

    return {
        "oai_identifier": identifier,
        "oai_datestamp": datestamp,
        "article_id": article_id,
        "title": titles[0] if titles else "",
        "creators": creators,
        "identifiers": identifiers,
        "doi": doi,
        "url": url,
        "year": int(year) if year else None,
        "publisher": publishers[0] if publishers else "",
        "source": sources[0] if sources else "",
        "type": types[0] if types else "",
    }


def jina_url(url: str) -> str:
    return f"{JINA_READER_PREFIX}{url}"


def request_jina_markdown(
    session: requests.Session,
    url: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(8.0, sleep_seconds * (2**attempt) if sleep_seconds else 1.0 + attempt))
        try:
            response = session.get(jina_url(url), timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            continue
        return {"status": "ok", "markdown": response.text}
    return {"status": "request_error", "error": last_error or "request failed"}


def parse_jina_get_record(markdown: str, article_id: str) -> Optional[Dict[str, Any]]:
    if "Markdown Content:" not in markdown:
        return None

    if "### Dublin Core Metadata" in markdown:
        section = markdown.split("### Dublin Core Metadata", 1)[1]
    else:
        section = markdown.split("Markdown Content:", 1)[1]
    section = section.split("\n*   [Identify]", 1)[0]
    section = section.split("\n## [About", 1)[0]

    record_id = ""
    record_match = re.search(r"OAI Record:\s*([^\n]+)", markdown)
    if record_match:
        record_id = record_match.group(1).strip()

    title = ""
    creators: List[str] = []
    identifiers: List[str] = []
    publisher = ""
    source = ""
    resource_type = ""
    year: Optional[int] = None

    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Title ") and not title:
            title = line.removeprefix("Title ").strip()
        elif line.startswith("Author or Creator "):
            creators.append(line.removeprefix("Author or Creator ").strip())
        elif line.startswith("Publisher ") and not publisher:
            publisher = line.removeprefix("Publisher ").strip()
        elif line.startswith("Date ") and year is None:
            match = re.search(r"(19[0-9]{2}|20[0-3][0-9])", line)
            if match:
                year = int(match.group(1))
        elif line.startswith("Resource Type ") and not resource_type:
            resource_type = line.removeprefix("Resource Type ").strip()
        elif line.startswith("Resource Identifier "):
            identifiers.append(line.removeprefix("Resource Identifier ").strip())
        elif line.startswith("Source ") and not source:
            source = line.removeprefix("Source ").strip()

    doi = ""
    url = ""
    for identifier in identifiers:
        normalized = normalize_doi(identifier)
        if normalized.startswith("10."):
            doi = normalized
        if identifier.startswith("http"):
            url = identifier

    return {
        "oai_identifier": record_id or f"{OAI_ID_PREFIX}{article_id}",
        "oai_datestamp": "",
        "article_id": article_id,
        "title": title,
        "creators": creators,
        "identifiers": identifiers,
        "doi": doi,
        "url": url,
        "year": year,
        "publisher": publisher,
        "source": source,
        "type": resource_type,
    }


def get_record_via_jina(
    session: requests.Session,
    slug: str,
    article_id: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
) -> Dict[str, Any]:
    identifier = f"{OAI_ID_PREFIX}{article_id}"
    bases = []
    if slug:
        bases.append(f"{OAI_BASE}{slug}/")
    bases.append(OAI_BASE)

    errors = []
    for base in bases:
        url = f"{base}?verb=GetRecord&metadataPrefix=oai_dc&identifier={identifier}"
        result = request_jina_markdown(session, url, timeout, retries, sleep_seconds)
        if result.get("status") != "ok":
            errors.append({"endpoint": jina_url(url), "status": result.get("status"), "error": result.get("error")})
            continue
        record = parse_jina_get_record(result.get("markdown") or "", article_id)
        if record:
            return {"status": "ok", "items": [record], "endpoint": jina_url(url), "fetch_mode": "jina"}
        errors.append({"endpoint": jina_url(url), "status": "parse_error"})
    return {"status": "error", "error": "Jina response did not include an OAI Dublin Core record", "errors": errors}


def get_record(
    session: requests.Session,
    slug: str,
    article_id: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    fetch_mode: str,
) -> Dict[str, Any]:
    if fetch_mode == "jina":
        return get_record_via_jina(session, slug, article_id, timeout, retries, sleep_seconds)

    identifier = f"{OAI_ID_PREFIX}{article_id}"
    bases = []
    if slug:
        bases.append(f"{OAI_BASE}{slug}/")
    bases.append(OAI_BASE)

    errors = []
    for base in bases:
        result = request_oai(
            session,
            base,
            {"verb": "GetRecord", "metadataPrefix": "oai_dc", "identifier": identifier},
            timeout,
            retries,
            sleep_seconds,
        )
        if result.get("status") == "ok":
            record = result["root"].find(".//oai:GetRecord/oai:record", OAI_NS)
            if record is not None:
                return {"status": "ok", "items": [record_from_element(record)], "endpoint": base}
            errors.append({"endpoint": base, "status": "empty"})
            continue
        errors.append({"endpoint": base, "status": result.get("status"), "error": result.get("error"), "code": result.get("code")})
    if fetch_mode == "auto":
        jina_result = get_record_via_jina(session, slug, article_id, timeout, retries, sleep_seconds)
        if jina_result.get("status") == "ok":
            return jina_result
        errors.append({"endpoint": "jina", "status": jina_result.get("status"), "error": jina_result.get("error")})
    return {"status": "error", "errors": errors}


def list_records_for_slug(
    session: requests.Session,
    slug: str,
    timeout: float,
    retries: int,
    sleep_seconds: float,
    max_records: int,
    max_pages: int,
) -> Dict[str, Any]:
    base = f"{OAI_BASE}{slug}/"
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
    records: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for _ in range(max_pages):
        result = request_oai(session, base, params, timeout, retries, sleep_seconds)
        if result.get("status") != "ok":
            errors.append({"endpoint": base, "status": result.get("status"), "error": result.get("error"), "code": result.get("code")})
            break
        root = result["root"]
        for record in root.findall(".//oai:ListRecords/oai:record", OAI_NS):
            records.append(record_from_element(record))
            if len(records) >= max_records:
                return {"status": "ok", "items": records, "endpoint": base, "truncated": True}
        token = root.findtext(".//oai:resumptionToken", default="", namespaces=OAI_NS)
        if not token:
            return {"status": "ok", "items": records, "endpoint": base, "truncated": False}
        params = {"verb": "ListRecords", "resumptionToken": token}
    return {"status": "ok" if records else "error", "items": records, "endpoint": base, "errors": errors, "truncated": bool(records)}


def author_surnames(creators: Sequence[str]) -> List[str]:
    surnames: List[str] = []
    for creator in creators:
        name = creator.split(",", 1)[0] if "," in creator else creator
        name_tokens = tokens(name)
        if name_tokens:
            surnames.append(name_tokens[-1])
    return surnames


def score_candidate(record: Dict[str, Any], context: str) -> CandidateScore:
    title = record.get("title") or ""
    title_token_count = len(tokens(title))
    coverage = title_coverage(title, context)
    similarity = title_similarity(title, context)
    author_ratio = author_coverage(author_surnames(record.get("creators") or []), context)
    year = record.get("year")
    has_year_match = bool(year and year in context_years(context))
    confidence = (
        (coverage * 0.55)
        + (similarity * 0.20)
        + (min(author_ratio, 1.0) * 0.15)
        + ((1.0 if has_year_match else 0.0) * 0.10)
    )

    if similarity >= 0.98 and (has_year_match or author_ratio >= 0.34):
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.88 and (has_year_match or author_ratio >= 0.34):
        status = "strong"
    elif title_token_count >= 8 and coverage >= 0.78 and author_ratio >= 0.34 and has_year_match:
        status = "strong"
    elif title_token_count >= 6 and coverage >= 0.68 and (has_year_match or author_ratio >= 0.34):
        status = "possible"
    elif title_token_count >= 8 and coverage >= 0.58 and author_ratio >= 0.34:
        status = "possible"
    else:
        status = "no_match"

    return CandidateScore(
        match_status=status,
        confidence=round(confidence, 4),
        title_coverage=round(coverage, 4),
        title_similarity=round(similarity, 4),
        title_token_count=title_token_count,
        author_coverage=round(author_ratio, 4),
        year_match=has_year_match,
        candidate=record,
    )


def best_candidate(items: List[Dict[str, Any]], row: Dict[str, Any]) -> Optional[CandidateScore]:
    if not items:
        return None
    exact_id = row.get("dergipark_article_id")
    exact_candidates = [item for item in items if exact_id and item.get("article_id") == exact_id]
    scored = [score_candidate(item, row.get("context") or "") for item in (exact_candidates or items)]
    if not scored:
        return None
    status_rank = {"strong": 2, "possible": 1, "no_match": 0}
    best = max(scored, key=lambda item: (status_rank[item.match_status], item.confidence))
    if exact_candidates and best.match_status == "no_match":
        best.match_status = "strong"
        best.confidence = max(best.confidence, 0.95)
    return best


def run_row(
    session: requests.Session,
    row: Dict[str, Any],
    cache: Dict[str, Dict[str, Any]],
    timeout: float,
    retries: int,
    sleep_seconds: float,
    max_records_per_slug: int,
    max_pages_per_slug: int,
    fetch_mode: str,
) -> Dict[str, Any]:
    if row["query_mode"] == "get_record":
        key = f"get:{row['dergipark_slug']}:{row['dergipark_article_id']}"
        if key not in cache:
            cache[key] = get_record(
                session,
                row["dergipark_slug"],
                row["dergipark_article_id"],
                timeout,
                retries,
                sleep_seconds,
                fetch_mode,
            )
        return cache[key]
    if row["query_mode"] == "list_records":
        key = f"list:{row['dergipark_slug']}"
        if key not in cache:
            cache[key] = list_records_for_slug(
                session,
                row["dergipark_slug"],
                timeout,
                retries,
                sleep_seconds,
                max_records_per_slug,
                max_pages_per_slug,
            )
        return cache[key]
    return {"status": "unqueryable", "items": []}


def output_row(row: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    base = {
        "sample_index": row["sample_index"],
        "publication_id": row["publication_id"],
        "reference_id": row["reference_id"],
        "reference_order": row["reference_order"],
        "query_mode": row["query_mode"],
        "dergipark_slug": row["dergipark_slug"],
        "dergipark_article_id": row["dergipark_article_id"],
        "dergipark_issue_id": row["dergipark_issue_id"],
        "dergipark_article_file_id": row["dergipark_article_file_id"],
        "dergipark_status": "not_checked",
        "oai_identifier": "",
        "dergipark_doi": "",
        "dergipark_title": "",
        "dergipark_year": "",
        "dergipark_source": "",
        "dergipark_url": "",
        "confidence": "",
        "title_coverage": "",
        "title_similarity": "",
        "title_token_count": "",
        "author_coverage": "",
        "year_match": "",
        "context": row["context"],
    }
    if result.get("status") == "unqueryable":
        base["dergipark_status"] = row["query_mode"]
        return base
    if result.get("status") == "not_checked":
        base["dergipark_status"] = "not_checked"
        return base
    if result.get("status") != "ok":
        base["dergipark_status"] = "request_error"
        return base
    score = best_candidate(result.get("items") or [], row)
    if not score:
        base["dergipark_status"] = "no_match"
        return base
    candidate = score.candidate
    base.update(
        {
            "dergipark_status": score.match_status,
            "oai_identifier": candidate.get("oai_identifier") or "",
            "dergipark_doi": candidate.get("doi") or "",
            "dergipark_title": candidate.get("title") or "",
            "dergipark_year": candidate.get("year") or "",
            "dergipark_source": candidate.get("source") or candidate.get("publisher") or "",
            "dergipark_url": candidate.get("url") or "",
            "confidence": score.confidence,
            "title_coverage": score.title_coverage,
            "title_similarity": score.title_similarity,
            "title_token_count": score.title_token_count,
            "author_coverage": score.author_coverage,
            "year_match": score.year_match,
        }
    )
    return base


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "query_mode",
        "dergipark_slug",
        "dergipark_article_id",
        "dergipark_issue_id",
        "dergipark_article_file_id",
        "dergipark_status",
        "oai_identifier",
        "dergipark_doi",
        "dergipark_title",
        "dergipark_year",
        "dergipark_source",
        "dergipark_url",
        "confidence",
        "title_coverage",
        "title_similarity",
        "title_token_count",
        "author_coverage",
        "year_match",
        "context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def build_summary(base_found: int, all_count: int, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    strong = sum(1 for row in rows if row["dergipark_status"] == "strong")
    possible = sum(1 for row in rows if row["dergipark_status"] == "possible")
    no_match = sum(1 for row in rows if row["dergipark_status"] == "no_match")
    request_error = sum(1 for row in rows if row["dergipark_status"] == "request_error")
    not_checked = sum(1 for row in rows if row["dergipark_status"] == "not_checked")
    queryable = sum(1 for row in rows if row["query_mode"] in {"get_record", "list_records"})
    article_id_targets = sum(1 for row in rows if row["query_mode"] == "get_record")
    slug_targets = sum(1 for row in rows if row["query_mode"] == "list_records")
    file_only = sum(1 for row in rows if row["query_mode"] == "file_url_only")
    no_filter = sum(1 for row in rows if row["query_mode"] == "no_oai_filter")
    experiment7_strict = base_found + strong
    experiment7_broad = base_found + strong + possible
    return {
        "experiment_label": "Deney 7 - DergiPark OAI-PMH direct filter",
        "sampled_references": all_count,
        "base_found_before_dergipark": base_found,
        "base_found_before_dergipark_rate_percent": percent(base_found, all_count),
        "dergipark_target_total": len(rows),
        "dergipark_oai_queryable": queryable,
        "dergipark_get_record_targets": article_id_targets,
        "dergipark_list_records_targets": slug_targets,
        "dergipark_file_url_only": file_only,
        "dergipark_no_oai_filter": no_filter,
        "dergipark_strong_matches": strong,
        "dergipark_possible_matches": possible,
        "dergipark_no_match": no_match,
        "dergipark_request_errors": request_error,
        "dergipark_not_checked": not_checked,
        "experiment7_strict_found": experiment7_strict,
        "experiment7_strict_found_rate_percent": percent(experiment7_strict, all_count),
        "experiment7_broad_found": experiment7_broad,
        "experiment7_broad_found_rate_percent": percent(experiment7_broad, all_count),
        "complete": request_error == 0 and not_checked == 0,
    }


def write_report(path: Path, summary: Dict[str, Any]) -> None:
    status = "tamamlandi" if summary["complete"] else "partial / network blocked"
    lines = [
        "# DergiPark OAI-PMH Deney 7",
        "",
        f"- Durum: {status}",
        f"- Toplam orneklem: {summary['sampled_references']}",
        f"- DergiPark oncesi baz bulunan: {summary['base_found_before_dergipark']} ({summary['base_found_before_dergipark_rate_percent']}%)",
        f"- DergiPark hedef kalan: {summary['dergipark_target_total']}",
        f"- OAI ile sorgulanabilir hedef: {summary['dergipark_oai_queryable']}",
        f"- GetRecord hedefi: {summary['dergipark_get_record_targets']}",
        f"- ListRecords hedefi: {summary['dergipark_list_records_targets']}",
        f"- Sadece article-file URL: {summary['dergipark_file_url_only']}",
        f"- OAI filtresi olmayan: {summary['dergipark_no_oai_filter']}",
        f"- Strong DergiPark eslesme: {summary['dergipark_strong_matches']}",
        f"- Possible DergiPark eslesme: {summary['dergipark_possible_matches']}",
        f"- Request error: {summary['dergipark_request_errors']}",
        f"- Kontrol edilmeyen: {summary['dergipark_not_checked']}",
        "",
        "## Deney 7 Sonuc",
        "",
        f"- Strict DergiPark ekli: {summary['experiment7_strict_found']} ({summary['experiment7_strict_found_rate_percent']}%)",
        f"- Broad DergiPark ekli: {summary['experiment7_broad_found']} ({summary['experiment7_broad_found_rate_percent']}%)",
        "",
        "Not: OAI-PMH title search API degildir; burada sadece identifier/slug ile filtrelenebilen DergiPark kayitlari denenir.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use DergiPark OAI-PMH for records not matched after experiment 6.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument(
        "--stq-csv",
        default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"),
        type=Path,
    )
    parser.add_argument(
        "--doi-fallback-csv",
        default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"),
        type=Path,
    )
    parser.add_argument(
        "--no-doi-fallback-csv",
        default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"),
        type=Path,
    )
    parser.add_argument(
        "--openalex-csv",
        default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.csv"),
        type=Path,
    )
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback"), type=Path)
    parser.add_argument("--timeout", default=10.0, type=float)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--sleep", default=0.2, type=float)
    parser.add_argument("--max-records-per-slug", default=500, type=int)
    parser.add_argument("--max-pages-per-slug", default=5, type=int)
    parser.add_argument("--max-requests", default=None, type=int)
    parser.add_argument("--save-every", default=10, type=int)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--fetch-mode", default="auto", choices=["direct", "auto", "jina"])
    parser.add_argument("--retry-errors", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.out_dir / "dergipark_oai_cache.json"
    cache = load_cache(cache_path)
    if args.retry_errors:
        retryable_keys = [key for key, value in cache.items() if value.get("status") in {"error", "request_error"}]
        for key in retryable_keys:
            del cache[key]
        if retryable_keys:
            save_cache(cache_path, cache)
            print(f"removed {len(retryable_keys)} retryable DergiPark cache errors", flush=True)

    sample_rows = read_csv(args.sample_csv)
    stq_rows = read_csv(args.stq_csv)
    doi_fallback_rows = read_csv(args.doi_fallback_csv)
    no_doi_fallback_rows = read_csv(args.no_doi_fallback_csv)
    openalex_rows = read_csv(args.openalex_csv)
    base_found = build_base_found(sample_rows, stq_rows, doi_fallback_rows, no_doi_fallback_rows, openalex_rows)
    rows = target_rows(sample_rows, base_found)

    session = make_session()
    queryable_rows = [row for row in rows if row["query_mode"] in {"get_record", "list_records"}]
    if args.max_requests is not None:
        queryable_rows = queryable_rows[: args.max_requests]
    print(
        f"target={len(rows)} base_found={len(base_found)} queryable={len([r for r in rows if r['query_mode'] in {'get_record', 'list_records'}])} run={len(queryable_rows)} cached={len(cache)}",
        flush=True,
    )

    if not args.metadata_only:
        dirty = False
        for index, row in enumerate(queryable_rows, start=1):
            run_row(
                session,
                row,
                cache,
                args.timeout,
                args.retries,
                args.sleep,
                args.max_records_per_slug,
                args.max_pages_per_slug,
                args.fetch_mode,
            )
            dirty = True
            if index % args.save_every == 0:
                save_cache(cache_path, cache)
                dirty = False
                print(f"cached {index}/{len(queryable_rows)} DergiPark OAI requests", flush=True)
        if dirty:
            save_cache(cache_path, cache)

    outputs: List[Dict[str, Any]] = []
    for row in rows:
        result = {"status": "unqueryable", "items": []}
        if row["query_mode"] == "get_record":
            result = cache.get(f"get:{row['dergipark_slug']}:{row['dergipark_article_id']}", {"status": "not_checked", "items": []})
        elif row["query_mode"] == "list_records":
            result = cache.get(f"list:{row['dergipark_slug']}", {"status": "not_checked", "items": []})
        outputs.append(output_row(row, result))

    summary = build_summary(len(base_found), len(sample_rows), outputs)
    write_csv(args.out_dir / "dergipark_oai_matches.csv", outputs)
    write_jsonl(args.out_dir / "dergipark_oai_matches.jsonl", outputs)
    write_json(args.out_dir / "dergipark_oai_summary.json", summary)
    write_report(args.out_dir / "dergipark_oai_report_tr.md", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
