# Deploy Free Embedding Model in Azure AI Foundry

You've deployed **Kimi k2.6** for chat (great!), but you also need an **embedding model** for document search.

## What You Need to Deploy

**Embedding Model Options (Choose ONE):**

### Option 1: text-embedding-3-small (OpenAI - May Need Credits)
- Most compatible with the app
- May require Azure OpenAI credits

### Option 2: Cohere Embed v3 (FREE Serverless)
- FREE serverless deployment
- Good alternative if OpenAI models require credits

---

## Steps to Deploy Embedding Model

### 1. Go to Azure AI Foundry
https://ai.azure.com/ → Your project: **document-qa-project**

### 2. Navigate to Deployments
Click **"Deployments"** in the left menu

### 3. Deploy an Embedding Model

Click **"+ Deploy model"** or **"+ Create deployment"**

#### Try Option 1 First: text-embedding-3-small
1. Search for: **"text-embedding-3-small"**
2. If found, select it
3. Deployment name: `text-embedding-3-small`
4. Click **"Deploy"**

**If it says "requires credits" or "not available"**, try Option 2:

#### Option 2: Cohere Embed v3 (Free Alternative)
1. Click **"Model catalog"** or **"Browse models"**
2. Filter by: **"Embeddings"** or search: **"Cohere"**
3. Select: **"Cohere Embed v3"** or **"Cohere Embed v3 - Multilingual"**
4. Click **"Deploy"** (serverless)
5. Deployment name: `cohere-embed-v3`
6. Click **"Deploy"**

---

## Update Your .env File

### If you deployed text-embedding-3-small (Option 1):
✅ Your `.env` is already correct - no changes needed!

### If you deployed Cohere Embed v3 (Option 2):
Update your `.env` file:
```env
AZURE_OPENAI_EMBED_DEPLOYMENT=cohere-embed-v3
EMBED_DIMENSIONS=1024
```

**Also update the config.py file** (I'll do this for you if needed)

---

## Why Do You Need an Embedding Model?

The Document Q&A app works like this:
1. **Upload PDF** → Extract text
2. **Embedding Model** → Convert text to numbers (vectors) for search
3. **Search** → Find relevant sections when you ask a question
4. **Chat Model (Kimi)** → Generate answer based on found sections

**Without embeddings**, the app can't search your documents effectively!

---

## Check What's Deployed

After deploying, you should see in the Deployments list:

```
Deployment Name              Model                Status
----------------------------------------------------------
Kimi-k2.6                    Kimi k2.6           ✅ Deployed
text-embedding-3-small       text-embedding...   ✅ Deployed
(or cohere-embed-v3)
```

---

## Test the Configuration

After deploying the embedding model, run:

```bash
.venv\Scripts\python.exe check_deployments.py
```

Expected output:
```
✅ Chat deployment is working! (Kimi k2.6)
✅ Embedding deployment is working!
✅ All deployments are ready!
```

---

## If Cohere Doesn't Work

Some free serverless models have limitations. If Cohere embeddings don't work with the app, you have these options:

1. **Use a small amount of Azure OpenAI credit** for text-embedding-3-small
   - Embeddings are VERY cheap (< $0.50 for the whole project)
   - Chat with Kimi is free, so you'd only pay for embeddings

2. **Try other free embedding models** in the catalog:
   - Look for "Embeddings" category in Model Catalog
   - Try any serverless embedding model

3. **Modify the app** to use a different embedding approach (more complex)

---

## Recommended Path

1. ✅ You have Kimi k2.6 for chat (FREE)
2. 👉 Deploy **text-embedding-3-small** if available
3. 👉 If not, deploy **Cohere Embed v3** (FREE)
4. 👉 Update .env if using Cohere
5. 👉 Test with check_deployments.py
6. 🚀 Start the app!

The embeddings cost is minimal (~$0.10-0.50 total), and Kimi k2.6 keeps your chat costs at $0!

---

Let me know which embedding model you deployed and I'll help configure it! 🚀
