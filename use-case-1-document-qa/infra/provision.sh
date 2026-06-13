#!/usr/bin/env bash
# Free-tier provisioning for the Document Q&A assignment.
# Prereqs: az login; an Azure Free Account ($200 credit covers Azure OpenAI usage; ~<$5 total).
# Usage: bash infra/provision.sh [resource-group] [region]
set -euo pipefail

RG="${1:-rg-docqa-demo}"
LOC="${2:-eastus}"
SUFFIX="$RANDOM"

echo "==> Resource group"
az group create -n "$RG" -l "$LOC" -o none

echo "==> Document Intelligence (F0 free tier: 500 pages/month, 2-page analysis window)"
az cognitiveservices account create -n "docintel-docqa-$SUFFIX" -g "$RG" -l "$LOC" \
  --kind FormRecognizer --sku F0 --yes -o none

echo "==> Azure AI Search (FREE tier: hybrid search yes, semantic ranker no)"
az search service create -n "search-docqa-$SUFFIX" -g "$RG" -l "$LOC" --sku free -o none

echo "==> Azure OpenAI (billed against free-account credit; total project < \$5)"
az cognitiveservices account create -n "aoai-docqa-$SUFFIX" -g "$RG" -l "$LOC" \
  --kind OpenAI --sku S0 --yes -o none
az cognitiveservices account deployment create -n "aoai-docqa-$SUFFIX" -g "$RG" \
  --deployment-name gpt-4o-mini --model-name gpt-4o-mini --model-version "2024-07-18" \
  --model-format OpenAI --sku-name GlobalStandard --sku-capacity 10 -o none
az cognitiveservices account deployment create -n "aoai-docqa-$SUFFIX" -g "$RG" \
  --deployment-name text-embedding-3-small --model-name text-embedding-3-small \
  --model-version "1" --model-format OpenAI --sku-name Standard --sku-capacity 10 -o none

echo "==> (optional) Storage account for blob originals"
az storage account create -n "stdocqa$SUFFIX" -g "$RG" -l "$LOC" --sku Standard_LRS -o none

echo
echo "Now fill .env with:"
echo "  DOCINTEL_ENDPOINT = $(az cognitiveservices account show -n docintel-docqa-$SUFFIX -g $RG --query properties.endpoint -o tsv)"
echo "  DOCINTEL_KEY      = $(az cognitiveservices account keys list -n docintel-docqa-$SUFFIX -g $RG --query key1 -o tsv)"
echo "  SEARCH_ENDPOINT   = https://search-docqa-$SUFFIX.search.windows.net"
echo "  SEARCH_KEY        = $(az search admin-key show --service-name search-docqa-$SUFFIX -g $RG --query primaryKey -o tsv)"
echo "  AZURE_OPENAI_ENDPOINT = $(az cognitiveservices account show -n aoai-docqa-$SUFFIX -g $RG --query properties.endpoint -o tsv)"
echo "  AZURE_OPENAI_API_KEY  = $(az cognitiveservices account keys list -n aoai-docqa-$SUFFIX -g $RG --query key1 -o tsv)"
echo "  BLOB_CONNECTION_STRING = $(az storage account show-connection-string -n stdocqa$SUFFIX -g $RG -o tsv)"
echo
echo "Teardown when done:  az group delete -n $RG --yes --no-wait"
