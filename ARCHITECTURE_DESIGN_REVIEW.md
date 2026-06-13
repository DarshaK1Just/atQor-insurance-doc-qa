# UC1 — Intelligent Document Processing & Q&A System
# Principal AI Architect — Design Review Document

> **Author role:** Principal AI Architect / Azure AI Solutions Architect
> **Scope:** atQor AI Engineer take-home (5 days) — but designed as if for production sign-off, then consciously scoped down.
> **Companion docs:** `SOLUTION_PLAN.md` (build plan), this doc (design reasoning + interview prep).
> **Reviewed against Azure state as of June 2026** (API versions and GA statuses verified by research; sources in SOLUTION_PLAN.md).

---

# 1. Problem Deconstruction — what is actually being asked

## 1.1 The business problem (stated)
A mid-size insurer receives **thousands of mixed-format documents per week** (policies, claim forms, medical reports — PDF, scanned images, DOCX). The operations team manually extracts key information and answers internal questions about coverage, claim eligibility, and regulatory clauses. They want: automatic processing → structured extraction → natural-language Q&A over the corpus.

## 1.2 The expected outcome (stated)
A working prototype: ingestion pipeline with batch upload + per-document status → layout-aware extraction (Document Intelligence) → justified chunking → Azure AI Search hybrid index with metadata → RAG chat with **citations (doc + page + snippet, clickable)** → **multi-turn** with coreference resolution. Deliverables: repo + README + architecture diagram + 5–7 min demo video.

## 1.3 Hidden requirements (read between the lines)
1. **"Justify your choice"** (chunking) — they grade *documented trade-off analysis*, not just code.
2. **"Design thinking and clean architecture over feature completeness"** — a well-argued partial solution beats a feature-complete mess. The README *is* a graded artifact.
3. **The 4 sample scenarios are the hidden test suite:**
   - Multi-page policy Q&A → layout-aware extraction + retrieval precision
   - Scanned claim form → the OCR/image path must actually work (TIFF/JPEG, handwriting, checkboxes)
   - "Does **it** also cover pre-existing conditions?" → multi-turn coreference resolution
   - "Compare deductible clauses across **all** uploaded policies" → multi-document aggregation, where naive top-k RAG demonstrably fails (one verbose document crowds out the rest)
4. **Citations must be clickable** → page-level metadata must survive extraction → chunking → indexing → generation → UI. This is an end-to-end *data lineage* requirement, the hardest invariant in the system.
5. **Reviewers will run it with their own credentials** → config externalization isn't a nice-to-have, it's a functional requirement (`.env.example`, no hardcoded endpoints, provisioning script).
6. **Throttling/error handling named explicitly** → they will likely look for 429 retry handling and graceful degradation in code review.
7. **Insurance + medical reports** → PII/PHI sensitivity. Not graded explicitly, but raising it unprompted (data residency, abuse-monitoring opt-out, no-training guarantees) signals production maturity.

## 1.4 What the interviewer is really assessing (mapped to rubric)
| Rubric row | Weight | What it actually measures | Where I win it |
|---|---|---|---|
| Architecture & Design | 25% | Can you decompose, layer, and justify? Do you know what to build vs buy? | This document → README; options tables; interface-driven design |
| RAG Implementation | 25% | Do you understand retrieval *failure modes* (lexical misses, context loss, multi-doc crowding, hallucination) and counter each one? | Hybrid+rerank, structural chunking, refusal gate, comparison fan-out, eval harness |
| Code Quality | 20% | Production habits: typing, errors, logging, tests, separation | Thin typed services, mocked-client tests, structured logs |
| Azure Integration | 15% | Current, correct, idiomatic Azure usage (auth, SDKs, API versions) | DefaultAzureCredential, pinned API versions, exact RBAC roles, currency signals (Prompt Flow retired, agentic retrieval GA) |
| UX | 15% | Does the demo feel coherent? | Status badges, streaming answer, clickable citation panel, refusal messaging |

**Strategic conclusion:** 50% of the grade is *thinking*, not typing. The submission should read like a design review with a working reference implementation attached — which is exactly the inversion of how most candidates submit.

---

# 2. Solution-Approach Brainstorm — five candidate architectures

Before choosing components, evaluate whole-system shapes. All five satisfy the letter of the assignment; they differ in where intelligence lives and how much of the graded surface they expose.

### Approach 1 — "Zero-code managed": Azure AI Search skillset + Azure OpenAI "On Your Data"
Blob → AI Search indexer + Document Layout skill (DI inside the indexer) + integrated vectorization → chat via Azure OpenAI `data_sources` extension (service-side retrieval, auto `[doc1]` citations).
- **Pros:** Days of work → hours. Fully Azure-native. Built-in retry. Minimal code to review (also a con).
- **Cons:** Chunking is the Text Split skill (no real control → can't "justify your chunking strategy" beyond defaults). Page numbers and headings are mutually exclusive in the layout skill's two modes — citation quality is compromised at the core. On Your Data citation format is rigid; multi-turn rewriting is opaque; comparison queries unsupported. **Outsources the entire 25% RAG criterion to a black box.** >20 docs/day requires billable skillset attach; 5-min/doc skill timeout.
- **Production readiness:** high (managed). **Interview value: lowest.**

### Approach 2 — "Foundry Agent": Azure AI Foundry Agent Service with File Search tool
Upload files to managed vector store; agent handles retrieval + citations + threads (conversation state) natively.
- **Pros:** Least code of all; managed multi-turn; auto-citations; the "agentic" buzzword.
- **Cons:** No chunking control, no index schema, no page-level citation guarantee, no retrieval tuning. The four hidden scenarios are pass/fail at the service's mercy. Demonstrates *API consumption*, not *AI engineering*. Also drifts from the assignment's explicit service list (AI Search index with metadata fields is *required*).
- **Production readiness:** medium-high. **Interview value: low. Fails the explicit requirement to configure AI Search.**

### Approach 3 — "Custom RAG, raw SDKs" (control plane in my code, intelligence in Azure models)
My ingestion service calls DI layout (markdown) → my chunker (structure-first, size-capped, driven by DI's detected structure) → push to a hand-designed AI Search hybrid index (BM25+vector+RRF+semantic ranker, query-time vectorizer) → my query layer (LLM query rewrite for multi-turn; LLM intent router; per-document fan-out for comparisons) → grounded generation with Structured Outputs citations → FastAPI + Streamlit.
- **Pros:** Every graded decision is visible, tunable, and defensible. Page-span citation lineage fully controlled. Each RAG failure mode gets an explicit, explainable counter. Smallest dependency surface; easiest for reviewers to run.
- **Cons:** Most code to write (~but the RAG loop is only ~200 lines); I own retry/backoff and status tracking myself (acceptable: tenacity + a status store).
- **Production readiness:** medium as-built; high with the documented evolution path (§7).
- **Interview value: highest.**

### Approach 4 — Approach 3 + orchestration framework (LangChain/LangGraph or Semantic Kernel)
- **Pros:** Pre-built loaders/splitters/retrievers; fashionable.
- **Cons:** A linear RAG pipeline has no branching complexity to justify a graph framework. Frameworks hide exactly the decisions being graded. LangChain is in maintenance mode ("use LangGraph for agents"); Semantic Kernel is mid-merge into Microsoft Agent Framework; Prompt Flow is **retired** (dev ended Apr 2026). Dependency weight hurts reviewer-runnability.
- **Interview value: medium — and citing the framework landscape's 2026 churn as the rejection reason is itself a currency signal.**

### Approach 5 — Approach 3 + managed agentic retrieval (AI Search knowledge bases, "Foundry IQ")
Replace my query layer with AI Search's agentic retrieval (GA in REST `2026-04-01`): LLM query planning over chat history, parallel subqueries, per-subquery reranking, structured references.
- **Pros:** Genuinely the managed future of this exact pattern; conversation-aware; handles comparisons natively; ~$0.002/query.
- **Cons:** Black-box query planning ("automated and not customizable") — I can't *explain* the layer the rubric weights at 25%. Newer API surface = demo risk; region/tier constraints may block reviewers. Dual billing complexity.
- **Interview value: high as a discussed evolution path, risky as the primary implementation.**

---

# 3. Azure Service Deep Analysis — fit, misfit, alternatives (per layer)

## 3.1 Extraction layer
| Service/option | Fit | Misfit / risk | Verdict |
|---|---|---|---|
| **DI `prebuilt-layout` v4.0 (`2024-11-30`), markdown output** | One API for PDF+DOCX+JPEG/PNG/TIFF; headings, HTML tables, opt-in KV pairs; **`pages[].spans` offsets enable exact chunk→page mapping**; OCR incl. handwriting + selection marks (claim-form checkboxes) | $10/1k pages (S0); **F0 free tier silently analyzes only first 2 pages** (demo-killing trap); DOCX = synthetic pages (3,000 chars), no polygons | ✅ **Core choice** |
| DI `prebuilt-read` | $1.50/1k pages | No tables/headings/KVP — destroys citation & chunk quality | ❌ |
| DI prebuilt verticals (`prebuilt-invoice`, `prebuilt-healthInsuranceCard.us`) | Schema'd fields + confidence for claim invoices/cards | Per-doc-type, not general | ◐ Optional routing flourish; shows catalog knowledge |
| DI custom neural model | Trainable on the insurer's fixed claim-form template (≥5 labeled samples) | Days of labeling; overkill for 5 days | ◐ Production path mention |
| **Azure AI Content Understanding** (GA Nov 2025) | Microsoft's stated forward direction; zero-shot field schemas; multimodal | **No free tier**; needs Foundry resource + model deployment; fewer regions/examples; schedule risk | ◐ Future-path section |
| AI Search Document Layout skill | Zero ingestion code | **Markdown mode → no page numbers; text mode → no headings.** The citation requirement falls into exactly this gap | ❌ for this use case (and say precisely why — that's the architect answer) |

## 3.2 Retrieval layer (Azure AI Search)
| Capability | Use? | Reasoning |
|---|---|---|
| Hybrid (BM25 + HNSW vector, RRF fusion) | ✅ | Vector-only fails exact-term queries (policy numbers, "$500 deductible", drug names); BM25-only fails paraphrase ("outpatient" vs "ambulatory care"). Insurance queries are both kinds. |
| **Semantic ranker (L2 cross-encoder)** | ✅ | MS benchmarks: hybrid+semantic > either alone. Calibrated `@search.rerankerScore` (0–4) → **refusal gate** (< ~1.8 → "not in the documents") = principled hallucination control. Free ≤1,000 queries/mo. Needs **Basic tier+** (not Free) — a deliberate, documented ~$2.5/day spend. |
| Query-time **vectorizer** (AOAI embedding inside the service) | ✅ | Query embedding becomes the search service's job: one request, guaranteed same model index/query, demoable in portal Search Explorer. Ingestion-side embedding stays in my code (chunk-metadata control). |
| Scoring profile (freshness on `upload_ts`) | ✅ | Insurance reality: policy versions supersede each other. Quadratic freshness boost over P365D. Cheap, real-world signal. |
| `en.microsoft` analyzer | ✅ | Better English lemmatization than default Lucene for the BM25 leg. |
| Built-in `queryRewrites` | ❌ | Still preview AND **not conversation-aware** (paraphrases current query only) — it cannot resolve "that same policy". Knowing this distinction is a currency signal. |
| Agentic retrieval / knowledge bases | ❌ build / ✅ discuss | See Approach 5. |
| Integrated vectorization (indexing side) | ❌ | Text Split skill chunking is structure-blind; I need heading+page metadata per chunk. |

**Index design principle:** one search document per chunk (parent-child via `doc_id`), `doc_id`/`doc_type` filterable+facetable (enables comparison fan-out + faceted UI), vectors `stored:false` (50%+ storage saving; never need raw vectors back), `chunk_id = {doc_id}_p{page}_c{n}` as a stable citation anchor.

## 3.3 Generation & embeddings (Azure OpenAI)
| Decision | Choice | Alternatives rejected |
|---|---|---|
| Chat model | **GPT-4o** (assignment names it), temperature ≤0.2 | gpt-4o-mini for rewrite/intent calls (cheap, fast) — actually *adopted* for the helper calls; o-series reasoning models unneeded for grounded extraction-style answers |
| Embeddings | **text-embedding-3-small @1536** (~$0.02/M tokens, beats ada-002 on MTEB at 1/5 price) | ada-002 (assignment's example — legacy; "or equivalent" clause exercised with an evidence table); 3-large+MRL/quantization = scale path |
| Citation mechanics | **Structured Outputs** (JSON schema): `{answer_markdown, citations[{source_id, doc_name, page, quote}], insufficient_context}` | Regex-parsing `[1]` from prose (brittle Python string handling — exactly what I'm avoiding); On Your Data (rigid, "classic"-labeled) |
| Grounding prompt | azure-search-openai-demo canonical form: numbered sources, "answer ONLY from sources, cite every fact [n], say you don't know" | — |

## 3.4 Storage, API, UI
- **Blob Storage**: originals (citation deep-links via short-TTL SAS) + persisted DI JSON (reprocessing without re-paying extraction; auditability).
- **FastAPI** (async-native — DI LRO pollers and parallel fan-out are natively awaitable; Pydantic models shared API↔Structured Outputs).
- **Streamlit** frontend: chat + upload + status + citation panel. (React if time permits; UX is 15% — coherent beats fancy.)

---

# 4. Assumptions Challenged, Risks, Edge Cases

## 4.1 Assumptions I am deliberately challenging
| Common assumption | Challenge |
|---|---|
| "Vector search is the modern default" | Insurance queries are full of exact tokens (policy IDs, dollar amounts, ICD codes) where BM25 wins; hybrid is non-negotiable. |
| "ada-002 because the assignment says so" | It says "or equivalent" — choosing 3-small with evidence demonstrates judgment, not disobedience. |
| "More framework = more engineering" | Inverse here: a framework hides the graded decisions. The elite move is *less* abstraction, more explanation. |
| "Free tier everywhere for a take-home" | Two free-tier traps found in research: DI F0 analyzes **only first 2 pages**; AI Search Free has **no semantic ranker**. Spending ~$3/day deliberately, documented, is the cost-aware answer. |
| "Citations = telling the model to cite" | Citations are a *data lineage* problem (span→page math at ingestion) plus a *contract* problem (structured output schema), not a prompt problem. |
| "Multi-turn = send chat history to search" | Raw history pollutes retrieval; condense-to-standalone-query via LLM is the canonical pattern. |

## 4.2 Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DI F0 2-page truncation during reviewer's run | High if F0 | Silent wrong answers | Use S0; assert page count vs PDF page count; warn in README |
| Azure OpenAI 429s during demo | Medium | Demo stall | tenacity backoff honoring Retry-After; gpt-4o-mini for helper calls; pre-warm before recording |
| Reviewer's region lacks a model/feature | Medium | Can't run | Pin models/API versions in `.env.example` with tested regions; provisioning script with region parameter |
| Markdown chunk → page mapping off-by-one | Medium | Wrong-page citations (worse than none) | Golden unit tests on a known multi-page PDF; binary-search span overlap, store page *ranges* |
| Scanned form OCR quality (skew, handwriting) | Medium | Scenario 2 fails | DI handles rotation natively; test with a genuinely scanned image early (Day 1); confidence surfaced in status |
| Comparison fan-out token blow-up (N docs × k chunks) | Low-Med | Context overflow | Cap k per doc (3–4), cap docs (facet count guard), summarize-then-compare if >8 docs |
| Indirect prompt injection via uploaded document content | Low (demo), real (prod) | Answer manipulation | Prompt structure separates instructions/sources; production path: Prompt Shields (XPIA detection) — documented |
| Semantic ranker quota (1,000/mo free) exhausted | Low | Cost | Far above demo usage; noted in cost table |

## 4.3 Edge cases the design must absorb
- Empty/corrupt/password-protected file → `failed` status with reason, never a 500.
- Unsupported format (`.xls`, `.msg`) → 415 with friendly message listing supported types.
- Image-only PDF (no text layer) → DI OCRs it transparently — but verify, don't assume.
- Question with zero relevant corpus ("What's the weather?") → refusal gate answers honestly; *demo this on video* — refusing well is a feature.
- Two documents with the same filename → `doc_id` = UUID; filename is display metadata only.
- Follow-up that switches entities mid-conversation ("and the Gold plan?") → rewriter must re-resolve, not cache; covered in eval golden set.
- Very long single section (20-page exclusions list) → size-cap splitter guarantees bounded chunks; breadcrumb keeps context.
- DOCX page citations → synthetic pages (3,000 chars); cite section headings as primary anchor for DOCX, page for PDF/images — honest in UI.

---

# 5. Decision Matrix and Selection

Weights mirror the grading rubric (architecture-visibility folded into Architecture; reviewer-runnability matters because they test with their own credentials).

| Criterion (weight) | A1 Skillset+OYD | A2 Foundry Agent | **A3 Custom RAG, raw SDKs** | A4 +Framework | A5 +Agentic retrieval |
|---|---|---|---|---|---|
| Architecture visibility & justification depth (25) | 8 | 6 | **24** | 15 | 18 |
| RAG quality vs the 4 hidden scenarios (25) | 12 | 10 | **23** | 20 | 21 |
| Code quality surface to demonstrate (20) | 6 | 5 | **18** | 13 | 15 |
| Azure integration correctness/currency (15) | 12 | 9 | **14** | 11 | 13 |
| UX achievable in timebox (15) | 12 | 12 | **13** | 12 | 11 |
| **Total (100)** | 50 | 42 | **92** | 71 | 78 |
| Schedule risk | Low | Low | **Medium (managed: vertical slice Day 1)** | Medium | High |
| Production readiness as-built | High | Med-High | Medium + documented path | Medium | Med-High |

**Selected: Approach 3 — custom RAG control plane over raw Azure SDKs, all intelligence delegated to Azure AI models** — with Approach 5 (agentic retrieval) and Content Understanding documented as the managed evolution path, and Approach 1 explained as the consciously rejected zero-code alternative. *The rejected options appear in the README — rejection rationale is graded thinking.*

### The AI-first inventory (why this is not "Python-heavy")
| Intelligent step | Done by | NOT done by |
|---|---|---|
| Layout, OCR, tables, heading hierarchy, checkboxes | **DI layout model** | pdfplumber/regex |
| Document type classification (policy/claim/medical) | **GPT-4o-mini at ingest** | filename heuristics |
| Chunk boundaries | **DI-detected structure** (+token cap) | blind character splits |
| Query↔chunk semantic match | **AOAI embeddings + HNSW** | keyword-only |
| Lexical precision | **BM25 (`en.microsoft` analyzer)** | — |
| Fusion + reranking | **RRF + semantic cross-encoder** | hand-tuned score math |
| Follow-up coreference ("that same policy") | **GPT-4o rewrite call** | regex pronoun resolution |
| Multi-doc query planning | **GPT-4o intent router** + facet fan-out | string matching on "compare" |
| Grounded synthesis + citation structure | **GPT-4o Structured Outputs** | prose regex parsing |
| Answer quality measurement | **LLM-judge evaluators** (groundedness/relevance/retrieval) | manual spot checks |
Python's job: typed orchestration, retries, status, logging. ~Zero domain heuristics.

---

# 6. End-to-End Architecture

## 6.1 Component & data flow
```
┌──────────────────────────────  INGESTION (async, per document)  ─────────────────────────────┐
│ POST /documents (batch ok) ── 202 + doc_id per file                                          │
│   └► Blob Storage  (container: originals/)                                                  │
│        └► DI prebuilt-layout (markdown + JSON; async LRO)  ── persist JSON → blob: extracts/ │
│             └► [GPT-4o-mini] doc_type classification                                         │
│             └► Chunker: markdown-header split (H1–H3) → 512-token cap, 15–25% overlap        │
│                        → tables kept whole → breadcrumb prepended                            │
│                        → page range per chunk via pages[].spans offset mapping               │
│             └► AOAI text-embedding-3-small (batched)                                         │
│                  └► AI Search push upsert (chunk docs)                                       │
│ Status machine: uploaded → extracting → classifying → chunking → indexing → ready | failed   │
│ GET /documents, GET /documents/{id}  (UI polls)                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────  QUERY (per chat turn)  ───────────────────────────────────────┐
│ POST /chat {session_id, message}                                                             │
│  1 [GPT-4o] rewrite: (history + message) → standalone query     ← multi-turn resolution     │
│  2 [GPT-4o] intent: simple | comparison                                                      │
│  3a simple:      AI Search hybrid (BM25 + vectorizer-embedded vector, RRF)                   │
│                  + semantic rerank + captions, top 5                                         │
│  3b comparison:  facet doc_name → parallel per-doc filtered hybrid sub-queries (k=3–4 each)  │
│  4 Gate: max @search.rerankerScore < τ (≈1.8) → honest refusal, no LLM call                  │
│  5 [GPT-4o] grounded answer, Structured Outputs:                                             │
│       {answer_markdown, citations[{source_id, doc_name, page, quote}], insufficient_context} │
│  6 UI: streamed answer + citation chips → panel → blob SAS link / cached page text           │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 6.2 AI flow (model call budget per turn)
| Call | Model | Tokens (typ.) | Purpose |
|---|---|---|---|
| Rewrite | gpt-4o-mini | ~300 in / 30 out | standalone query |
| Intent | gpt-4o-mini (or merged into rewrite as one structured call — preferred) | ~100 | route |
| Query embed | (inside AI Search vectorizer) | ~30 | vector leg |
| Answer | gpt-4o | ~3–6k in / 400 out | grounded synthesis |
≈ $0.02–0.04 per question at PAYG rates. Merging rewrite+intent into one structured-output call is the efficiency refinement worth mentioning aloud.

## 6.3 Security architecture
**Demo tier (built):** `DefaultAzureCredential` everywhere (works as `az login` locally, managed identity in cloud); zero secrets in code; `.env.example` documents config; key-auth fallback only as documented escape hatch; short-TTL SAS for citation links.
**Production tier (designed, documented):**
- User-assigned managed identity with least-privilege built-in roles: **Cognitive Services OpenAI User** (AOAI), **Cognitive Services User** (DI), **Search Index Data Reader** (query path) / **Search Index Data Contributor** (ingestion), **Storage Blob Data Contributor**, **Key Vault Secrets User** (residual secrets only).
- Disable local/key auth on AOAI, Search (`aadOnly`), Storage; private endpoints + Private DNS for all PaaS; `publicNetworkAccess: Disabled`; App Gateway + WAF in front (per MS Baseline Foundry Chat reference architecture).
- **Content safety:** default AOAI content filters + **Prompt Shields** for indirect prompt injection — uploaded documents are an injection vector in RAG; spotlighting separates instructions from retrieved text.
- **PHI/compliance (insurance + medical reports):** Azure OpenAI no-training guarantee; **modified abuse monitoring** (no 30-day human-review retention) for PHI workloads; **Data Zone Standard (US/EU)** deployment for residency; CMK encryption option; audit via diagnostic logs. HIPAA BAA in scope.

## 6.4 Observability
**Built:** `structlog` JSON logs; correlation ID per document and per chat turn; per-stage timing spans (upload→extract→chunk→index; rewrite→retrieve→gate→generate); token usage logged per call; assignment's "trace the full pipeline" requirement satisfied verbatim.
**Production path:** `azure-monitor-opentelemetry` distro → Application Insights (FastAPI + OpenAI SDK auto-instrumented); **OTel GenAI semantic conventions** (`gen_ai.*` spans) → App Insights "Agents" view; Foundry **continuous evaluation** (GA Mar 2026) sampling live traces for groundedness/relevance; Cost Management budgets with 50/75/90% alerts.

## 6.5 Scaling strategy (the "thousands of docs/week" answer)
Do the arithmetic first — it reframes the problem: 5,000 docs/week ≈ 30/hour ≈ **0.01 docs/sec**, vs a single S0 DI resource at **15 TPS** and Tier-1 embedding quota of 1M TPM (~2,000 chunk-embeddings/min). **Capacity is a non-issue; the real production problems are smoothness, resilience, and idempotency.** Therefore:
- **Ingestion:** Blob upload → Event Grid → queue (Service Bus) → KEDA-scaled workers (Container Apps Jobs / Functions) → DI async → embed (batched) → push index. Dead-letter queue; idempotent `doc_id`s; per-stage retry. The take-home's `IngestionPipeline` interface is the seam where the in-process implementation swaps for the queue-backed one — one diagram annotation makes this point.
- **Query path:** AOAI Global/Data-Zone Standard PAYG behind an **APIM GenAI gateway** when scale demands: backend pools across deployments/regions, circuit breaker honoring Retry-After, per-team token limits (`llm-token-limit`), token-usage metrics; **PTU reservation** only when sustained volume justifies (~70% discount at commitment).
- **AI Search:** Basic (demo) → **S1, 3 replicas × 1 partition** (read-write SLA needs ≥3 replicas); partitions only when storage/latency demands; embeddings scale path = 3-large + MRL truncation + binary quantization.
- **Hosting:** containers on **Azure Container Apps** (scale-to-zero, KEDA), citing App Service as MS-baseline conservative alternative; AKS explicitly not justified at this scale.

## 6.6 Deployment flow
**Demo:** `infra/provision.sh` (az cli) or Bicep — RG, Blob, DI S0, Search Basic, AOAI (gpt-4o, gpt-4o-mini, text-embedding-3-small) — reviewer runs one script, fills `.env`, `uvicorn` + `streamlit run`.
**Production path:** **azd + Bicep** (modeled on Azure-Samples/azure-search-openai-demo `infra/`), GitHub Actions with **OIDC federated credentials** (keyless deploys, `id-token: write` + `azure/login@v2`); PR → lint/test/`bicep what-if` → staging revision → smoke + eval gate (groundedness threshold) → promote. Eval-gated promotion is the AI-native CI/CD detail interviewers remember.

## 6.7 Evaluation (the differentiator)
`evals/golden_set.jsonl`: 12–15 questions across the four scenario types (incl. 2 unanswerable → refusal expected, 2 follow-up chains, 1 comparison). `evals/evaluate.py` with `azure-ai-evaluation` **Groundedness / Relevance / Retrieval** evaluators (LLM-judge, 1–5); results table committed to README. Closes the loop: AI evaluates the AI.

---

# 7. Design Decision Register (one line each — README-ready)

| # | Decision | Over | Because |
|---|---|---|---|
| D1 | DI `prebuilt-layout` v4.0 markdown, called from my code | Search skillset / Content Understanding / prebuilt-read | Only option giving headings AND page spans AND all 5 formats; skillset modes each lose one citation ingredient; CU has no free tier + schedule risk |
| D2 | Hybrid structural chunking (headers → 512-token cap, 15–25% overlap, tables whole, breadcrumb) | pure structural / fixed window | Microsoft's own documented pattern; structure from the AI model; counters context-loss and table-severing failure modes |
| D3 | Page mapping via `pages[].spans` offset math | PageBreak counting / none | Exact, testable; citations that open the right page |
| D4 | Hybrid + semantic ranker on Basic tier (~$2.5/day) | Free tier | Free tier lacks semantic ranker; rerankerScore powers the refusal gate; documented cost-awareness |
| D5 | rerankerScore refusal gate (τ≈1.8) | prompt-only "say I don't know" | Calibrated model signal beats hope; demonstrable in video |
| D6 | LLM query rewrite for multi-turn | raw history to retriever / Search `queryRewrites` | Canonical MS pattern; built-in rewrite is preview and not conversation-aware |
| D7 | Intent router + facet + per-doc fan-out for comparisons | naive top-k / agentic retrieval | top-k provably under-covers; agentic retrieval is the cited managed path but black-box for the graded layer |
| D8 | text-embedding-3-small @1536 | ada-002 (assignment example) | "or equivalent" exercised: better MTEB, 1/5 price; 3-large+MRL = scale path |
| D9 | Structured Outputs citations | prose `[n]` regex / On Your Data | Deterministic UI contract; the model emits structure; OYD outsources the graded layer |
| D10 | Raw Azure SDKs, no orchestration framework | LangChain/SK/Agent Service/Prompt Flow | Linear pipeline; frameworks hide graded decisions; PF retired Apr 2026, SK mid-merger — currency signals |
| D11 | FastAPI BackgroundTasks + status machine | Durable Functions now | Right-sized; interface seam documents the queue-backed production swap |
| D12 | `DefaultAzureCredential` + exact RBAC roles documented | key auth | Assignment requires it; zero-code local→cloud auth |
| D13 | Eval harness in repo with scores in README | none | Evaluation-driven development; touches 3 rubric rows |

---

# 8. Interview Preparation

## 8.1 60-second architecture walkthrough (video opening / interview opener)
> "I treated this as a design problem first. The grade concentrates on architecture and RAG quality, and the four sample scenarios are really four retrieval failure modes: lexical precision, OCR, coreference, and multi-document coverage. My architecture counters each one explicitly. Document Intelligence's layout model gives me structure — headings, tables, and page spans — so my chunking follows the document's own semantics and every chunk carries an exact page range for citations. Retrieval is hybrid BM25-plus-vector fused by RRF, then reranked by the semantic cross-encoder, whose calibrated score doubles as a refusal gate so the system declines to answer rather than hallucinate. Multi-turn works by LLM query rewriting; comparison questions fan out per document via facets so every policy contributes evidence. Generation uses structured outputs, so citations are a typed contract, not parsed prose. Python is a thin, typed control plane — every intelligent step is an Azure model. And I shipped an eval harness, so I can show you groundedness numbers, not vibes."

## 8.2 Expected questions → strong answers

**Q: Why didn't you use Azure AI Search's built-in skillset pipeline? It does everything you wrote.**
A: Its Layout skill has two modes — markdown mode preserves headings but drops page numbers; text mode keeps page numbers but drops headings. The citation requirement needs both, so I called DI directly and did span-offset page mapping. I'd also lose chunking control, and >20 docs/day requires a billable attach with a 5-min/doc skill timeout. It's the right tool for a content-team search portal; not for citation-grade RAG.

**Q: Why not the Foundry Agent Service / why isn't this "agentic"?**
A: Agents earn their complexity when there's tool choice or branching plans. This is a linear retrieval pipeline with one conditional (comparison fan-out) — I implemented the planning step as a single structured LLM call I can explain and test. I did evaluate AI Search's agentic retrieval, which went GA in `2026-04-01` — it's the managed evolution of exactly my query layer, and my README shows where it would slot in. For an assessed exercise I wanted the graded layer to be glass-box.

**Q: Your chunking — why 512 tokens? Why not semantic-similarity chunking?**
A: 512/~15–25% overlap is Microsoft's documented starting point and fits the embedding model's sweet spot — but the size cap is the *fallback*, not the strategy. Primary boundaries come from the layout model's detected headings, so chunks align to the document's meaning; embedding-similarity chunking adds cost and nondeterminism and still ignores tables, which in policies carry the answers. My table rule — never split, prepend the section breadcrumb — comes from the failure mode where a coverage-limit table is retrieved without the section that names the benefit.

**Q: How do you prevent hallucinations?**
A: Four layers. Retrieval: hybrid + reranking maximizes the chance the truth is in context. Gate: if the best rerankerScore is below threshold, we refuse before generation — a calibrated model signal, not a prompt hope. Prompt: answer-only-from-sources with mandatory per-fact citations, temperature 0.2. Measurement: groundedness evaluator over a golden set, scores in the README — and in production, Foundry continuous evaluation sampling live traces.

**Q: "Compare deductibles across all policies" — walk me through it.**
A: Naive top-k fails structurally — one verbose policy crowds out the rest. My router classifies comparison intent, a facet query on `doc_name` enumerates the corpus with zero extra infrastructure, then the same sub-query runs per document with a filter, in parallel, capped at 3–4 chunks each, so every policy is guaranteed representation. Synthesis gets per-document evidence blocks and returns a comparison table with per-cell citations. Over ~8 documents I'd switch to summarize-then-compare; at real scale this is exactly what agentic retrieval manages for you.

**Q: How does this scale to thousands of documents a week?**
A: First, arithmetic: 5,000/week is 0.01 docs/sec against a 15-TPS Document Intelligence resource — capacity isn't the problem; smoothness and resilience are. So the production shape is queue-based load leveling: Event Grid → Service Bus → KEDA-scaled workers, dead-letter and idempotent doc IDs. My ingestion is behind an interface so the in-process demo implementation swaps for that without touching the pipeline stages. Query side scales via APIM's GenAI gateway — backend pools across deployments, circuit breaker honoring Retry-After — and PTU reservation once volume is steady. Search goes S1 with three replicas for the read-write SLA.

**Q: Security for medical data?**
A: Managed identity with least-privilege data-plane roles, key auth disabled, private endpoints per the MS baseline. AOAI specifics: prompts aren't used for training; for PHI I'd request modified abuse monitoring so prompts aren't retained for human review; Data Zone deployment pins processing geography. Plus Prompt Shields, because in RAG, uploaded documents are an injection vector — a scanned PDF can carry adversarial instructions into my context.

**Q: What would you do differently with more time?**
A: Three things, in order: (1) figure/image verbalization — DI crops figures, GPT-4o describes them, indexed as chunks — claim forms have stamps and signatures that matter; (2) table-summary augmentation chunks; (3) hybrid eval expansion — retrieval metrics (hit-rate@k on labeled chunk relevance) alongside LLM-judge scores, then continuous evaluation in production. Honest limitation: my DOCX citations are section-anchored, not page-anchored, because layout's Office pages are synthetic 3,000-char units — I surface that honestly in the UI rather than fake page numbers.

**Q: Why FastAPI/raw SDKs — isn't that more code to maintain than a framework?**
A: The RAG loop is ~200 lines; LangChain's equivalent abstraction would be ~50 lines of mine plus a heavyweight dependency tree the reviewer must install, and the decisions I'm being assessed on would be buried in callbacks. The framework landscape itself argues for caution right now: Prompt Flow retired this April, Semantic Kernel is merging into Agent Framework, LangChain proper is in maintenance mode. Stable Azure SDKs are the lowest-risk dependency surface in 2026.

## 8.3 Demo video structure (5–7 min)
1. **0:00–1:30** Architecture: the diagram, the four-failure-modes framing, three decisions (chunking, refusal gate, fan-out).
2. **1:30–5:30** Live: batch upload (PDF+scan+DOCX) with live status → scenario 1 (policy Q + clickable citation to page) → scenario 2 (scanned claim form) → scenario 3 (follow-up "does *it* cover…", show the rewritten query in logs — make the invisible visible) → scenario 4 (comparison table with per-policy citations) → **refusal demo** (off-corpus question).
3. **5:30–7:00** Challenges: page-span mapping trick, F0 2-page trap, comparison fan-out; eval scores table; 30-second production path (queue ingestion, APIM gateway, private endpoints, continuous eval).

---

# 9. Zero-Budget Constraint — Free-Tier Architecture (BINDING)

**Constraint:** no paid subscription. Everything must run on genuinely free Azure options. This is not a degradation — it's a *constraint-driven redesign*, and documenting it explicitly is graded ("If you encounter resource limitations, document them and explain how you would implement the feature with full access" — assignment §10).

## 9.1 The free-tier reality (verified)
| Service | Free option | Hard limits that bite | Status |
|---|---|---|---|
| Azure OpenAI | **None exists.** Use **Azure Free Account: $200 credit / 30 days** (or Azure for Students $100, no card) | Credit expires day 30; some regions/models gated on new subs | ✅ project total ≈ **$2–3** of credit (gpt-4o-mini + 3-small) |
| Document Intelligence | **F0**: 500 pages/month, $0 | **Only the FIRST 2 PAGES of any document are analyzed — silently**; 4 MB max file | ⚠ needs workaround (below) |
| Azure AI Search | **Free (F1)**: $0 forever, 50 MB, 3 indexes | **No semantic ranker**; no scoring-profile-after-rerank; small quota; no SLA | ⚠ needs gate redesign (below) |
| Blob Storage | Free account: 5 GB / 12 months (else pennies vs credit) | — | ✅ |
| Hosting | Run locally (uvicorn + streamlit) | — | ✅ free |
| Eval judge | gpt-4o-mini as `azure-ai-evaluation` judge model | — | ✅ pennies |

## 9.2 Redesign 1 — the DI F0 two-page trap → **page-window splitter**
F0 silently truncates analysis to the first 2 pages. Two compliant solutions; ship both:
1. **Sample documents authored at ≤2 pages each** where realistic (claim form, medical report).
2. **Page-window splitter for multi-page PDFs** (the multi-page policy scenario is mandatory): split the PDF into 2-page windows with `pypdf` (pure plumbing — no intelligence in Python), send each window to DI F0 separately, then **merge results with a page-number offset** (window *i* → real pages `2i+1, 2i+2`). The span→page mapping logic is unchanged per window; chunk metadata carries *real* page numbers.
   - Cost math: a 10-page policy = 5 F0 calls = 10 of the 500 free pages/month. Budget: ~25 multi-page docs/month free — ample for the demo corpus.
   - Caveat to document honestly: headings that straddle a window boundary can split a logical section into two chunks — acceptable at demo scale; on S0 the splitter is bypassed by a single config flag (`DOCINTEL_PAGE_WINDOW=0`), which **is** the "with full access" answer.
   - Bonus: the splitter also keeps every request under F0's 4 MB cap.
3. Guard rail stays: post-extraction **page-count assertion** (DI pages == pypdf pages) so truncation can never pass silently.

## 9.3 Redesign 2 — no semantic ranker → **LLM-groundedness refusal gate**
Free Search tier removes the cross-encoder and its calibrated `@search.rerankerScore`. Replace the gate, don't drop it — and make it *more* AI-native:
- Retrieval remains **hybrid BM25 + vector + RRF** (fully supported on Free tier).
- The refusal decision moves into the **answer model itself via Structured Outputs**: the response schema's `insufficient_context: bool` + `confidence: "high"|"medium"|"low"` fields are populated by GPT-4o-mini judging whether the retrieved sources actually answer the question; `insufficient_context=true` → UI shows the honest refusal and suppresses citations. One call, zero extra cost, and the judge is a model — not a Python threshold.
- Secondary cheap signal: if RRF top score < ~0.02 (near-floor) or zero results → refuse before the LLM call (saves tokens on garbage queries).
- README framing: *"On Basic+ tiers I would gate on the semantic reranker's calibrated 0–4 score (designed, documented, one config flag); on the free tier the gate is LLM-self-assessed groundedness — here is the trade-off table."* This turns a limitation into a demonstrated design seam.
- Also lost with semantic ranker: extractive captions → citation snippets come from the cited chunk's `quote` field in the structured output instead (already in the schema — no loss in UX).

## 9.4 Redesign 3 — cost-pinned model lineup (against the $200 credit)
| Role | Model | Why |
|---|---|---|
| Rewrite + intent (one structured call) | **gpt-4o-mini** | ~$0.0002/turn |
| Grounded answer | **gpt-4o-mini default**, `CHAT_MODEL` env-switchable to gpt-4o | 4o-mini is fully capable of grounded extraction-style answers; reviewer can flip the env var |
| Embeddings | **text-embedding-3-small @1536** | ~$0.02/M tokens; whole corpus < $0.01 |
| Eval judge | gpt-4o-mini | 15-question golden set ≈ $0.05 |
| Query embedding | **client-side** (same embeddings deployment) | Avoids any vectorizer/managed-identity friction on free Search tier; one extra ~30-token call; vectorizer documented as the Basic+ pattern |

**Total estimated Azure spend for the entire assignment: < $5 of the $200 credit. Free-tier resources (DI F0, Search F1, local hosting) cost $0 permanently** — the repo remains runnable by reviewers on their own free accounts, which is itself a deliverable requirement.

## 9.5 What stays unchanged (the design survives the constraint)
Layout-markdown extraction, structural chunking + span→page citations, hybrid retrieval, LLM query rewriting, comparison fan-out via facets (facets work on Free tier), Structured-Outputs citations, status machine, structured logging, eval harness, DefaultAzureCredential. **The architecture's value was never in the paid tiers — it's in where the intelligence sits.**

## 9.6 110%-working insurance — pre-demo verification checklist
1. `scripts/smoke_test.py`: provisions nothing, asserts — DI F0 reachable, Search index exists, AOAI deployments respond, one end-to-end Q&A round-trips with a citation.
2. Page-count assertion on every ingest (catches truncation).
3. Golden-set eval run green (incl. 2 refusal cases) before recording.
4. All four assignment scenarios scripted in `evals/golden_set.jsonl` — the demo literally replays the graded test suite.
5. Pin `api-version` for DI (`2024-11-30`) and Search (stable GA) and model deployment names in `.env.example`; never rely on defaults.
6. Record the demo **before** day 25 of the trial credit window.

---

# 10. Plan Updates (deltas applied to SOLUTION_PLAN.md)

1. **Merge rewrite + intent into one structured-output call** (latency/cost; one schema returns `{standalone_query, intent}`).
2. **Day 0.5 addendum:** verify reviewer-region model availability; record exact RBAC role names in README (§6.3 list).
3. **Day 4 addendum:** add the **refusal demo** and **rewritten-query log reveal** to the demo script; add 2 unanswerable + 2 follow-up-chain items to the golden set.
4. **README structure:** include the Decision Register (§7) verbatim and the security/scaling production-path sections (§6.3–6.6) as "Limitations & Production Path".
5. **New risk controls:** page-count assertion post-extraction (F0 trap detector); comparison fan-out caps (k≤4/doc, ≤8 docs).
6. Everything else in SOLUTION_PLAN.md stands.
