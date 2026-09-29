"""Blob Storage: raw uploads in `documents/`, extraction results in `processed/`."""

import json
from functools import lru_cache

from azure.storage.blob import BlobServiceClient, ContentSettings

from .config import get_credential, get_settings


@lru_cache
def _service() -> BlobServiceClient:
    return BlobServiceClient(get_settings().storage_account_url, credential=get_credential())


def save_raw(blob_name: str, data: bytes, content_type: str, metadata: dict[str, str]) -> None:
    _service().get_blob_client(get_settings().raw_container, blob_name).upload_blob(
        data, overwrite=True, content_settings=ContentSettings(content_type=content_type), metadata=metadata
    )


def save_processed(doc_id: str, engine: str, result: dict) -> None:
    _service().get_blob_client(get_settings().processed_container, f"{doc_id}/{engine}.json").upload_blob(
        json.dumps(result, default=str, indent=2), overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def load_processed(doc_id: str) -> list[dict]:
    container = _service().get_container_client(get_settings().processed_container)
    return [json.loads(container.download_blob(b.name).readall()) for b in container.list_blobs(name_starts_with=f"{doc_id}/")]


def list_documents() -> list[dict]:
    container = _service().get_container_client(get_settings().raw_container)
    docs = [
        {
            "doc_id": b.name.split("/", 1)[0],
            "name": b.name.split("/", 1)[-1],
            "blob": b.name,
            "size": b.size,
            "uploaded": b.last_modified.isoformat() if b.last_modified else None,
            "engines": (b.metadata or {}).get("engines", ""),
        }
        for b in container.list_blobs(include=["metadata"])
    ]
    return sorted(docs, key=lambda d: d["uploaded"] or "", reverse=True)


def download_raw(blob_name: str) -> tuple[bytes, str]:
    blob = _service().get_blob_client(get_settings().raw_container, blob_name)
    props = blob.get_blob_properties()
    return blob.download_blob().readall(), props.content_settings.content_type or "application/octet-stream"


def delete_raw(doc_id: str) -> None:
    s = get_settings()
    for container_name in (s.raw_container, s.processed_container):
        container = _service().get_container_client(container_name)
        for b in container.list_blobs(name_starts_with=f"{doc_id}/"):
            container.delete_blob(b.name)
