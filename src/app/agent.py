"""Microsoft Foundry prompt agent grounded on the Azure AI Search index (Foundry SDK: azure-ai-projects 2.x)."""

from functools import lru_cache

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AISearchIndexResource,
    AzureAISearchQueryType,
    AzureAISearchTool,
    AzureAISearchToolResource,
    PromptAgentDefinition,
)

from .config import get_credential, get_settings
from .indexer import url_for_title

INSTRUCTIONS = """You are the Document Analyst for a document-processing demo.
Documents are ingested with Azure AI Document Intelligence and Azure Content Understanding,
then indexed in Azure AI Search. Each indexed chunk records which engine and model extracted it.

Rules:
- Always use the Azure AI Search tool to answer; never answer from general knowledge about the documents.
- Cite every factual statement using the tool's citation format.
- When asked about invoices, receipts, IDs or contracts, prefer the 'Structured fields extracted' chunks
  and present values in a compact markdown table.
- When the user asks to compare engines, contrast Document Intelligence vs Content Understanding results.
- If the answer is not in the documents, say so clearly.
"""


@lru_cache
def project_client() -> AIProjectClient:
    return AIProjectClient(endpoint=get_settings().foundry_project_endpoint, credential=get_credential())


def create_or_update_agent() -> str:
    """Publish a new agent version (idempotent from the caller's point of view)."""
    s = get_settings()
    project = project_client()
    connection_id = project.connections.get(s.search_connection_name).id
    agent = project.agents.create_version(
        agent_name=s.agent_name,
        definition=PromptAgentDefinition(
            model=s.chat_deployment,
            instructions=INSTRUCTIONS,
            tools=[
                AzureAISearchTool(
                    azure_ai_search=AzureAISearchToolResource(
                        indexes=[
                            AISearchIndexResource(
                                project_connection_id=connection_id,
                                index_name=s.search_index_name,
                                query_type=AzureAISearchQueryType.VECTOR_SEMANTIC_HYBRID,
                                top_k=8,
                            )
                        ]
                    )
                )
            ],
        ),
        description="Answers questions over documents processed by Document Intelligence and Content Understanding.",
    )
    return f"{agent.name}:{agent.version}"


def ask(question: str, conversation_id: str | None) -> dict:
    s = get_settings()
    openai = project_client().get_openai_client()
    if not conversation_id:
        conversation_id = openai.conversations.create().id

    response = openai.responses.create(
        conversation=conversation_id,
        input=question,
        extra_body={"agent_reference": {"name": s.agent_name, "type": "agent_reference"}},
    )

    citations, tool_calls = [], []
    for item in response.output or []:
        if item.type == "message":
            for part in item.content or []:
                for ann in getattr(part, "annotations", None) or []:
                    if ann.type == "url_citation":
                        citations.append({"title": getattr(ann, "title", None), "url": ann.url})
        else:
            tool_calls.append(item.type)

    unique = list({(c["title"], c["url"]): c for c in citations}.values())
    for c in unique:
        # The Search tool cites the service endpoint; link to the original document instead.
        if c["title"] and not c["url"].startswith("/api/documents/"):
            c["url"] = url_for_title(c["title"]) or c["url"]
    return {
        "answer": response.output_text,
        "citations": unique,
        "tool_calls": tool_calls,
        "conversation_id": conversation_id,
        "response_id": response.id,
    }
