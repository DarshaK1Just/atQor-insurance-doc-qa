# UC1 — Intelligent Document Processing & Q&A System
## Elite Solution Plan (Research → Options → Decision → Design → Build Steps)

> **Companion doc:** `ARCHITECTURE_DESIGN_REVIEW.md` — the Principal-Architect design review (full brainstorm, decision matrix, security/scaling/deployment design, decision register, interview Q&A prep). Read that first; this file is the build plan.
> **v3 — ZERO-BUDGET CONSTRAINT (BINDING):** no paid subscription. See design review §9 for the full free-tier architecture. Summary: Azure Free Account **$200/30-day credit** covers Azure OpenAI (total spend < $5, gpt-4o-mini + text-embedding-3-small, client-side query embedding); **Document Intelligence F0** (free) + **2-page-window PDF splitter** with page-offset merge (F0 only analyzes first 2 pages — splitter defeats the trap; assertion guards it); **Azure AI Search Free (F1)** — hybrid BM25+vector+RRF works, **no semantic ranker** → refusal gate becomes LLM-self-assessed `insufficient_context` via Structured Outputs (+ RRF floor pre-check); citation snippets from cited-chunk `quote` instead of semantic captions; host locally. Day 0.5 provisioning accordingly: DI **F0**, Search **F1**, AOAI gpt-4o-mini + 3-small only. Semantic-ranker gate + vectorizer + Basic tier remain in README as the documented "with full access" design (single config flag).
>
> **v2 updates from the design review:** (1) rewrite + intent are ONE structured-output LLM call returning `{standalone_query, intent}`; (2) page-count assertion after extraction (detects the DI F0 2-page trap); (3) comparison fan-out caps: k≤4 chunks/doc, ≤8 docs; (4) golden set must include 2 unanswerable + 2 follow-up-chain questions; (5) demo video must show the refusal case and the rewritten-query log line; (6) README embeds the Decision Register + production-path sections from the design review.

> Assignment: atQor AI Engineer take-home, 5 working days.
> Scoring: Architecture & Design **25%** + RAG Implementation **25%** + Code Quality **20%** + Azure Integration **15%** + UX **15%**.
> Strategy: **Architecture + RAG = 50% of the grade.** Every decision below is optimized to showcase architectural judgment, and to put ALL intelligence in Azure AI services — Python stays a thin, legible orchestration layer (no hand-rolled heuristics).

---

# PART 1 — What the assignment is really testing

Reading between the lines of the document:

1. **"Justify your choice"** appears explicitly for chunking — they want documented trade-off analysis, not just working code.
2. **"We value design thinking and clean architecture over feature completeness"** — a well-argued README + architecture diagram is worth more than extra features.
3. The 4 sample test scenarios are the hidden rubric:
   - Multi-page policy PDF Q&A → tests **layout-aware extraction + retrieval relevance**
   - Scanned claim form image → tests **OCR path (images, not just digital PDFs)**
   - "Does *it* also cover pre-existing conditions?" → tests **multi-turn coreference resolution**
   - "Compare deductible clauses across **all** uploaded policies" → tests **multi-document retrieval** (naive top-k RAG fails this — one verbose policy crowds out the others)
4. Citations must be **clickable** back to source document + page number — page-level metadata must survive the whole pipeline.

**Your positioning (the "how I think" story):** every stage that requires intelligence is delegated to an AI model/service; every stage that is plumbing is thin, typed, testable Python. The skill being demonstrated is *knowing where intelligence belongs*.

---

# PART 2 — Options analysis (the research)

## 2.1 Document extraction — 4 options

| Option | What it is | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. DI `prebuilt-read`** | OCR only ($1.50/1k pages) | Cheapest | No tables, no headings, no KV pairs — kills citation/section quality | ❌ Too weak |
| **B. DI `prebuilt-layout` v4.0 (API `2024-11-30`) with Markdown output** | Full layout analysis: Markdown w/ headings, HTML tables, KV pairs (opt-in), page numbers + bounding polygons for every element; one API covers PDF + DOCX + JPEG/PNG/TIFF | Exactly matches assignment's required service; structure detection is done by the AI model (not Python); page spans enable precise citations; F0 free tier exists | $10/1k pages on S0; F0 free tier analyzes **only first 2 pages** per doc (hidden gotcha — call it out!) | ✅ **SELECTED** |
| **C. Azure AI Content Understanding** (GA Nov 2025) | Newer multimodal Foundry service, zero-shot field extraction | Microsoft's forward direction; richer | **No free tier**, needs Foundry resource + model deployment, fewer examples, riskier in 5 days | ❌ Mention as future path |
| **D. Azure AI Search built-in skillset** (Document Layout skill + integrated vectorization) | Search indexer runs DI + chunking + embedding for you | Zero ingestion code | **Markdown mode loses page numbers; text mode loses headings** (awkward for citations); >20 docs/day needs billable attach; 5-min/doc skill timeout; hides your engineering skill — the thing being graded | ❌ Mention as managed alternative |

**Decision: B.** `prebuilt-layout`, `outputContentFormat=markdown`, called from your own ingestion service (push model). Optional flourish: route detected claim invoices to `prebuilt-invoice` for structured fields — shows you know the prebuilt model catalog.

**Citation-grade page mapping (the elite detail):** DI returns one continuous Markdown `content` string, but `pages[].spans` gives each page's `{offset, length}` window into that same string. Compute each chunk's character offset → binary-search which page span(s) it overlaps → exact `page_start`/`page_end` per chunk. (Simpler fallback: count `<!-- PageBreak -->` delimiters.) This span-mapping is the difference between "citations" and "citations that actually open the right page."

DOCX caveat to document: layout treats 3,000 chars = 1 "page" for Office formats and gives no bounding polygons (digital text, no OCR needed) — handle gracefully.

## 2.2 Chunking — 3 options (assignment explicitly demands justification)

| Strategy | Pros | Cons |
|---|---|---|
| **(a) Pure structural** (split on DI Markdown headings) | Semantically coherent; heading = free citation metadata | Sections can be huge (blows context) or tiny (weak embeddings) |
| **(b) Fixed sliding window** (e.g., 512 tokens / 25% overlap) | Trivial, uniform | Severs sentences/tables mid-way; chunks lose "where am I" context — fatal for policy tables (a coverage limit table is meaningless without its section heading) |
| **(c) Hybrid: structure-first, size-capped** | Best of both — Microsoft's own documented pattern | Slightly more code |

**Decision: (c) Hybrid** — and this is the *AI-native* answer because the structure detection itself comes from the Document Intelligence model:
1. Split DI Markdown on headings H1–H3 (`MarkdownHeaderTextSplitter` from `langchain-text-splitters` as a standalone micro-dependency, or ~40 lines equivalent).
2. Size-cap oversized sections at **~512 tokens with ~15–25% overlap** (token-counted via tiktoken, per Microsoft's recommended starting point: 512 tokens ≈ 2,000 chars, 128-token overlap).
3. **Tables are never split** — each table becomes its own chunk, kept in Markdown/HTML form (LLMs reason over Markdown tables far better than flattened text).
4. Every chunk gets the **heading breadcrumb prepended** ("Policy Schedule > Section 4 > Outpatient Benefits") — prevents context loss for mid-document chunks and improves both embedding quality and citation display.
5. Per-chunk metadata: `doc_id, doc_name, doc_type, page_start, page_end, heading_path, upload_ts` (via the span-mapping above).

## 2.3 Retrieval architecture — the ladder (show all 4, ship #3+#4)

| Architecture | Exact-term queries (policy #s, "$500 deductible") | Precision | Cost | Verdict |
|---|---|---|---|---|
| 1. Vector-only | ❌ fails on IDs/numbers/jargon | weak | embeddings only | baseline — discuss, don't ship |
| 2. Hybrid (BM25 + vector + RRF) | ✅ | good | free | minimum credible bar |
| 3. **Hybrid + Semantic Ranker (L2 reranker)** | ✅ | **best per MS benchmarks** | 1,000 free reranked queries/mo (needs Basic tier) | ✅ **SHIP** |
| 4. **+ LLM query decomposition for comparisons** | ✅ | covers multi-doc intent | 1 extra LLM call | ✅ **SHIP** |
| 5. Agentic retrieval / knowledge bases (GA in REST `2026-04-01`, "Foundry IQ") | ✅ | managed query planning | ~$0.002/query, black-box | discuss as evolution path |

**Decision: Hybrid + semantic ranker + own LLM-driven query layer.** Key details:
- Single request carries `search` (BM25) + `vectorQueries` (HNSW, k=50 — required when semantic ranker is on); merged via Reciprocal Rank Fusion; then `queryType=semantic` reranks top-50 with a cross-encoder, returning a **calibrated `@search.rerankerScore` (0–4)**.
- **Use the rerankerScore as a groundedness gate**: if no chunk scores ≥ ~1.5–2.0, the system *refuses to answer* ("I don't have enough information in the uploaded documents") instead of hallucinating. This is a principled, model-driven "I don't know" — a huge rubric signal.
- **Query-time vectorizer** (Azure OpenAI vectorizer on the index): the *search service itself* embeds the query — one less client call, guaranteed same model index/query, demoable in the portal. Ingestion-side embedding stays in your code (you control chunk metadata).
- Semantic captions (extractive highlights) come back free with the reranker → perfect citation snippets for the UI.

**Multi-document comparison ("compare deductibles across all policies"):** naive top-k fails. Implement **LLM intent classification → facet query on `doc_name` to enumerate documents (zero extra infra) → parallel per-document filtered hybrid sub-queries → structured comparison synthesis** (markdown table answer with per-document citations). This is the Azure Architecture Center's documented decomposition pattern, ~30 lines you can fully defend — vs. agentic retrieval which does it managed but black-box. The intent detection is itself an LLM call (AI-native, not Python regex).

## 2.4 Embeddings

| Model | Dims | Price /1M tokens | Verdict |
|---|---|---|---|
| ada-002 (named in assignment) | 1536 | ~$0.10 | legacy — *mention you know the assignment names it, then upgrade* |
| **text-embedding-3-small** | 1536 | **~$0.02** | ✅ **SELECTED** — beats ada on MTEB at 1/5 price |
| text-embedding-3-large | 3072 (MRL-truncatable) | ~$0.13 | scale-up path; mention MRL `truncationDimension` + binary quantization |

The assignment says "ada-002 **or equivalent**" — choosing 3-small *with the comparison table in the README* shows current knowledge.

## 2.5 Multi-turn conversation — 3 options

| Option | Verdict |
|---|---|
| Send raw chat history to retriever | ❌ pollutes the embedding; "it" never resolves |
| Azure AI Search built-in `queryRewrites` (semantic ranker feature) | ❌ still preview AND not conversation-aware (paraphrases current query only) — knowing this is a currency signal |
| **LLM query rewriting**: GPT-4o condenses (history + new question) → standalone search query, via structured output | ✅ **SELECTED** — the canonical pattern from Microsoft's own azure-search-openai-demo |

Two-part flow: **rewritten standalone query → retrieval**, but **full recent history → answer-generation prompt** (keeps conversational tone). "What about the deductible for that same policy?" → rewritten to "What is the deductible for [Policy X]?" by the model — the LLM does coreference resolution, zero Python heuristics.

## 2.6 Answer generation — 2 options

| Option | Verdict |
|---|---|
| Azure OpenAI **On Your Data** (`data_sources` extension) — service-side retrieval + auto `[doc1]` citations | ❌ outsources chunking/retrieval/citations = outsources the 25% RAG grade; limited citation control; docs now label it "classic" |
| **Custom RAG loop** with grounded system prompt + **Structured Outputs** (JSON schema) | ✅ **SELECTED** |

Generation details:
- System prompt (azure-search-openai-demo canonical form): *"Answer ONLY from the numbered sources below. Every fact must carry its source id in brackets, e.g. [1][3] (never [1,3]). If the sources are insufficient, say you don't know."* Temperature ≤ 0.2.
- **Structured Outputs** (`response_format` JSON schema / Pydantic `.parse()`): return `{answer_markdown, citations: [{source_id, doc_name, page, quote}], insufficient_context: bool}` — the UI renders clickable citations deterministically; no regex parsing of prose. The model emits the citation structure — AI-native again.

## 2.7 Orchestration framework — 5 options (this is a big judgment signal)

| Option | Status mid-2026 | Verdict |
|---|---|---|
| **Plain Azure SDKs** (`azure-ai-documentintelligence`, `azure-search-documents`, `openai`) | GA, stable | ✅ **SELECTED** — every RAG decision visible to the grader; custom RAG loop is ~200 lines |
| LangChain / LangGraph | LC in maintenance mode; LangGraph overkill for linear RAG | ❌ (borrow only `langchain-text-splitters` for the markdown splitter) |
| Semantic Kernel | mid-merge into Microsoft Agent Framework | ❌ abstraction without value here |
| Azure AI Foundry Agent Service (file search) | GA | ❌ black-boxes exactly what's being graded |
| Prompt Flow | **RETIRED** (dev ended Apr 2026, gone Apr 2027) | ❌ — citing its deprecation in README is itself a currency signal |

One README line each on *why rejected* = the engineering-judgment paragraph reviewers remember. Frameworks hide the decisions the rubric rewards.

## 2.8 Ingestion pipeline shape

- **Build:** FastAPI `POST /documents` → `202 Accepted + document_id` → background task (async) runs: Blob upload → DI analyze (async LRO poller) → chunk → embed → index upsert; status machine `uploaded → extracting → chunking → indexing → ready | failed` persisted per document; `GET /documents/{id}` for polling (assignment requires status tracking). Batch = N parallel background tasks with bounded concurrency (semaphore).
- **Describe, don't build:** production path = Blob → Event Grid → Azure (Durable) Functions fan-out with retries + queue-based load leveling. Design the `IngestionPipeline` as an interface so the in-process implementation is swappable — that's the architecture-points move, stated in one diagram annotation.

## 2.9 The differentiator almost nobody includes: RAG evaluation harness

`azure-ai-evaluation` SDK — **Groundedness, Relevance, Retrieval** evaluators (LLM-as-judge, 1–5 scores), run locally against a 12–15 question golden set over your sample policies; results table in the README. Half a day of work, scores across three rubric rows (RAG + Code Quality + Azure Integration). The "AI evaluating AI" framing completes your AI-native story.

---

# PART 3 — Selected architecture (the design)

## 3.1 Final stack

| Layer | Choice | Azure service does the intelligence |
|---|---|---|
| Storage | Azure Blob Storage (originals + DI JSON for citation deep-links) | — |
| Extraction | DI `prebuilt-layout` v4.0, Markdown output, span→page mapping | layout/OCR/table/heading detection |
| Chunking | Structure-first (DI headings) + 512-token cap, 15–25% overlap, tables whole, breadcrumb prepended | structure comes from the DI model |
| Index | Azure AI Search (Basic tier), hybrid index + semantic config + AOAI query vectorizer + freshness scoring profile | BM25 + HNSW + RRF + cross-encoder reranking + query embedding |
| Embeddings | text-embedding-3-small @1536, cosine | Azure OpenAI |
| Query layer | LLM query rewrite (multi-turn) + LLM intent router (single-doc vs comparison fan-out) | GPT-4o does coreference + planning |
| Generation | Custom RAG loop, grounded prompt, Structured Outputs citations, rerankerScore refusal gate | GPT-4o |
| API | FastAPI (async), Pydantic models/settings, structured JSON logging w/ correlation IDs | — |
| Frontend | Streamlit (fast) or minimal React (if time) — chat + upload + status + clickable citation panel | — |
| Auth | `DefaultAzureCredential` (Entra ID / keyless) everywhere, key fallback via env | — |
| Eval | `azure-ai-evaluation` Groundedness/Relevance/Retrieval | LLM judge |

## 3.2 Data flow

```
                         ┌─────────────────────────────────────────────────┐
 INGESTION (async)       │                  QUERY (sync)                   │
                         │                                                 │
 upload (PDF/DOCX/img)   │  user question + chat history                   │
   │ 202 + doc_id        │     │                                           │
   ▼                     │     ▼                                           │
 Blob Storage ◄──────────┼── [GPT-4o] rewrite → standalone query           │
   │                     │     │                                           │
   ▼                     │     ▼                                           │
 [DI prebuilt-layout] ─► │  [GPT-4o] intent: simple ─────────┐             │
   markdown + page spans │           comparison → facet docs │             │
   │                     │           → per-doc fan-out       │             │
   ▼                     │     │                             ▼             │
 chunker (headings→cap)  │     ▼                                           │
   │  +page/heading meta │  [AI Search] hybrid (BM25+vector+RRF)           │
   ▼                     │     + semantic rerank + captions                │
 [AOAI embed 3-small]    │     │  rerankerScore < τ → refuse               │
   │                     │     ▼                                           │
   ▼                     │  [GPT-4o] grounded answer, Structured Outputs   │
 [AI Search] push upsert │     │ {answer, citations[{doc,page,quote}]}     │
                         │     ▼                                           │
 status: uploaded→...→ready   chat UI — clickable citations → Blob source  │
                         └─────────────────────────────────────────────────┘
```

## 3.3 Index schema (citation-grade)

| Field | Type | Attributes | Purpose |
|---|---|---|---|
| `chunk_id` | String | key | `{doc_id}_p{page}_c{n}` — stable citation anchor |
| `doc_id` / `doc_name` | String | filterable, facetable | comparison fan-out + citation display |
| `doc_type` | String | filterable, facetable | policy / claim form / medical report (LLM-classified at ingest — another AI-native touch) |
| `page_start`, `page_end` | Int32 | filterable, sortable | page-level citations |
| `heading_path` | String | searchable | section citations; semantic-config `title` slot |
| `content` | String | searchable, `en.microsoft` analyzer | grounding text; semantic-config `content` |
| `content_vector` | Collection(Single) 1536d | searchable, `stored:false` | vector leg (storage saver) |
| `upload_ts` | DateTimeOffset | filterable, sortable | freshness scoring profile (boost newest policy versions) |

## 3.4 Repo layout (matches the assignment's recommended structure)

```
use-case-1-document-qa/
├── src/
│   ├── ingestion/    # blob client, DI extractor, status store, pipeline orchestrator
│   ├── indexing/     # chunker (header split + token cap + table handling), index schema, push client
│   ├── retrieval/    # query rewriter, intent router, hybrid search, comparison fan-out, score gate
│   ├── generation/   # grounded prompt, structured-output models, RAG answer service
│   ├── api/          # FastAPI routes: /documents, /documents/{id}, /chat ; middleware: logging, errors
│   └── core/         # pydantic-settings config, azure clients factory (DefaultAzureCredential), logging
├── frontend/         # Streamlit chat UI
├── tests/            # pytest, Azure clients mocked; chunker golden tests
├── evals/            # golden_set.jsonl + evaluate.py (azure-ai-evaluation)
├── infra/            # provision.bicep or provision.sh (az cli) — reviewer-friendly
├── sample-documents/ # 2 policies (overlapping coverage, different deductibles), 1 scanned claim form, 1 DOCX medical report
├── README.md  ·  architecture.png  ·  .env.example  ·  requirements.txt
```

## 3.5 Technical-expectations checklist (Section 6 of assignment → concrete answer)

- **Error handling:** unsupported format → 415 with friendly message; DI failure/empty OCR → `failed` status + reason; empty retrieval / low rerankerScore → graceful "not in corpus" answer; Azure 429s → tenacity exponential backoff on every client.
- **Logging:** `structlog` JSON logs, one correlation ID per document and per chat turn, spans for each stage (upload→extract→chunk→index / rewrite→retrieve→generate) with timings — "trace the full pipeline" requirement, verbatim.
- **Config:** `pydantic-settings` + `.env.example` listing every endpoint/key/deployment name — reviewers plug in their own credentials (explicit assignment requirement).
- **Security:** `DefaultAzureCredential` first (Entra ID), key-based fallback via env; zero hardcoded secrets; RBAC roles documented in README.

---

# PART 4 — 5-day build plan

**Day 0.5 — Provision + skeleton**
Azure: resource group; Blob Storage; Document Intelligence **S0** (F0 only analyzes first 2 pages — document this trap); Azure AI Search **Basic** (~$2.5/day, unlocks semantic ranker; delete after demo); Azure OpenAI: `gpt-4o` + `text-embedding-3-small` deployments. Write `infra/provision.sh`. Repo skeleton, `core/` (settings, client factory, logging), CI lint (ruff + mypy).

**Day 1 — Ingestion vertical slice**
Blob upload → DI layout (markdown) → raw result persisted → status store + `/documents` endpoints. Prove the span→page mapping on a multi-page PDF early (this is the riskiest detail — de-risk it first). Create sample documents (2 policies with deliberately different deductibles/coverage tables, 1 scanned claim form image, 1 DOCX medical report).

**Day 2 — Chunking + indexing**
Hybrid chunker (header split → token cap → tables whole → breadcrumb prepend) with golden unit tests; index schema + vectorizer + semantic config + scoring profile (index-as-code, idempotent create); embed + push upsert. Verify in portal Search Explorer.

**Day 3 — RAG query path**
Hybrid + semantic retrieval; rerankerScore refusal gate; LLM query rewriter (multi-turn); grounded generation with Structured Outputs citations; `/chat` endpoint with session history. Test scenarios 1–3 from the assignment.

**Day 4 — Comparison fan-out + UI + eval**
Intent router + facet enumeration + per-doc parallel sub-queries + comparison synthesis (scenario 4). Streamlit UI: upload w/ status badges, chat, citation panel that opens the source page (Blob SAS link / cached page text). Eval harness + golden set; record scores.

**Day 5 — Polish + deliverables**
README (architecture diagram, *options-considered tables from Part 2 — this is your 25% architecture essay*, service justifications, setup, limitations & production path: Durable Functions ingestion, agentic retrieval/Foundry IQ, Content Understanding, Key Vault, App Insights). Record 5–7 min demo: 1.5 min architecture & decisions → 4 min live demo of all four sample scenarios incl. the refusal case → 1 min challenges (page-mapping trick, F0 trap, comparison fan-out). Cost table. Delete/stop billable resources after recording.

---

# PART 5 — The "talking points" that separate elite from good

1. **Page citations via span math, not guesswork** — DI `pages[].spans` offset mapping into the Markdown string.
2. **Refusal gate from calibrated rerankerScore** — principled hallucination control, not a prompt hope.
3. **Comparison queries via facet + per-document fan-out** — and why you hand-rolled it vs agentic retrieval (control, cost ~$0.002/q, explainability), while citing agentic retrieval as GA evolution path.
4. **3-small over ada-002 with MTEB/price table** — "or equivalent" clause exercised with evidence.
5. **No framework, and one line each on why** — incl. Prompt Flow's 2026 retirement.
6. **F0 Document Intelligence 2-page truncation trap** — documented in limitations (graders know it).
7. **Eval harness with numbers in the README** — AI judging AI; evaluation-driven development.
8. **Every intelligent step is a model** — layout (DI), classification (LLM), coreference (LLM rewrite), planning (LLM router), ranking (cross-encoder), synthesis (LLM), evaluation (LLM judge). Python is plumbing.
