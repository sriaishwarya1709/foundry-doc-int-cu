"""End-to-end ingestion pipeline: store -> extract (DI and/or CU) -> persist -> index."""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePath

from . import indexer, storage
from .extractors import analyze_with_content_understanding, analyze_with_document_intelligence

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".heif", ".docx", ".xlsx", ".pptx"}
MAX_BYTES = 25 * 1024 * 1024


def safe_filename(name: str) -> str:
    base = PurePath(name or "document").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120]
    return base or "document"


def process_document(
    filename: str,
    data: bytes,
    content_type: str,
    engine: str,
    di_model: str = "prebuilt-layout",
    cu_analyzer: str = "prebuilt-documentSearch",
) -> dict:
    if engine not in {"document-intelligence", "content-understanding", "both"}:
        raise ValueError("engine must be document-intelligence, content-understanding or both")
    name = safe_filename(filename)
    if PurePath(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    if len(data) > MAX_BYTES:
        raise ValueError("File exceeds 25 MB limit")

    doc_id = uuid.uuid4().hex
    blob_name = f"{doc_id}/{name}"
    url = f"/api/documents/{blob_name}"

    jobs = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        if engine in ("document-intelligence", "both"):
            jobs["document-intelligence"] = pool.submit(analyze_with_document_intelligence, data, di_model)
        if engine in ("content-understanding", "both"):
            jobs["content-understanding"] = pool.submit(analyze_with_content_understanding, data, cu_analyzer)
        storage.save_raw(blob_name, data, content_type, {"engines": ",".join(jobs)})
        results = {k: f.result() for k, f in jobs.items()}

    for eng, result in results.items():
        result["chunks_indexed"] = indexer.index_extraction(doc_id, name, url, result)
        storage.save_processed(doc_id, eng, result)

    return {"doc_id": doc_id, "name": name, "url": url, "results": list(results.values())}
