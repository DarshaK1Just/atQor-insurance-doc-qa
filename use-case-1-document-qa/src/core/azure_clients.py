"""Azure client factory.

Authentication policy (assignment §6 Security): keyless `DefaultAzureCredential`
is preferred (works as `az login` locally, managed identity in the cloud).
A key provided via env is honoured as the low-friction fallback for free-trial
reviewers. No credential ever appears in code."""
from functools import lru_cache

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI

from src.core.config import get_settings

_AOAI_SCOPE = "https://cognitiveservices.azure.com/.default"


def _ssl_kwargs() -> dict:
    """azure-core transport honours `connection_verify`. When VERIFY_SSL=false
    (local demo behind a TLS-intercepting proxy) we pass False to unblock; the
    default keeps full verification."""
    return {} if get_settings().verify_ssl else {"connection_verify": False}


@lru_cache
def docintel_client() -> DocumentIntelligenceClient:
    s = get_settings()
    cred = AzureKeyCredential(s.docintel_key) if s.docintel_key else DefaultAzureCredential()
    return DocumentIntelligenceClient(endpoint=s.docintel_endpoint, credential=cred, **_ssl_kwargs())


@lru_cache
def search_client() -> SearchClient:
    s = get_settings()
    cred = AzureKeyCredential(s.search_key) if s.search_key else DefaultAzureCredential()
    return SearchClient(endpoint=s.search_endpoint, index_name=s.search_index_name,
                        credential=cred, **_ssl_kwargs())


@lru_cache
def search_index_client() -> SearchIndexClient:
    s = get_settings()
    cred = AzureKeyCredential(s.search_key) if s.search_key else DefaultAzureCredential()
    return SearchIndexClient(endpoint=s.search_endpoint, credential=cred, **_ssl_kwargs())


@lru_cache
def openai_client() -> AzureOpenAI:
    s = get_settings()
    # The OpenAI SDK is httpx-backed; disabling verification means a custom client.
    http_client = None
    if not s.verify_ssl:
        import httpx
        http_client = httpx.Client(verify=False)
    common = {"azure_endpoint": s.azure_openai_endpoint,
              "api_version": s.azure_openai_api_version}
    if http_client is not None:
        common["http_client"] = http_client
    if s.azure_openai_api_key:
        return AzureOpenAI(api_key=s.azure_openai_api_key, **common)
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), _AOAI_SCOPE)
    return AzureOpenAI(azure_ad_token_provider=token_provider, **common)
