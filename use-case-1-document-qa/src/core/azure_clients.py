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


@lru_cache
def docintel_client() -> DocumentIntelligenceClient:
    s = get_settings()
    cred = AzureKeyCredential(s.docintel_key) if s.docintel_key else DefaultAzureCredential()
    return DocumentIntelligenceClient(endpoint=s.docintel_endpoint, credential=cred)


@lru_cache
def search_client() -> SearchClient:
    s = get_settings()
    cred = AzureKeyCredential(s.search_key) if s.search_key else DefaultAzureCredential()
    return SearchClient(endpoint=s.search_endpoint, index_name=s.search_index_name, credential=cred)


@lru_cache
def search_index_client() -> SearchIndexClient:
    s = get_settings()
    cred = AzureKeyCredential(s.search_key) if s.search_key else DefaultAzureCredential()
    return SearchIndexClient(endpoint=s.search_endpoint, credential=cred)


@lru_cache
def openai_client() -> AzureOpenAI:
    s = get_settings()
    if s.azure_openai_api_key:
        return AzureOpenAI(
            azure_endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version,
        )
    token_provider = get_bearer_token_provider(DefaultAzureCredential(), _AOAI_SCOPE)
    return AzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=s.azure_openai_api_version,
    )
