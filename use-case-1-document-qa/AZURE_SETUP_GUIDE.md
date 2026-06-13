# Azure Services Setup Guide - Complete Step-by-Step

This guide will walk you through setting up all Azure services needed for the Document Q&A application and obtaining the required credentials.

## Prerequisites

1. **Azure Account**: Create a free Azure account at https://azure.microsoft.com/free/
   - Get $200 free credit for 30 days
   - Some services have free tiers that continue after credit expires

2. **Install Azure CLI** (optional but recommended):
   ```bash
   # Download from: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli
   # After installation, login:
   az login
   ```

---

## Service 1: Azure OpenAI (Required)

### Cost: $200 free credit (no permanent free tier)

### Step-by-Step Setup:

1. **Navigate to Azure Portal**
   - Go to https://portal.azure.com
   - Sign in with your Azure account

2. **Create Azure OpenAI Resource**
   - Click "Create a resource" (+ icon)
   - Search for "Azure OpenAI"
   - Click "Create"

3. **Fill in Resource Details**
   - **Subscription**: Select your subscription
   - **Resource group**: Create new (e.g., "rg-document-qa") or select existing
   - **Region**: Choose a region (e.g., "East US", "West Europe")
   - **Name**: Enter a unique name (e.g., "my-openai-service")
   - **Pricing tier**: Select "Standard S0"
   - Click "Next" through tabs, then "Review + Create"

4. **Deploy Models**
   
   After resource creation (takes 2-5 minutes):
   
   a. **Deploy Chat Model (GPT-4o-mini)**:
   - Go to your Azure OpenAI resource
   - Click "Go to Azure OpenAI Studio" button
   - In the Studio, click "Deployments" in left menu
   - Click "+ Create new deployment"
   - **Model**: Select "gpt-4o-mini" (or "gpt-4o" if you have quota)
   - **Deployment name**: `gpt-4o-mini` (use exact name for .env)
   - **Deployment type**: Standard
   - Click "Create"
   
   b. **Deploy Embedding Model**:
   - Click "+ Create new deployment" again
   - **Model**: Select "text-embedding-3-small"
   - **Deployment name**: `text-embedding-3-small` (use exact name)
   - Click "Create"

5. **Get Credentials**
   - Go back to Azure Portal → Your OpenAI resource
   - Click "Keys and Endpoint" in left menu
   - Copy:
     - **Endpoint**: `https://your-name.openai.azure.com/`
     - **KEY 1**: Copy the entire key string

6. **Add to .env file**:
   ```env
   AZURE_OPENAI_ENDPOINT=https://your-name.openai.azure.com/
   AZURE_OPENAI_API_KEY=your_copied_key_here
   AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
   AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
   ```

---

## Service 2: Azure AI Document Intelligence (Required)

### Cost: F0 Free Tier - 500 pages/month (limited to 2 pages per request)

### Step-by-Step Setup:

1. **Create Document Intelligence Resource**
   - In Azure Portal, click "Create a resource"
   - Search for "Document Intelligence" or "Form Recognizer"
   - Click "Create"

2. **Fill in Details**
   - **Subscription**: Your subscription
   - **Resource group**: Use same as OpenAI (e.g., "rg-document-qa")
   - **Region**: Choose a region (same as OpenAI recommended)
   - **Name**: Enter unique name (e.g., "my-docintel-service")
   - **Pricing tier**: Select **"Free F0"** (500 pages/month)
   - Click "Review + Create" → "Create"

3. **Get Credentials**
   - After creation, go to your Document Intelligence resource
   - Click "Keys and Endpoint" in left menu
   - Copy:
     - **Endpoint**: `https://your-name.cognitiveservices.azure.com/`
     - **KEY 1**: Copy the entire key

4. **Add to .env file**:
   ```env
   DOCINTEL_ENDPOINT=https://your-name.cognitiveservices.azure.com/
   DOCINTEL_KEY=your_copied_key_here
   DOCINTEL_PAGE_WINDOW=2
   ```

**Note**: F0 tier only processes first 2 pages per request. The app handles this automatically by splitting documents.

---

## Service 3: Azure AI Search (Required)

### Cost: F1 Free Tier (up to 50 MB storage, 10K documents)

### Step-by-Step Setup:

1. **Create AI Search Resource**
   - In Azure Portal, click "Create a resource"
   - Search for "Azure AI Search" or "Cognitive Search"
   - Click "Create"

2. **Fill in Details**
   - **Subscription**: Your subscription
   - **Resource group**: Use same (e.g., "rg-document-qa")
   - **Service name**: Enter unique name (e.g., "my-search-service")
   - **Location**: Choose a region
   - **Pricing tier**: Click "Change Pricing Tier" → Select **"Free F1"**
   - Click "Review + Create" → "Create"

3. **Get Credentials**
   - After creation, go to your AI Search resource
   - Click "Keys" in left menu under Settings
   - Copy:
     - **URL**: `https://your-search-name.search.windows.net`
     - **Primary admin key**: Copy the entire key

4. **Add to .env file**:
   ```env
   SEARCH_ENDPOINT=https://your-search-name.search.windows.net
   SEARCH_KEY=your_copied_admin_key_here
   SEARCH_INDEX_NAME=insurance-chunks
   ```

**Note**: F1 tier supports hybrid search but NOT semantic ranker. The app will work fine without it.

---

## Service 4: Azure Blob Storage (Optional)

### Cost: Free tier available (5 GB storage + limited transactions)

### Step-by-Step Setup:

1. **Create Storage Account**
   - In Azure Portal, click "Create a resource"
   - Search for "Storage account"
   - Click "Create"

2. **Fill in Details**
   - **Subscription**: Your subscription
   - **Resource group**: Use same (e.g., "rg-document-qa")
   - **Storage account name**: Enter unique name (e.g., "mydocqastorage") - must be lowercase, no hyphens
   - **Region**: Choose same region
   - **Performance**: Standard
   - **Redundancy**: LRS (Locally-redundant storage) - cheapest option
   - Click "Review + Create" → "Create"

3. **Create Containers**
   - Go to your Storage Account
   - Click "Containers" in left menu under "Data storage"
   - Click "+ Container" twice to create:
     - Container 1: Name = `originals`, Access level = Private
     - Container 2: Name = `extracts`, Access level = Private

4. **Get Connection String**
   - In your Storage Account, click "Access keys" in left menu
   - Under "key1", click "Show" next to "Connection string"
   - Click the copy icon to copy the entire connection string

5. **Add to .env file**:
   ```env
   BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...your_copied_connection_string
   BLOB_CONTAINER_ORIGINALS=originals
   BLOB_CONTAINER_EXTRACTS=extracts
   ```

**Note**: If you skip this, the app will use local `./data` folder instead (works fine for development).

---

## Complete .env File Template

Create a file named `.env` in the `use-case-1-document-qa` directory with this content:

```env
# ── Azure OpenAI ──────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT=https://YOUR-OPENAI-NAME.openai.azure.com/
AZURE_OPENAI_API_KEY=your_openai_key_here
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
EMBED_DIMENSIONS=1536

# ── Azure AI Document Intelligence ────────────────────────────────────────────
DOCINTEL_ENDPOINT=https://YOUR-DOCINTEL-NAME.cognitiveservices.azure.com/
DOCINTEL_KEY=your_docintel_key_here
DOCINTEL_PAGE_WINDOW=2

# ── Azure AI Search ───────────────────────────────────────────────────────────
SEARCH_ENDPOINT=https://YOUR-SEARCH-NAME.search.windows.net
SEARCH_KEY=your_search_admin_key_here
SEARCH_INDEX_NAME=insurance-chunks

# ── Azure Blob Storage (optional) ─────────────────────────────────────────────
BLOB_CONNECTION_STRING=your_blob_connection_string_here
BLOB_CONTAINER_ORIGINALS=originals
BLOB_CONTAINER_EXTRACTS=extracts

# ── App behaviour ─────────────────────────────────────────────────────────────
DATA_DIR=./data
CHUNK_MAX_TOKENS=512
CHUNK_OVERLAP_TOKENS=80
TOP_K=5
COMPARE_K_PER_DOC=4
COMPARE_MAX_DOCS=8
RRF_FLOOR=0.01
API_BASE_URL=http://localhost:8000
```

---

## Quick Verification Checklist

After setting up all services, verify:

- [ ] Azure OpenAI resource created with both deployments (chat + embedding)
- [ ] Document Intelligence resource created (F0 tier)
- [ ] AI Search resource created (F1 tier)
- [ ] (Optional) Storage Account created with two containers
- [ ] All credentials copied to `.env` file
- [ ] `.env` file is in the `use-case-1-document-qa` directory (NOT the parent folder)

---

## Cost Management Tips

1. **Set up Budget Alerts**:
   - Go to Azure Portal → "Cost Management + Billing"
   - Click "Budgets" → "Add"
   - Set a monthly budget (e.g., $10)
   - Configure email alerts at 80% and 100%

2. **Monitor Usage**:
   - Free tiers limits:
     - Document Intelligence F0: 500 pages/month
     - AI Search F1: 50 MB storage
     - Blob Storage: 5 GB storage + limited transactions
   - Azure OpenAI uses your $200 credit

3. **Delete Resources When Done**:
   ```bash
   az group delete --name rg-document-qa --yes
   ```

---

## Troubleshooting

### Issue: "Model deployment quota exceeded"
- **Solution**: Some regions have limited quota. Try a different region or request quota increase in Azure OpenAI Studio.

### Issue: "Resource name already exists"
- **Solution**: Azure resource names must be globally unique. Add numbers or your initials to the name.

### Issue: "Subscription not registered for Microsoft.CognitiveServices"
- **Solution**: Go to Subscriptions → Resource providers → Find "Microsoft.CognitiveServices" → Click "Register"

### Issue: Cannot find "Free F0" pricing tier
- **Solution**: Some regions don't offer free tier. Try creating in different regions: East US, West Europe, or West US.

---

## Alternative: Using Azure CLI (Advanced)

If you prefer command-line setup:

```bash
# Login
az login

# Set variables
RG="rg-document-qa"
LOCATION="eastus"
OPENAI_NAME="my-openai-$(date +%s)"
DOCINTEL_NAME="my-docintel-$(date +%s)"
SEARCH_NAME="my-search-$(date +%s)"

# Create resource group
az group create --name $RG --location $LOCATION

# Create Azure OpenAI
az cognitiveservices account create \
  --name $OPENAI_NAME \
  --resource-group $RG \
  --kind OpenAI \
  --sku S0 \
  --location $LOCATION

# Create Document Intelligence
az cognitiveservices account create \
  --name $DOCINTEL_NAME \
  --resource-group $RG \
  --kind FormRecognizer \
  --sku F0 \
  --location $LOCATION

# Create AI Search
az search service create \
  --name $SEARCH_NAME \
  --resource-group $RG \
  --sku free \
  --location $LOCATION

# Get keys (run these after creation completes)
az cognitiveservices account keys list --name $OPENAI_NAME --resource-group $RG
az cognitiveservices account keys list --name $DOCINTEL_NAME --resource-group $RG
az search admin-key show --service-name $SEARCH_NAME --resource-group $RG
```

---

## Next Steps

After completing this setup:

1. **Verify your .env file** is properly configured
2. **Install dependencies**: 
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the smoke test**:
   ```bash
   python scripts/smoke_test.py
   ```
4. **Start the application**:
   ```bash
   # Terminal 1 - Backend
   uvicorn src.api.main:app --reload
   
   # Terminal 2 - Frontend
   streamlit run frontend/app.py
   ```

---

## Support

If you encounter issues:
- Check the [Azure documentation](https://learn.microsoft.com/en-us/azure/)
- Review error messages in the console
- Ensure all service names are globally unique
- Verify your Azure subscription has available credit
- Check that services are created in supported regions

Good luck with your setup! 🚀
