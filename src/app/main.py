import logging
import os
import re
from pathlib import Path

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor()

from . import agent, indexer, storage  # noqa: E402
from .config import get_settings  # noqa: E402
from .extractors import CU_ANALYZERS, DI_MODELS  # noqa: E402
from .pipeline import process_document  # noqa: E402

log = logging.getLogger("docdemo")
STATIC = Path(__file__).parent / "static"
DOC_ID = re.compile(r"^[a-f0-9]{32}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

app = FastAPI(title="Document Intelligence + Content Understanding + Foundry Agent")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(HttpResponseError)
def azure_error(_, exc: HttpResponseError):
    log.exception("Azure service error")
    return JSONResponse(status_code=502, content={"detail": exc.message or str(exc)})


@app.exception_handler(ValueError)
def bad_request(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _check_doc_id(doc_id: str) -> None:
    if not DOC_ID.match(doc_id):
        raise HTTPException(404)


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    s = get_settings()
    return {
        "di_models": DI_MODELS,
        "cu_analyzers": CU_ANALYZERS,
        "agent_name": s.agent_name,
        "chat_deployment": s.chat_deployment,
        "embedding_deployment": s.embedding_deployment,
        "search_index": s.search_index_name,
        "project_endpoint": s.foundry_project_endpoint,
    }


@app.post("/api/ingest")
def ingest(
    file: UploadFile = File(...),
    engine: str = Form("both"),
    di_model: str = Form("prebuilt-layout"),
    cu_analyzer: str = Form("prebuilt-documentSearch"),
):
    data = file.file.read()
    return process_document(file.filename or "document", data, file.content_type or "application/octet-stream", engine, di_model, cu_analyzer)


@app.get("/api/documents")
def documents():
    return storage.list_documents()


@app.get("/api/documents/{doc_id}/results")
def document_results(doc_id: str):
    _check_doc_id(doc_id)
    return storage.load_processed(doc_id)


@app.get("/api/documents/{doc_id}/{name}")
def document_file(doc_id: str, name: str):
    _check_doc_id(doc_id)
    if not SAFE_NAME.match(name):
        raise HTTPException(404)
    try:
        data, content_type = storage.download_raw(f"{doc_id}/{name}")
    except ResourceNotFoundError:
        raise HTTPException(404)
    return Response(data, media_type=content_type, headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    _check_doc_id(doc_id)
    indexer.delete_document(doc_id)
    storage.delete_raw(doc_id)
    return {"deleted": doc_id}


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=200)


@app.post("/api/chat")
def chat(req: ChatRequest):
    return agent.ask(req.question, req.conversation_id)


@app.get("/healthz")
def health():
    return {"status": "ok"}
