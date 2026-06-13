# Setup Guide

Everything you need to provision Azure, configure credentials, and run the
Insurance Document Intelligence system locally. Two provisioning paths are
documented — pick the one that matches your budget.

---

## 1. Prerequisites

- **Python 3.11+**
- An **Azure account** (free account / $200 trial is enough — this project runs for **< $1**)
- **Azure CLI** (`az`) for the automated path, or access to **[Azure AI Foundry](https://ai.azure.com/)** for the free serverless path
- ~5 minutes

---

## 2. Provision Azure resources

### Path A — Free serverless (recommended, ~$0) ⭐

This is the path used for the reference deployment. Chat runs on a **free
serverless model**, so the only (tiny) cost is embeddings.

| Service | Tier | Cost | What you deploy |
|---|---|---|---|
| Azure AI Foundry — chat | Serverless | **Free** | A chat model deployment (e.g. `Kimi-k2.6`) — a free GPT‑4o‑*equivalent* (see note below) |
| Azure OpenAI — embeddings | Standard | ~$0.10–0.50 total | `text-embedding-3-small` (1536‑dim) |
| Azure AI Document Intelligence | **F0** | **Free** (500 pages/mo) | `prebuilt-layout` |
| Azure AI Search | **Free (F1)** | **Free** | one index (`insurance-chunks`) |
| Azure Blob Storage | Standard LRS | **Free** (12 mo) | containers `originals`, `extracts` *(optional — falls back to local disk)* |

**Steps (Azure AI Foundry portal):**
1. Create a project at <https://ai.azure.com/>.
2. **Deployments → + Deploy model →** deploy a free serverless **chat** model. Note its **deployment name** and **endpoint**.
3. Deploy **text-embedding-3-small** (embeddings).
4. Create **Document Intelligence (F0)** and **Azure AI Search (Free)** resources in the [Azure Portal](https://portal.azure.com).
5. (Optional) Create a Storage account and run `python scripts/setup_blob_containers.py` to create the containers.

> **Why a non‑OpenAI chat model is allowed.** The assignment permits free‑tier
> substitutions (§10) and asks for "GPT‑4o **or equivalent**" (§5). Azure OpenAI
> GPT‑4o is *paid*; a free serverless chat model on Azure AI Foundry is an
> equivalent chat‑completions model on Azure. The code auto‑detects model
> capabilities, so it works with either — see the README.

### Path B — Automated, Azure OpenAI everywhere (~<$5)

If you have credit and want GPT‑4o‑mini for chat too, one script provisions
everything:

```bash
az login
bash infra/provision.sh [resource-group] [region]   # defaults: rg-docqa-demo eastus
```

It prints every value you need to paste into `.env`, and a teardown command at the end.

---

## 3. Configure `.env`

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Key variables (full list and comments are in [.env.example](../.env.example)):

```env
# Chat model (Foundry serverless OR Azure OpenAI) — point these at your deployment
AZURE_OPENAI_ENDPOINT=https://<your-resource>.services.ai.azure.com/   # or https://<aoai>.openai.azure.com/
AZURE_OPENAI_API_KEY=<key>                 # leave empty to use DefaultAzureCredential (az login / managed identity)
AZURE_OPENAI_CHAT_DEPLOYMENT=<your-chat-deployment-name>
AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
EMBED_DIMENSIONS=1536

# Document Intelligence (F0 free tier analyses only the first 2 pages/request)
DOCINTEL_ENDPOINT=https://<your-docintel>.cognitiveservices.azure.com/
DOCINTEL_KEY=<key>
DOCINTEL_PAGE_WINDOW=2          # the windowed splitter that defeats the F0 2-page cap; set 0 on paid S0

# Azure AI Search (Free F1: hybrid search yes, semantic ranker no)
SEARCH_ENDPOINT=https://<your-search>.search.windows.net
SEARCH_KEY=<admin-key>
SEARCH_INDEX_NAME=insurance-chunks

# Blob (optional — omit to use local ./data)
BLOB_CONNECTION_STRING=
```

**Security:** never commit `.env` (it is git‑ignored). Leave any `*_KEY` blank to
authenticate keylessly via `DefaultAzureCredential` (`az login` locally, managed
identity in the cloud).

---

## 4. Install & run

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

python scripts/make_samples.py          # (optional) generate demo insurance documents
python scripts/smoke_test.py            # verify Azure connectivity before launching
```

Run the two processes (Windows users can double‑click `START_APP.bat` instead):

```bash
# Terminal 1 — backend (drop --reload for a faster, demo-grade start)
uvicorn src.api.main:app

# Terminal 2 — frontend
streamlit run frontend/app.py
```

Open **<http://localhost:8501>**. Backend API docs live at **<http://localhost:8000/docs>**.

---

## 5. Free‑tier limitations (documented per assignment §10)

| Limitation | Impact | How the code handles it |
|---|---|---|
| Document Intelligence **F0** analyses only the first **2 pages** per request | Multi‑page PDFs would silently truncate | PDFs are split into 2‑page windows, analysed in parallel, and merged with corrected page offsets ([extractor.py](../src/ingestion/extractor.py)). A truncation guard aborts rather than answer from partial text. |
| Azure AI Search **Free (F1)** has **no semantic ranker** | Can't use Azure's L2 semantic rerank | Relevance comes from **hybrid BM25 + vector + RRF** fusion, which the free tier fully supports. *(A free Cohere Rerank serverless deployment can be wired in as an optional L2 reranker — see README → Future improvements.)* |
| F1 Search caps storage (~50 MB) | Limits corpus size | Vectors are stored `false` (never read back), halving index storage. |
| In‑memory session history | Lost on backend restart | Documented demo‑scope choice; production would use Cosmos DB. |

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Backend won't start | Check port 8000 is free; confirm `.env` exists; run `python scripts/smoke_test.py`. |
| Frontend won't start | Backend must be up first; try `streamlit run frontend/app.py --server.port 8502`. |
| Documents stuck "processing" | Check the backend log; verify DI page quota (500/mo on F0). |
| "Insufficient context" answers | Ensure the document status is **Ready**; ask more specific questions. |
| **`CERTIFICATE_VERIFY_FAILED` on every Azure call** | You're behind a TLS-intercepting corporate proxy whose root CA isn't trusted by Python. **Proper fix:** obtain your corporate root CA (`.crt`) from IT and either add it to the OS trust store (`sudo cp corp-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates`) then set `export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=$SSL_CERT_FILE`, **or** append it to certifi's bundle. **Quick local-demo unblock:** set `VERIFY_SSL=false` in `.env` (disables certificate verification — never use in production). Also confirm the network/firewall actually allows `*.search.windows.net`, `*.blob.core.windows.net` and `*.cognitiveservices.azure.com`. |

Teardown (automated path): `az group delete -n <resource-group> --yes --no-wait`.
