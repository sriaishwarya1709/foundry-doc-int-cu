"""Chunk extracted markdown, embed with Foundry (text-embedding-3-large) and push to Azure AI Search."""

import json
import re
from functools import lru_cache

from azure.identity import get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from openai import AzureOpenAI

from .config import get_credential, get_settings

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


@lru_cache
def _openai() -> AzureOpenAI:
    s = get_settings()
    return AzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        azure_ad_token_provider=get_bearer_token_provider(get_credential(), "https://cognitiveservices.azure.com/.default"),
        api_version="2024-10-21",
    )


@lru_cache
def _search_client() -> SearchClient:
    s = get_settings()
    return SearchClient(s.search_endpoint, s.search_index_name, get_credential())


def ensure_index() -> None:
    """Create/update the index. The integrated vectorizer lets the Foundry agent run hybrid queries."""
    s = get_settings()
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="url", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="engine", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="model", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, sortable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=s.embedding_dimensions,
            vector_search_profile_name="vprofile",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="vprofile", algorithm_configuration_name="hnsw", vectorizer_name="foundry")],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="foundry",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=s.azure_openai_endpoint.rstrip("/"),
                    deployment_name=s.embedding_deployment,
                    model_name="text-embedding-3-large",
                ),
            )
        ],
    )
    semantic = SemanticSearch(
        default_configuration_name="default",
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    )
    index = SearchIndex(name=s.search_index_name, fields=fields, vector_search=vector_search, semantic_search=semantic)
    SearchIndexClient(s.search_endpoint, get_credential()).create_or_update_index(index)


def chunk_markdown(text: str) -> list[str]:
    """Paragraph-aware chunking with a small overlap."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 2 > CHUNK_SIZE and current:
            chunks.append(current)
            current = current[-CHUNK_OVERLAP:]
        while len(p) > CHUNK_SIZE:
            chunks.append((current + "\n\n" + p[:CHUNK_SIZE]).strip())
            p, current = p[CHUNK_SIZE - CHUNK_OVERLAP :], ""
        current = f"{current}\n\n{p}".strip()
    if current:
        chunks.append(current)
    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 16):
        resp = _openai().embeddings.create(model=s.embedding_deployment, input=texts[i : i + 16])
        vectors.extend(d.embedding for d in resp.data)
    return vectors


def index_extraction(doc_id: str, title: str, url: str, extraction: dict) -> int:
    texts: list[str] = []
    if extraction.get("summary"):
        texts.append(f"Summary of {title}:\n{extraction['summary']}")
    if extraction.get("fields"):
        values = {k: v["value"] for k, v in extraction["fields"].items()}
        texts.append(f"Structured fields extracted from {title} ({extraction['model']}):\n" + json.dumps(values, default=str, indent=1))
    texts.extend(chunk_markdown(extraction.get("markdown") or ""))
    if not texts:
        return 0

    engine = extraction["engine"]
    vectors = _embed(texts)
    docs = [
        {
            "id": f"{doc_id}-{'di' if engine == 'document-intelligence' else 'cu'}-{i}",
            "doc_id": doc_id,
            "title": title,
            "url": url,
            "content": text,
            "engine": engine,
            "model": extraction["model"],
            "chunk_index": i,
            "content_vector": vec,
        }
        for i, (text, vec) in enumerate(zip(texts, vectors))
    ]
    _search_client().upload_documents(documents=docs)
    return len(docs)


def url_for_title(title: str) -> str | None:
    escaped = title.replace("'", "''")
    hits = list(_search_client().search(search_text="*", filter=f"title eq '{escaped}'", select=["url"], top=1))
    return hits[0]["url"] if hits else None


def delete_document(doc_id: str) -> None:
    client = _search_client()
    hits = client.search(search_text="*", filter=f"doc_id eq '{doc_id}'", select=["id"], top=1000)
    ids = [{"id": h["id"]} for h in hits]
    if ids:
        client.delete_documents(documents=ids)
