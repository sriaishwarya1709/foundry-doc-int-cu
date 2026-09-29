"""Extraction engines: Azure AI Document Intelligence and Azure Content Understanding.

Both run on the same Microsoft Foundry (AIServices) resource and return a normalized result
so the UI can show them side by side and the indexer can treat them the same way.
"""

import io
import time
from functools import lru_cache
from typing import Any

from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.exceptions import HttpResponseError

from .config import get_credential, get_settings

DI_MODELS = [
    "prebuilt-layout",
    "prebuilt-read",
    "prebuilt-invoice",
    "prebuilt-receipt",
    "prebuilt-idDocument",
    "prebuilt-contract",
]
CU_ANALYZERS = [
    "prebuilt-documentSearch",
    "prebuilt-invoice",
    "prebuilt-receipt",
    "prebuilt-layout",
]


@lru_cache
def _di_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(get_settings().document_intelligence_endpoint, get_credential())


@lru_cache
def _cu_client() -> ContentUnderstandingClient:
    return ContentUnderstandingClient(endpoint=get_settings().ai_services_endpoint, credential=get_credential())


# ---------------- Document Intelligence ----------------
def _di_value(f: Any) -> Any:
    if f is None:
        return None
    if f.type == "array":
        return [_di_value(x) for x in (f.value_array or [])]
    if f.type == "object":
        return {k: _di_value(v) for k, v in (f.value_object or {}).items()}
    if f.type == "currency" and f.value_currency:
        return {"amount": f.value_currency.amount, "currency": f.value_currency.currency_code}
    return f.content


def analyze_with_document_intelligence(data: bytes, model_id: str) -> dict:
    if model_id not in DI_MODELS:
        raise ValueError(f"Unsupported Document Intelligence model: {model_id}")
    started = time.perf_counter()
    client = _di_client()
    try:
        poller = client.begin_analyze_document(
            model_id,
            body=io.BytesIO(data),
            content_type="application/octet-stream",
            output_content_format=DocumentContentFormat.MARKDOWN,
        )
        result = poller.result()
    except HttpResponseError:
        # Some models (e.g. prebuilt-read) only return plain text.
        poller = client.begin_analyze_document(model_id, body=io.BytesIO(data), content_type="application/octet-stream")
        result = poller.result()

    fields: dict[str, Any] = {}
    for i, doc in enumerate(result.documents or []):
        prefix = f"doc{i + 1}." if len(result.documents) > 1 else ""
        for name, f in (doc.fields or {}).items():
            fields[prefix + name] = {"value": _di_value(f), "confidence": f.confidence}

    return {
        "engine": "document-intelligence",
        "model": model_id,
        "markdown": result.content or "",
        "summary": None,
        "fields": fields,
        "pages": len(result.pages or []),
        "tables": len(result.tables or []),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


# ---------------- Content Understanding ----------------
def _cu_value(f: Any) -> Any:
    v = getattr(f, "value", None)
    if isinstance(v, list):
        return [_cu_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _cu_value(x) for k, x in v.items()}
    return v


def analyze_with_content_understanding(data: bytes, analyzer_id: str) -> dict:
    if analyzer_id not in CU_ANALYZERS:
        raise ValueError(f"Unsupported Content Understanding analyzer: {analyzer_id}")
    started = time.perf_counter()
    poller = _cu_client().begin_analyze_binary(analyzer_id=analyzer_id, binary_input=data)
    result = poller.result()

    markdown_parts, fields, pages, tables = [], {}, 0, 0
    for content in result.contents or []:
        if content.markdown:
            markdown_parts.append(content.markdown)
        for name, f in (getattr(content, "fields", None) or {}).items():
            fields[name] = {"value": _cu_value(f), "confidence": getattr(f, "confidence", None)}
        pages += len(getattr(content, "pages", None) or [])
        tables += len(getattr(content, "tables", None) or [])

    summary = fields.pop("Summary", {}).get("value")
    return {
        "engine": "content-understanding",
        "model": analyzer_id,
        "markdown": "\n\n".join(markdown_parts),
        "summary": summary,
        "fields": fields,
        "pages": pages,
        "tables": tables,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
