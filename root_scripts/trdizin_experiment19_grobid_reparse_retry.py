#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from trdizin_crossref_bibliographic_fallback import (
    best_candidate as best_crossref_candidate,
    fill_missing_cache as fill_crossref_search_cache,
    first_text as crossref_first_text,
    issued_year as crossref_issued_year,
)
from trdizin_experiment12_trdizin_target_publication import (
    CONTACT_EMAIL,
    fetch_crossref_doi,
    load_cache,
    normalize_doi,
    percent,
    read_csv,
    save_cache,
    write_csv,
    write_json,
    write_jsonl,
)
from trdizin_experiment13_trdizin_title_search import (
    fetch_search_key,
    fill_missing_cache as fill_trdizin_search_cache,
    query_variants as trdizin_query_variants,
    score_candidate as score_trdizin_candidate,
)
from trdizin_experiments14_18_resolvers import (
    current_base_found,
    found_after_experiment14,
    found_after_experiment15,
    found_after_experiment16,
    found_after_experiment18,
    remaining_sample_rows,
    write_report,
)
from trdizin_openalex_fallback import (
    best_candidate as best_openalex_candidate,
    fill_missing_cache as fill_openalex_cache,
)
from trdizin_remaining_after_experiment10_stats import PATTERNS, classify_remaining


WORD_RE = re.compile(r"[a-z0-9]+")
YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-3][0-9])\b")
DEFAULT_TARGET_CATEGORIES = {
    "journal_like_left",
    "other",
    "hidden_doi",
    "dergipark_file",
    "conference",
}


@dataclass
class GrobidReference:
    publication_id: str
    grobid_index: int
    raw_reference: str
    title: str
    journal: str
    year: str
    authors: str
    author_surnames: List[str]
    doi: str
    volume: str
    issue: str
    pages: str


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


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("ı", "i")
    return " ".join(WORD_RE.findall(value))


def tokens(value: str) -> List[str]:
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "from",
        "into",
        "using",
        "based",
        "study",
        "analysis",
        "review",
        "article",
        "journal",
        "dergisi",
        "bir",
        "ve",
        "ile",
        "icin",
        "uzerine",
    }
    return [token for token in normalize_text(value).split() if len(token) > 2 and token not in stopwords]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def first_descendant(element: ET.Element, tag: str, attr: Optional[str] = None, value: Optional[str] = None) -> Optional[ET.Element]:
    for child in element.iter():
        if local_name(child.tag) != tag:
            continue
        if attr is not None and child.get(attr) != value:
            continue
        return child
    return None


def direct_children(element: ET.Element, tag: str) -> List[ET.Element]:
    return [child for child in list(element) if local_name(child.tag) == tag]


def first_direct_child(element: ET.Element, tag: str) -> Optional[ET.Element]:
    children = direct_children(element, tag)
    return children[0] if children else None


def title_with_level(element: ET.Element, level: str) -> str:
    node = first_descendant(element, "title", "level", level)
    return element_text(node)


def year_from_text(value: str) -> str:
    years = [int(year) for year in YEAR_RE.findall(value or "")]
    if not years:
        return ""
    return str(max(years))


def date_year(bibl: ET.Element) -> str:
    for node in bibl.iter():
        if local_name(node.tag) != "date":
            continue
        candidates = [node.get("when") or "", element_text(node)]
        for candidate in candidates:
            year = year_from_text(candidate)
            if year:
                return year
    return ""


def author_values(parent: Optional[ET.Element]) -> Tuple[str, List[str]]:
    if parent is None:
        return "", []
    names: List[str] = []
    surnames: List[str] = []
    for author in parent.iter():
        if local_name(author.tag) != "author":
            continue
        pers = first_descendant(author, "persName")
        if pers is None:
            text = element_text(author)
            if text:
                names.append(text)
                parts = tokens(text)
                if parts:
                    surnames.append(parts[-1])
            continue
        surname = element_text(first_descendant(pers, "surname"))
        forenames = [element_text(node) for node in pers.iter() if local_name(node.tag) == "forename"]
        name = " ".join(piece for piece in [*forenames, surname] if piece).strip() or element_text(pers)
        if name:
            names.append(name)
        surname_tokens = tokens(surname or name)
        if surname_tokens:
            surnames.append(surname_tokens[-1])
    return "; ".join(names), surnames


def bibl_scope(bibl: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for node in bibl.iter():
        if local_name(node.tag) != "biblScope":
            continue
        unit = (node.get("unit") or node.get("type") or "").lower()
        if unit not in wanted:
            continue
        start = node.get("from") or ""
        end = node.get("to") or ""
        if start and end and start != end:
            return f"{start}-{end}"
        return start or element_text(node)
    return ""


def doi_from_bibl(bibl: ET.Element) -> str:
    for node in bibl.iter():
        if local_name(node.tag) == "idno" and (node.get("type") or "").lower() == "doi":
            doi = normalize_doi(element_text(node))
            if doi.startswith("10."):
                return doi
    raw = ""
    for node in bibl.iter():
        if local_name(node.tag) == "note" and node.get("type") == "raw_reference":
            raw = element_text(node)
            break
    match = re.search(r"(10\.\d{4,9}\s*/\s*[^\s\"'<>]+)", raw, re.IGNORECASE)
    return normalize_doi(match.group(1)) if match else ""


def parse_grobid_tei(path: Path, publication_id: str) -> List[GrobidReference]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    refs: List[GrobidReference] = []
    for index, bibl in enumerate((node for node in root.iter() if local_name(node.tag) == "biblStruct"), start=1):
        analytic = first_direct_child(bibl, "analytic")
        monogr = first_direct_child(bibl, "monogr")
        raw = ""
        for node in bibl.iter():
            if local_name(node.tag) == "note" and node.get("type") == "raw_reference":
                raw = element_text(node)
                break
        article_title = title_with_level(analytic, "a") if analytic is not None else ""
        monograph_title = title_with_level(monogr, "m") if monogr is not None else ""
        journal = title_with_level(monogr, "j") if monogr is not None else ""
        title = article_title or monograph_title
        authors, surnames = author_values(analytic)
        if not authors:
            authors, surnames = author_values(monogr)
        refs.append(
            GrobidReference(
                publication_id=publication_id,
                grobid_index=index,
                raw_reference=raw,
                title=title,
                journal=journal,
                year=date_year(bibl) or year_from_text(raw),
                authors=authors,
                author_surnames=surnames,
                doi=doi_from_bibl(bibl),
                volume=bibl_scope(bibl, "volume", "vol"),
                issue=bibl_scope(bibl, "issue"),
                pages=bibl_scope(bibl, "page", "pp"),
            )
        )
    return refs


def find_tei_path(publication_id: str, tei_dirs: Sequence[Path]) -> Optional[Path]:
    for directory in tei_dirs:
        path = directory / f"{publication_id}.tei.xml"
        if path.exists():
            return path
    return None


def load_match_report(path: Path) -> Dict[Tuple[str, int], Dict[str, Any]]:
    mapping: Dict[Tuple[str, int], Dict[str, Any]] = {}
    if not path.exists():
        return mapping
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            doc = json.loads(line)
            publication_id = str(doc.get("publication_id") or "")
            for decision in doc.get("decisions") or []:
                try:
                    order = int(decision.get("trdizin_order"))
                except (TypeError, ValueError):
                    continue
                mapping[(publication_id, order)] = decision
    return mapping


def similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def token_coverage(needle: str, haystack: str) -> float:
    needle_tokens = tokens(needle)
    haystack_tokens = set(tokens(haystack))
    if not needle_tokens:
        return 0.0
    return len([token for token in needle_tokens if token in haystack_tokens]) / len(needle_tokens)


def title_pair_score(candidate_title: str, grobid_title: str) -> Tuple[float, float]:
    return round(similarity(candidate_title, grobid_title), 4), round(
        max(token_coverage(candidate_title, grobid_title), token_coverage(grobid_title, candidate_title)),
        4,
    )


def title_pair_supported(candidate_title: str, grobid_title: str) -> bool:
    sim, cov = title_pair_score(candidate_title, grobid_title)
    token_count = min(len(tokens(candidate_title)), len(tokens(grobid_title)))
    if token_count < 4:
        return False
    return sim >= 0.88 or cov >= 0.86


def align_grobid_reference(
    row: Dict[str, str],
    refs: Sequence[GrobidReference],
    decision: Optional[Dict[str, Any]],
    min_alignment_score: float,
) -> Tuple[Optional[GrobidReference], float, str]:
    if decision and str(decision.get("grobid_index") or "").isdigit():
        index = int(decision["grobid_index"])
        if 1 <= index <= len(refs):
            score = float(decision.get("score") or 0.0)
            if score >= min_alignment_score:
                return refs[index - 1], round(score, 4), "match_report"
    if not refs:
        return None, 0.0, "missing"
    context = row.get("context") or ""
    scored = [(similarity(ref.raw_reference, context), ref) for ref in refs if ref.raw_reference]
    if not scored:
        return None, 0.0, "missing_raw"
    score, ref = max(scored, key=lambda item: item[0])
    if score >= min_alignment_score:
        return ref, round(score, 4), "raw_similarity"
    return None, round(score, 4), "low_alignment"


def build_crossref_query(grobid: GrobidReference, max_chars: int) -> str:
    first_author = grobid.author_surnames[0] if grobid.author_surnames else ""
    pieces = [grobid.title, first_author, grobid.year, grobid.journal]
    query = " ".join(piece for piece in pieces if piece)
    query = " ".join(query.split())
    if len(query) <= max_chars:
        return query
    return query[:max_chars].rsplit(" ", 1)[0].strip()


def build_openalex_query(grobid: GrobidReference, max_chars: int) -> str:
    first_author = grobid.author_surnames[0] if grobid.author_surnames else ""
    pieces = [grobid.title, grobid.year, first_author, grobid.journal]
    query = " ".join(piece for piece in pieces if piece)
    query = " ".join(query.split())
    if len(query) <= max_chars:
        return query
    return query[:max_chars].rsplit(" ", 1)[0].strip()


def make_target_row(row: Dict[str, str], grobid: GrobidReference, alignment_score: float, alignment_source: str) -> Dict[str, Any]:
    target = {
        "sample_index": row.get("sample_index", ""),
        "publication_id": row.get("publication_id", ""),
        "reference_id": row.get("reference_id", ""),
        "reference_order": row.get("reference_order", ""),
        "exclusive_category": row.get("exclusive_category", ""),
        "alignment_score": alignment_score,
        "alignment_source": alignment_source,
        "grobid_index": grobid.grobid_index,
        "grobid_doi": grobid.doi,
        "grobid_title": grobid.title,
        "grobid_journal": grobid.journal,
        "grobid_year": grobid.year,
        "grobid_authors": grobid.authors,
        "grobid_volume": grobid.volume,
        "grobid_issue": grobid.issue,
        "grobid_pages": grobid.pages,
        "grobid_raw_reference": grobid.raw_reference,
        "context": row.get("context", ""),
    }
    target["crossref_query"] = build_crossref_query(grobid, 260)
    target["openalex_key"] = f"search:{build_openalex_query(grobid, 220)}"
    variants = trdizin_query_variants(grobid.title, grobid.year, 2) if grobid.title and grobid.year else []
    target["trdizin_query_modes"] = [item[0] for item in variants]
    target["trdizin_query_keys"] = [item[1] for item in variants]
    target["trdizin_queries"] = [item[2] for item in variants]
    return target


def target_is_searchable(row: Dict[str, Any], include_categories: set[str], include_doi_unlikely: bool) -> bool:
    if row.get("grobid_doi"):
        return True
    if not row.get("grobid_title") or not row.get("grobid_year"):
        return False
    if len(tokens(row.get("grobid_title") or "")) < 4:
        return False
    category = row.get("exclusive_category") or ""
    return include_doi_unlikely or category in include_categories


def fill_crossref_doi_cache(
    cache_path: Path,
    cache: Dict[str, Dict[str, Any]],
    dois: Sequence[str],
    workers: int,
    timeout: float,
    max_start_rate: float,
    save_every: int,
) -> None:
    missing = [doi for doi in sorted(set(dois)) if doi and doi not in cache]
    if not missing:
        return
    limiter = RateLimiter(max_start_rate)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_crossref_doi, doi, timeout, limiter): doi for doi in missing}
        for future in as_completed(futures):
            doi, result = future.result()
            cache[doi] = result
            completed += 1
            if completed % save_every == 0:
                save_cache(cache_path, cache)
                print(f"cached {completed}/{len(missing)} GROBID DOI checks", flush=True)
    save_cache(cache_path, cache)


def openalex_candidate_title(candidate: Dict[str, Any]) -> str:
    return str(candidate.get("title") or candidate.get("display_name") or "")


def evaluate_target(
    target: Dict[str, Any],
    doi_cache: Dict[str, Dict[str, Any]],
    crossref_cache: Dict[str, Dict[str, Any]],
    trdizin_cache: Dict[str, Dict[str, Any]],
    openalex_cache: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    output = {
        **{key: target.get(key, "") for key in [
            "sample_index",
            "publication_id",
            "reference_id",
            "reference_order",
            "exclusive_category",
            "alignment_score",
            "alignment_source",
            "grobid_index",
            "grobid_doi",
            "grobid_title",
            "grobid_journal",
            "grobid_year",
            "grobid_authors",
            "grobid_volume",
            "grobid_issue",
            "grobid_pages",
        ]},
        "experiment19_status": "no_match",
        "resolver": "",
        "matched_id": "",
        "matched_doi": "",
        "matched_title": "",
        "matched_year": "",
        "matched_venue": "",
        "confidence": "",
        "title_similarity": "",
        "title_coverage": "",
        "title_token_count": "",
        "author_coverage": "",
        "year_match": "",
        "title_pair_similarity": "",
        "title_pair_coverage": "",
        "query": "",
        "context": target.get("context", ""),
    }

    doi = target.get("grobid_doi") or ""
    if doi:
        result = doi_cache.get(doi) or {}
        if result.get("status") == "ok":
            message = result.get("message") if isinstance(result.get("message"), dict) else {}
            matched_title = crossref_first_text(message.get("title")) or ""
            output.update(
                {
                    "experiment19_status": "strong",
                    "resolver": "grobid_doi_crossref",
                    "matched_doi": result.get("doi") or doi,
                    "matched_title": matched_title,
                    "matched_year": str(crossref_issued_year(message) or ""),
                    "matched_venue": crossref_first_text(message.get("container-title")) or "",
                    "query": doi,
                }
            )
            return output

    crossref_query = target.get("crossref_query") or ""
    crossref_result = crossref_cache.get(crossref_query) if crossref_query else None
    if crossref_result and crossref_result.get("status") == "ok":
        score = best_crossref_candidate(crossref_result.get("items") or [], target.get("context") or "")
        if score:
            candidate = score.candidate
            matched_title = crossref_first_text(candidate.get("title")) or ""
            pair_sim, pair_cov = title_pair_score(matched_title, target.get("grobid_title") or "")
            status = score.match_status
            if status == "strong" and not title_pair_supported(matched_title, target.get("grobid_title") or ""):
                status = "possible"
            output.update(
                {
                    "experiment19_status": status,
                    "resolver": "grobid_crossref_bibliographic",
                    "matched_doi": normalize_doi(str(candidate.get("DOI") or "")),
                    "matched_title": matched_title,
                    "matched_year": str(crossref_issued_year(candidate) or ""),
                    "matched_venue": str(candidate.get("publisher") or ""),
                    "confidence": score.confidence,
                    "title_similarity": score.title_similarity,
                    "title_coverage": score.title_coverage,
                    "title_token_count": score.title_token_count,
                    "author_coverage": score.author_coverage,
                    "year_match": score.year_match,
                    "title_pair_similarity": pair_sim,
                    "title_pair_coverage": pair_cov,
                    "query": crossref_query,
                }
            )
            if status == "strong":
                return output

    trdizin_scores: List[Tuple[Dict[str, Any], str]] = []
    for key, query in zip(target.get("trdizin_query_keys") or [], target.get("trdizin_queries") or []):
        result = trdizin_cache.get(key)
        if not result or result.get("status") != "ok":
            continue
        for candidate in result.get("items") or []:
            if isinstance(candidate, dict):
                trdizin_scores.append((score_trdizin_candidate(candidate, {
                    "parsed_title": target.get("grobid_title") or "",
                    "parsed_journal": target.get("grobid_journal") or "",
                    "parsed_year": target.get("grobid_year") or "",
                    "context": target.get("context") or "",
                    "publication_id": target.get("publication_id") or "",
                }), query))
    if trdizin_scores:
        rank = {"strong": 2, "possible": 1, "no_match": 0}
        score, query = max(
            trdizin_scores,
            key=lambda item: (
                rank[item[0]["status"]],
                item[0]["confidence"],
                item[0]["title_similarity"],
                item[0]["title_coverage"],
            ),
        )
        candidate = score["candidate"]
        status = score["status"]
        pair_sim, pair_cov = title_pair_score(candidate.get("title") or "", target.get("grobid_title") or "")
        if status == "strong" and not title_pair_supported(candidate.get("title") or "", target.get("grobid_title") or ""):
            status = "possible"
        if rank[status] > rank.get(str(output.get("experiment19_status")), 0):
            output.update(
                {
                    "experiment19_status": status,
                    "resolver": "grobid_trdizin_title_search",
                    "matched_id": candidate.get("trdizin_id") or "",
                    "matched_doi": candidate.get("doi") or "",
                    "matched_title": candidate.get("title") or "",
                    "matched_year": candidate.get("year") or "",
                    "matched_venue": candidate.get("journal") or "",
                    "confidence": score["confidence"],
                    "title_similarity": score["title_similarity"],
                    "title_coverage": score["title_coverage"],
                    "title_token_count": score["title_token_count"],
                    "author_coverage": score["author_coverage"],
                    "year_match": score["year_match"],
                    "title_pair_similarity": pair_sim,
                    "title_pair_coverage": pair_cov,
                    "query": query,
                }
            )
            if status == "strong":
                return output

    openalex_key = target.get("openalex_key") or ""
    openalex_result = openalex_cache.get(openalex_key) if openalex_key else None
    if openalex_result and openalex_result.get("status") == "ok":
        score = best_openalex_candidate(openalex_result.get("items") or [], target.get("context") or "")
        if score:
            candidate = score.candidate
            matched_title = openalex_candidate_title(candidate)
            pair_sim, pair_cov = title_pair_score(matched_title, target.get("grobid_title") or "")
            status = score.match_status
            if status == "strong" and not title_pair_supported(matched_title, target.get("grobid_title") or ""):
                status = "possible"
            rank = {"strong": 2, "possible": 1, "no_match": 0}
            if rank[status] > rank.get(str(output.get("experiment19_status")), 0):
                output.update(
                    {
                        "experiment19_status": status,
                        "resolver": "grobid_openalex",
                        "matched_id": candidate.get("id") or "",
                        "matched_doi": candidate.get("doi") or "",
                        "matched_title": matched_title,
                        "matched_year": str(candidate.get("publication_year") or ""),
                        "matched_venue": candidate.get("source_title") or "",
                        "confidence": score.confidence,
                        "title_similarity": score.title_similarity,
                        "title_coverage": score.title_coverage,
                        "title_token_count": score.title_token_count,
                        "author_coverage": score.author_coverage,
                        "year_match": score.year_match,
                        "title_pair_similarity": pair_sim,
                        "title_pair_coverage": pair_cov,
                        "query": openalex_key.removeprefix("search:"),
                    }
                )

    return output


def check_grobid_alive(grobid_url: str, timeout: float) -> bool:
    if not grobid_url:
        return False
    try:
        response = requests.get(f"{grobid_url.rstrip('/')}/api/isalive", timeout=timeout)
        return response.status_code == 200 and response.text.strip().lower() == "true"
    except requests.RequestException:
        return False


def write_remaining_after_experiment19(args: argparse.Namespace, sample_rows: List[Dict[str, str]], found: set[str]) -> Dict[str, Any]:
    out_dir = args.out_dir / "remaining_after_experiment19"
    out_dir.mkdir(parents=True, exist_ok=True)
    remaining_rows = remaining_sample_rows(sample_rows, found)
    classified = classify_remaining(remaining_rows)
    total = len(sample_rows)
    remaining = len(classified)
    exclusive = []
    labels = {
        "hidden_doi": "Gizli DOI",
        "dergipark_file": "DergiPark article-file",
        "thesis": "Tez",
        "report_policy_legal": "Rapor / mevzuat / hukuk",
        "url_web": "Web / haber / video",
        "conference": "Konferans / bildiri",
        "book_or_chapter": "Kitap / kitap bolumu",
        "journal_like_left": "Journal-like kalan",
        "other": "Diger / zayif parse",
    }
    for category in labels:
        count = sum(1 for row in classified if row["exclusive_category"] == category)
        exclusive.append(
            {
                "category": category,
                "label": labels[category],
                "count": count,
                "remaining_rate_percent": percent(count, remaining),
                "total_rate_percent": percent(count, total),
            }
        )
    doi_unlikely = sum(row["count"] for row in exclusive if row["category"] in {"book_or_chapter", "url_web", "thesis", "report_policy_legal", "conference"})
    summary = {
        "experiment_label": "Deney 19 sonrasi kalan referans siniflandirmasi",
        "sampled_references": total,
        "found_after_experiment19": len(found),
        "found_after_experiment19_rate_percent": percent(len(found), total),
        "remaining_after_experiment19": remaining,
        "remaining_after_experiment19_rate_percent": percent(remaining, total),
        "doi_unlikely_exclusive_count": doi_unlikely,
        "doi_unlikely_exclusive_remaining_rate_percent": percent(doi_unlikely, remaining),
        "exclusive_categories": exclusive,
    }
    write_json(out_dir / "remaining_after_experiment19_summary.json", summary)
    write_jsonl(out_dir / "remaining_after_experiment19_references.jsonl", classified)
    write_csv(
        out_dir / "remaining_after_experiment19_references.csv",
        [
            "sample_index",
            "publication_id",
            "reference_id",
            "reference_order",
            "exclusive_category",
            "exclusive_category_label",
            *[f"flag_{key}" for key in PATTERNS],
            "context",
        ],
        classified,
    )
    write_csv(out_dir / "remaining_after_experiment19_exclusive_categories.csv", ["category", "label", "count", "remaining_rate_percent", "total_rate_percent"], exclusive)
    write_report(
        out_dir / "remaining_after_experiment19_report_tr.md",
        "Deney 19 Sonrasi Kalan Referans Istatistigi",
        [
            f"- Deney 19 sonrasi bulunan: {summary['found_after_experiment19']} ({summary['found_after_experiment19_rate_percent']}%)",
            f"- Kalan: {summary['remaining_after_experiment19']} ({summary['remaining_after_experiment19_rate_percent']}%)",
            f"- DOI beklenmesi zayif: {summary['doi_unlikely_exclusive_count']} ({summary['doi_unlikely_exclusive_remaining_rate_percent']}% kalan)",
        ],
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deney 19: GROBID re-parse plus resolver retry.")
    parser.add_argument("--sample-csv", default=Path("trdizin_crossref_doi_stats_10k/sample_references_crossref.csv"), type=Path)
    parser.add_argument("--stq-csv", default=Path("trdizin_crossref_doi_stats_10k/simple_text_query_combined/simple_text_query_matches.csv"), type=Path)
    parser.add_argument("--doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/doi_not_found_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--no-doi-fallback-csv", default=Path("trdizin_crossref_doi_stats_10k/no_doi_tei_bibliographic_fallback.csv"), type=Path)
    parser.add_argument("--openalex-csv", default=Path("trdizin_crossref_doi_stats_10k/openalex_api_key_fallback/openalex_fallback_matches.csv"), type=Path)
    parser.add_argument("--dergipark-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_oai_fallback/dergipark_oai_matches.csv"), type=Path)
    parser.add_argument("--cleanup-csv", default=Path("trdizin_crossref_doi_stats_10k/crossref_cleanup_fallback/crossref_cleanup_matches.csv"), type=Path)
    parser.add_argument("--europepmc-csv", default=Path("trdizin_crossref_doi_stats_10k/europepmc_fallback/europepmc_fallback_matches.csv"), type=Path)
    parser.add_argument("--article-file-csv", default=Path("trdizin_crossref_doi_stats_10k/dergipark_article_file_probe/dergipark_article_file_probe_matches.csv"), type=Path)
    parser.add_argument("--experiment11-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment11_journal_like/experiment11_matches.csv"), type=Path)
    parser.add_argument("--experiment12-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment12_trdizin_target/trdizin_target_publication_matches.csv"), type=Path)
    parser.add_argument("--experiment13-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment13_trdizin_title_search/trdizin_title_search_matches.csv"), type=Path)
    parser.add_argument("--experiment14-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment14_hidden_doi/hidden_doi_matches.csv"), type=Path)
    parser.add_argument("--experiment15-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment15_dergipark_article_file/dergipark_article_file_matches.csv"), type=Path)
    parser.add_argument("--experiment16-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment16_isbn_book/isbn_book_matches.csv"), type=Path)
    parser.add_argument("--experiment18-csv", default=Path("trdizin_crossref_doi_stats_10k/experiment18_pubmed_citation_matcher/pubmed_citation_matches.csv"), type=Path)
    parser.add_argument("--match-report", default=Path("trdizin_full_reference_training_clean_date_10k/match_report.jsonl"), type=Path)
    parser.add_argument("--tei-dir", action="append", default=[Path("grobid_references_tei"), Path("trdizin_full_reference_training/grobid_process_references_tei")], type=Path)
    parser.add_argument("--out-dir", default=Path("trdizin_crossref_doi_stats_10k"), type=Path)
    parser.add_argument("--grobid-url", default="http://localhost:8072")
    parser.add_argument("--openalex-api-key", default="Fn1edVmRSGRAlMSISg47cZ")
    parser.add_argument("--include-category", action="append", default=sorted(DEFAULT_TARGET_CATEGORIES))
    parser.add_argument("--include-doi-unlikely", action="store_true")
    parser.add_argument("--min-alignment-score", default=0.72, type=float)
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--workers", default=8, type=int)
    parser.add_argument("--save-every", default=50, type=int)
    parser.add_argument("--crossref-rate", default=5.0, type=float)
    parser.add_argument("--trdizin-rate", default=4.0, type=float)
    parser.add_argument("--openalex-rate", default=5.0, type=float)
    parser.add_argument("--rows", default=5, type=int)
    parser.add_argument("--retries", default=1, type=int)
    parser.add_argument("--sleep", default=0.0, type=float)
    parser.add_argument("--max-targets", default=0, type=int)
    parser.add_argument("--skip-openalex-fetch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir / "experiment19_grobid_reparse"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_rows = read_csv(args.sample_csv)
    found13 = current_base_found(args, sample_rows)
    found14 = found_after_experiment14(found13, args)
    found15 = found_after_experiment15(found14, args)
    found16 = found_after_experiment16(found15, args)
    found18 = found_after_experiment18(found16, args)
    remaining_rows = remaining_sample_rows(sample_rows, found18)
    classified_remaining = classify_remaining(remaining_rows)
    classification_by_sample = {row["sample_index"]: row for row in classified_remaining}
    match_report = load_match_report(args.match_report)

    grobid_alive = check_grobid_alive(args.grobid_url, min(args.timeout, 5.0))
    tei_cache: Dict[str, List[GrobidReference]] = {}
    parse_rows: List[Dict[str, Any]] = []
    target_rows: List[Dict[str, Any]] = []
    include_categories = set(args.include_category or [])

    for row in remaining_rows:
        classified = classification_by_sample.get(row["sample_index"], row)
        publication_id = str(row.get("publication_id") or "")
        if publication_id not in tei_cache:
            path = find_tei_path(publication_id, args.tei_dir)
            tei_cache[publication_id] = parse_grobid_tei(path, publication_id) if path else []
        refs = tei_cache[publication_id]
        order = int(row["reference_order"]) if str(row.get("reference_order") or "").isdigit() else -1
        decision = match_report.get((publication_id, order))
        grobid_ref, alignment_score, alignment_source = align_grobid_reference(row, refs, decision, args.min_alignment_score)
        output = {
            "sample_index": row.get("sample_index", ""),
            "publication_id": publication_id,
            "reference_id": row.get("reference_id", ""),
            "reference_order": row.get("reference_order", ""),
            "exclusive_category": classified.get("exclusive_category", ""),
            "alignment_score": alignment_score,
            "alignment_source": alignment_source,
            "has_grobid_reference": bool(grobid_ref),
            "grobid_index": grobid_ref.grobid_index if grobid_ref else "",
            "grobid_doi": grobid_ref.doi if grobid_ref else "",
            "grobid_title": grobid_ref.title if grobid_ref else "",
            "grobid_journal": grobid_ref.journal if grobid_ref else "",
            "grobid_year": grobid_ref.year if grobid_ref else "",
            "grobid_authors": grobid_ref.authors if grobid_ref else "",
            "context": row.get("context", ""),
        }
        parse_rows.append(output)
        if grobid_ref:
            target = make_target_row({**row, "exclusive_category": classified.get("exclusive_category", "")}, grobid_ref, alignment_score, alignment_source)
            if target_is_searchable(target, include_categories, args.include_doi_unlikely):
                target_rows.append(target)

    target_rows = sorted(target_rows, key=lambda item: int(item["sample_index"]))
    if args.max_targets > 0:
        target_rows = target_rows[: args.max_targets]

    doi_cache_path = out_dir / "grobid_crossref_doi_cache.json"
    crossref_cache_path = out_dir / "grobid_crossref_search_cache.json"
    trdizin_cache_path = out_dir / "grobid_trdizin_search_cache.json"
    openalex_cache_path = out_dir / "grobid_openalex_cache.json"
    doi_cache = load_cache(doi_cache_path)
    crossref_cache = load_cache(crossref_cache_path)
    trdizin_cache = load_cache(trdizin_cache_path)
    openalex_cache = load_cache(openalex_cache_path)

    grobid_dois = sorted({row["grobid_doi"] for row in target_rows if row.get("grobid_doi")})
    fill_crossref_doi_cache(doi_cache_path, doi_cache, grobid_dois, args.workers, args.timeout, args.crossref_rate, args.save_every)

    crossref_queries = sorted({row["crossref_query"] for row in target_rows if row.get("crossref_query") and not row.get("grobid_doi")})
    missing_crossref = [query for query in crossref_queries if query not in crossref_cache]
    fill_crossref_search_cache(
        crossref_cache_path,
        crossref_cache,
        missing_crossref,
        args.rows,
        args.timeout,
        args.retries,
        args.sleep,
        args.workers,
        args.save_every,
        200,
        0.0,
        args.crossref_rate,
    )

    trdizin_keys = sorted({key for row in target_rows if not row.get("grobid_doi") for key in row.get("trdizin_query_keys") or []})
    fill_trdizin_search_cache(
        trdizin_cache_path,
        trdizin_cache,
        trdizin_keys,
        fetch_search_key,
        args.workers,
        args.timeout,
        args.trdizin_rate,
        args.save_every,
        rows=args.rows,
    )

    openalex_keys = sorted({row["openalex_key"] for row in target_rows if row.get("openalex_key") and not row.get("grobid_doi")})
    missing_openalex = [key for key in openalex_keys if key not in openalex_cache]
    if args.skip_openalex_fetch:
        print(f"skipping {len(missing_openalex)} missing OpenAlex requests", flush=True)
    else:
        fill_openalex_cache(
            openalex_cache_path,
            openalex_cache,
            missing_openalex,
            args.rows,
            args.timeout,
            args.retries,
            args.sleep,
            args.openalex_api_key,
            args.workers,
            args.openalex_rate,
            args.save_every,
            batch_size=200,
        )

    match_rows = [evaluate_target(row, doi_cache, crossref_cache, trdizin_cache, openalex_cache) for row in target_rows]
    strong_rows = [row for row in match_rows if row["experiment19_status"] == "strong"]
    possible_rows = [row for row in match_rows if row["experiment19_status"] == "possible"]
    found19 = set(found18) | {str(row["sample_index"]) for row in strong_rows}
    remaining_summary = write_remaining_after_experiment19(args, sample_rows, found19)

    parse_fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "exclusive_category",
        "alignment_score",
        "alignment_source",
        "has_grobid_reference",
        "grobid_index",
        "grobid_doi",
        "grobid_title",
        "grobid_journal",
        "grobid_year",
        "grobid_authors",
        "context",
    ]
    match_fieldnames = [
        "sample_index",
        "publication_id",
        "reference_id",
        "reference_order",
        "exclusive_category",
        "alignment_score",
        "alignment_source",
        "grobid_index",
        "grobid_doi",
        "grobid_title",
        "grobid_journal",
        "grobid_year",
        "grobid_authors",
        "grobid_volume",
        "grobid_issue",
        "grobid_pages",
        "experiment19_status",
        "resolver",
        "matched_id",
        "matched_doi",
        "matched_title",
        "matched_year",
        "matched_venue",
        "confidence",
        "title_similarity",
        "title_coverage",
        "title_token_count",
        "author_coverage",
        "year_match",
        "title_pair_similarity",
        "title_pair_coverage",
        "query",
        "context",
    ]
    write_csv(out_dir / "grobid_parse_rows.csv", parse_fieldnames, parse_rows)
    write_jsonl(out_dir / "grobid_parse_rows.jsonl", parse_rows)
    write_csv(out_dir / "grobid_reparse_matches.csv", match_fieldnames, match_rows)
    write_jsonl(out_dir / "grobid_reparse_matches.jsonl", match_rows)
    write_csv(out_dir / "grobid_reparse_review_candidates.csv", match_fieldnames, possible_rows)

    resolver_counts: Dict[str, int] = {}
    for row in strong_rows:
        resolver = row.get("resolver") or "unknown"
        resolver_counts[resolver] = resolver_counts.get(resolver, 0) + 1
    category_counts: Dict[str, int] = {}
    for row in strong_rows:
        category = row.get("exclusive_category") or "unknown"
        category_counts[category] = category_counts.get(category, 0) + 1
    openalex_missing_after = sum(1 for key in openalex_keys if key not in openalex_cache)
    summary = {
        "experiment_label": "Deney 19 - GROBID re-parse + resolver retry",
        "sampled_references": len(sample_rows),
        "grobid_service_url": args.grobid_url,
        "grobid_service_alive": grobid_alive,
        "base_found_before_experiment19": len(found18),
        "base_found_before_experiment19_rate_percent": percent(len(found18), len(sample_rows)),
        "remaining_before_experiment19": len(remaining_rows),
        "remaining_with_grobid_alignment": sum(1 for row in parse_rows if row["has_grobid_reference"]),
        "remaining_with_grobid_doi": sum(1 for row in parse_rows if row["grobid_doi"]),
        "remaining_with_grobid_title": sum(1 for row in parse_rows if row["grobid_title"]),
        "remaining_with_grobid_title_year": sum(1 for row in parse_rows if row["grobid_title"] and row["grobid_year"]),
        "target_categories": sorted(include_categories),
        "include_doi_unlikely": bool(args.include_doi_unlikely),
        "grobid_retry_targets": len(target_rows),
        "grobid_unique_doi_targets": len(grobid_dois),
        "crossref_search_queries": len(crossref_queries),
        "trdizin_search_queries": len(trdizin_keys),
        "openalex_search_queries": len(openalex_keys),
        "openalex_cached_queries": sum(1 for key in openalex_keys if key in openalex_cache),
        "openalex_missing_queries": openalex_missing_after,
        "openalex_fetch_skipped": bool(args.skip_openalex_fetch),
        "experiment19_strong_matches": len(strong_rows),
        "experiment19_possible_matches": len(possible_rows),
        "experiment19_no_match": sum(1 for row in match_rows if row["experiment19_status"] == "no_match"),
        "experiment19_strong_by_resolver": resolver_counts,
        "experiment19_strong_by_category": category_counts,
        "experiment19_auto_resolved_found": len(found19),
        "experiment19_auto_resolved_rate_percent": percent(len(found19), len(sample_rows)),
        "remaining_summary": remaining_summary,
        "complete": not openalex_missing_after,
    }
    write_json(out_dir / "grobid_reparse_summary.json", summary)
    write_report(
        out_dir / "grobid_reparse_report_tr.md",
        "Deney 19 - GROBID Re-parse + Resolver Retry",
        [
            f"- GROBID servis: {args.grobid_url} ({'alive' if grobid_alive else 'not reachable'})",
            f"- Deney 18 sonrasi baz: {summary['base_found_before_experiment19']} ({summary['base_found_before_experiment19_rate_percent']}%)",
            f"- Kalan referans: {summary['remaining_before_experiment19']}",
            f"- GROBID alignment bulunan: {summary['remaining_with_grobid_alignment']}",
            f"- GROBID title+year bulunan: {summary['remaining_with_grobid_title_year']}",
            f"- Retry hedefi: {summary['grobid_retry_targets']}",
            f"- Strong: {summary['experiment19_strong_matches']}",
            f"- Possible: {summary['experiment19_possible_matches']}",
            f"- Yeni toplam: {summary['experiment19_auto_resolved_found']} ({summary['experiment19_auto_resolved_rate_percent']}%)",
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
