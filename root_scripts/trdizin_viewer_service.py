from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import requests

try:
    from flask import Response
except ModuleNotFoundError:
    Response = None  # type: ignore[assignment]


TRDIZIN_PUBLICATION_BY_ID = "https://search.trdizin.gov.tr/api/publicationById/{publication_id}"
TRDIZIN_GET_FILE = "https://search.trdizin.gov.tr/api/getFile/{key}?showViewer=false"
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_publication_metadata(publication_id: int) -> Optional[Dict[str, Any]]:
    url = TRDIZIN_PUBLICATION_BY_ID.format(publication_id=publication_id)
    response = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
    response.raise_for_status()

    payload = response.json()
    hits = ((payload.get("hits") or {}).get("hits") or [])
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if isinstance(source, dict) and source.get("id") == publication_id:
            return source
    return None


def find_pdf_key(metadata: Dict[str, Any]) -> Optional[str]:
    for key in ("pdf", "pdf_key", "pdfKey", "pdfId"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_pdf_url(pdf_key: str) -> Optional[str]:
    url = TRDIZIN_GET_FILE.format(key=pdf_key)
    response = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if not isinstance(payload, str):
        return None

    pdf_url = payload.strip().strip('"')
    return pdf_url if pdf_url.startswith(("http://", "https://")) else None


def fetch_pdf(publication_id: int) -> Tuple[bytes, str]:
    metadata = fetch_publication_metadata(publication_id)
    if not metadata:
        raise RuntimeError("Publication metadata bulunamadi.")

    pdf_key = find_pdf_key(metadata)
    if not pdf_key:
        raise RuntimeError("Metadata icinde pdf key bulunamadi.")

    pdf_url = resolve_pdf_url(pdf_key)
    if not pdf_url:
        raise RuntimeError("PDF URL alinamadi.")

    response = requests.get(pdf_url, timeout=60, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return response.content, response.headers.get("Content-Type", "application/pdf")


def build_pdf_response(publication_id: int) -> Response:
    if Response is None:
        raise RuntimeError("Flask is required for build_pdf_response().")
    try:
        pdf_bytes, content_type = fetch_pdf(publication_id)
        mimetype = content_type if "pdf" in content_type.lower() else "application/pdf"
        return Response(
            pdf_bytes,
            mimetype=mimetype,
            headers={
                "Content-Disposition": f'attachment; filename="{publication_id}.pdf"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        return Response(f"PDF yuklenemedi: {exc}", status=500, mimetype="text/plain; charset=utf-8")
