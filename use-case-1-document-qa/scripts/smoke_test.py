"""Pre-demo verification: asserts every Azure dependency answers before you
record anything. Run with the API running:  python scripts/smoke_test.py"""
import sys

import requests

from src.core.config import get_settings


def main() -> int:
    settings = get_settings()
    failures: list[str] = []

    # 1. Azure OpenAI chat + embeddings
    try:
        from src.core.azure_clients import openai_client
        client = openai_client()
        client.chat.completions.create(model=settings.azure_openai_chat_deployment,
                                       messages=[{"role": "user", "content": "ping"}], max_tokens=2)
        client.embeddings.create(model=settings.azure_openai_embed_deployment, input=["ping"],
                                 dimensions=settings.embed_dimensions)
        print("[ok] Azure OpenAI chat + embeddings")
    except Exception as exc:
        failures.append(f"Azure OpenAI: {exc}")

    # 2. Document Intelligence reachability
    try:
        from src.core.azure_clients import docintel_client
        docintel_client()  # construction validates endpoint shape
        assert settings.docintel_endpoint.startswith("https://"), "DOCINTEL_ENDPOINT not set"
        print("[ok] Document Intelligence client configured")
    except Exception as exc:
        failures.append(f"Document Intelligence: {exc}")

    # 3. Search index
    try:
        from src.indexing.index_manager import ensure_index
        ensure_index()
        print(f"[ok] Azure AI Search index '{settings.search_index_name}'")
    except Exception as exc:
        failures.append(f"Azure AI Search: {exc}")

    # 4. API round-trip
    try:
        response = requests.get(f"{settings.api_base_url}/health", timeout=5)
        response.raise_for_status()
        print("[ok] API /health")
    except Exception as exc:
        failures.append(f"API (is uvicorn running?): {exc}")

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"  [x] {failure}")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
