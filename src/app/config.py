import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Local dev: read <repo>/.env (App Service injects real app settings).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


@dataclass(frozen=True)
class Settings:
    ai_services_endpoint: str
    document_intelligence_endpoint: str
    azure_openai_endpoint: str
    foundry_project_endpoint: str
    chat_deployment: str
    mini_deployment: str
    embedding_deployment: str
    search_endpoint: str
    search_index_name: str
    search_connection_name: str
    storage_account_url: str
    agent_name: str
    embedding_dimensions: int = 3072
    raw_container: str = "documents"
    processed_container: str = "processed"


@lru_cache
def get_settings() -> Settings:
    e = os.environ
    return Settings(
        ai_services_endpoint=e["AI_SERVICES_ENDPOINT"],
        document_intelligence_endpoint=e["DOCUMENT_INTELLIGENCE_ENDPOINT"],
        azure_openai_endpoint=e["AZURE_OPENAI_ENDPOINT"],
        foundry_project_endpoint=e["FOUNDRY_PROJECT_ENDPOINT"],
        chat_deployment=e.get("CHAT_DEPLOYMENT", "gpt-4.1"),
        mini_deployment=e.get("MINI_DEPLOYMENT", "gpt-4.1-mini"),
        embedding_deployment=e.get("EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
        search_endpoint=e["SEARCH_ENDPOINT"],
        search_index_name=e.get("SEARCH_INDEX_NAME", "processed-documents"),
        search_connection_name=e.get("SEARCH_CONNECTION_NAME", "doc-search"),
        storage_account_url=e["STORAGE_ACCOUNT_URL"],
        agent_name=e.get("AGENT_NAME", "document-analyst"),
    )


@lru_cache
def get_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)
