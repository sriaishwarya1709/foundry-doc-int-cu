"""One-time / per-deployment setup. Run from `src/`:  python -m app.bootstrap

1. Maps Foundry model deployments as Content Understanding defaults (required for prebuilt analyzers).
2. Creates/updates the Azure AI Search index (with integrated Foundry vectorizer).
3. Publishes the Foundry prompt agent wired to the index through the project's Search connection.

Sample documents are seeded through the deployed web app (storage is private-endpoint only).
"""

from azure.ai.contentunderstanding import ContentUnderstandingClient

from .agent import create_or_update_agent
from .config import get_credential, get_settings
from .indexer import ensure_index


def configure_content_understanding_defaults() -> None:
    s = get_settings()
    client = ContentUnderstandingClient(endpoint=s.ai_services_endpoint, credential=get_credential())
    defaults = client.update_defaults(
        model_deployments={
            "gpt-4.1": s.chat_deployment,
            "gpt-4.1-mini": s.mini_deployment,
            "text-embedding-3-large": s.embedding_deployment,
        }
    )
    print(f"[CU] model defaults: {dict(defaults.model_deployments or {})}")


def main() -> None:
    configure_content_understanding_defaults()
    ensure_index()
    print(f"[Search] index '{get_settings().search_index_name}' ready")
    print(f"[Foundry] agent published: {create_or_update_agent()}")


if __name__ == "__main__":
    main()
