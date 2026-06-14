"""FastAPI backend — thin HTTP layer over the ingestion / retrieval /
generation services. Endpoints:
  POST /documents             batch upload → 202 + per-file doc_ids
  GET  /documents             all statuses
  GET  /documents/{id}        one status
  GET  /documents/{id}/file   original document (inline, citation click-through)
  POST /chat                  one RAG turn (synchronous)
  POST /chat/stream           same turn as SSE so the UI can render an
                              'agentic trace' (planning → retrieving → generating)
  GET  /health                liveness + Azure dependency check"""
import json
import shutil
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from src.core.azure_clients import chat_client, chat_extra_kwargs, chat_model
from src.core.config import active_provider, get_settings
from src.core.logging import configure_logging, get_logger
from src.generation.rag_service import answer_question, stream_answer
from src.generation.schemas import ChatRequest, ChatResponse
from src.indexing.index_manager import ensure_index
from src.ingestion.extractor import SUPPORTED_EXTENSIONS
from src.ingestion.pipeline import process_document
from src.ingestion.status_store import status_store

configure_logging()
log = get_logger("api")

app = FastAPI(title="Intelligent Document Processing & Q&A", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
)

# In-memory conversation history per session with sliding TTL (demo scope;
# production: Cosmos DB). _last_seen is updated on every chat turn; stale
# sessions are pruned opportunistically to keep memory bounded.
_sessions: dict[str, list[dict]] = defaultdict(list)
_last_seen: dict[str, float] = {}
_SESSION_TTL_SECONDS = 24 * 3600
_MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # DI F0 request cap

# Document-level parallel ingestion. FastAPI's BackgroundTasks runs sequentially
# AFTER the response is sent, which serialises multi-doc uploads. A dedicated
# ThreadPoolExecutor fires every ingestion concurrently — for a 5-file upload
# that's a ~5× wall-clock win bound only by Azure throughput. azure-core SDK
# clients are thread-safe so concurrent calls share the same pooled HTTP session.
_INGEST_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ingest")


def _prune_sessions() -> None:
    now = time.time()
    expired = [sid for sid, ts in _last_seen.items() if now - ts > _SESSION_TTL_SECONDS]
    for sid in expired:
        _sessions.pop(sid, None)
        _last_seen.pop(sid, None)
    if expired:
        log.info("sessions_pruned", count=len(expired))


def _warmup() -> None:
    """Best-effort: fire one tiny embed + chat call so the FIRST real query
    doesn't pay the serverless cold-start (free Foundry models scale to zero).
    Runs in a daemon thread; every failure is logged and ignored."""
    try:
        from src.indexing.embedder import embed_query
        embed_query("warmup")
    except Exception as exc:
        log.info("warmup_embed_skipped", error=type(exc).__name__)
    try:
        chat_client().chat.completions.create(
            model=chat_model(),
            messages=[{"role": "user", "content": "ping"}], max_tokens=1, temperature=0,
            **chat_extra_kwargs(),
        )
        log.info("warmup_complete", provider=active_provider(), model=chat_model())
    except Exception as exc:
        log.info("warmup_chat_skipped", error=type(exc).__name__)


def _boot_tasks() -> None:
    """Index check (+ optional warmup) in the background so the server binds the
    port instantly. Previously these ran inline in the startup event; if Azure
    was slow/unreachable the index check's retries delayed 'startup complete' by
    up to a minute. Now boot is immediate and these self-heal in the background."""
    # Reconcile orphans first: any doc still 'processing' at boot has no worker
    # (its thread died with the previous process), so clean/fail it immediately —
    # this is what stops documents blinking "processing" forever after a restart.
    try:
        reaped = status_store.reap_stale(0)
        if reaped:
            log.info("startup_reconciled_orphans", count=reaped)
    except Exception as exc:
        log.warning("startup_reconcile_failed", error=str(exc))
    try:
        ensure_index()
        log.info("startup_index_ready", index=get_settings().search_index_name)
    except Exception as exc:
        log.error("startup_index_unavailable", error=str(exc),
                  hint="Check SEARCH_ENDPOINT / SEARCH_KEY / network reachability (see docs/SETUP.md).")
    if get_settings().warmup_on_startup:
        _warmup()


@app.on_event("startup")
def startup() -> None:
    import threading
    threading.Thread(target=_boot_tasks, name="boot", daemon=True).start()
    log.info("startup_complete")


@app.get("/health")
def health() -> dict:
    """Lightweight liveness probe plus a per-service config check.
    Real readiness is implicit: failing dependencies surface as 5xx on the actual
    routes that need them, with structured logs for triage."""
    settings = get_settings()
    provider = active_provider()
    llm_ok = bool(settings.gemini_api_key) if provider == "gemini" else bool(settings.azure_openai_endpoint)
    return {
        "status": "ok",
        "provider": provider,
        "services": {
            "llm": llm_ok,
            "docintel": bool(settings.docintel_endpoint),
            "search": bool(settings.search_endpoint),
            "blob": bool(settings.blob_connection_string),
        },
        "chat_model": chat_model(),
        "embed_model": settings.azure_openai_embed_deployment,
    }


@app.post("/documents", status_code=202)
def upload_documents(files: list[UploadFile]) -> list[dict]:
    settings = get_settings()
    accepted: list[dict] = []
    for file in files:
        name = file.filename or "unnamed"
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=f"'{name}': unsupported format '{ext}'. "
                       f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )
        doc_id = uuid.uuid4().hex[:12]
        dest = settings.data_dir / "uploads" / f"{doc_id}{ext}"
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        if ext != ".pdf" and dest.stat().st_size > _MAX_UPLOAD_BYTES:
            dest.unlink()
            raise HTTPException(status_code=413,
                                detail=f"'{name}' exceeds the 4 MB Document Intelligence F0 limit.")
        status_store.create(doc_id, name)
        # Fire-and-forget into the parallel ingestion pool — every file starts
        # processing immediately, not after the previous one completes.
        _INGEST_POOL.submit(process_document, doc_id, dest)
        accepted.append({"doc_id": doc_id, "doc_name": name, "status": "uploaded"})
        log.info("upload_accepted", doc_id=doc_id, doc_name=name)
    return accepted


@app.get("/documents")
def list_documents() -> list[dict]:
    # Opportunistically reap documents that have hung mid-processing so a genuinely
    # stuck Azure call can't leave a card spinning forever. Healthy docs bump
    # updated_ts at every stage, so they're never within the stale window.
    status_store.reap_stale(get_settings().stale_doc_seconds)
    return status_store.list_all()


@app.get("/documents/{doc_id}")
def get_document(doc_id: str) -> dict:
    record = status_store.get(doc_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Unknown document id '{doc_id}'.")
    return record


@app.get("/documents/{doc_id}/file")
def get_document_file(doc_id: str, inline: bool = True) -> FileResponse:
    """Return the original document. Browsers can render PDFs/images inline,
    so the UI uses this for the embedded preview pane (set ?inline=false to force download).
    PDF citation URLs append '#page=N' so most viewers jump straight to the page."""
    record = status_store.get(doc_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Unknown document id '{doc_id}'.")
    uploads = get_settings().data_dir / "uploads"
    matches = list(uploads.glob(f"{doc_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Original file not found on disk.")
    headers = {"Content-Disposition": f'inline; filename="{record["doc_name"]}"'} if inline else None
    return FileResponse(matches[0], filename=record["doc_name"], headers=headers)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty.")
    _prune_sessions()
    history = _sessions[request.session_id]
    try:
        response = answer_question(request.session_id, request.message, history)
    except Exception as exc:
        log.error("chat_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Answer generation failed: {exc}") from exc
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": response.answer.answer_markdown})
    del history[:-12]  # keep the last 6 turns
    _last_seen[request.session_id] = time.time()
    return response


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Server-Sent Events stream of pipeline stages so the UI can render an
    agentic trace in real time. Events: planning → planned → retrieving →
    retrieved → generating → done | error. Each `data:` line is a JSON object
    with the stage name and payload. Same RAG pipeline; just observed live."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message must not be empty.")
    _prune_sessions()
    history = list(_sessions[request.session_id])

    def event_stream():
        try:
            final_answer: dict | None = None
            for stage, payload in stream_answer(request.session_id, request.message, history):
                yield f"event: {stage}\ndata: {json.dumps(payload)}\n\n"
                if stage == "done":
                    final_answer = payload
            if final_answer:
                # Commit history only on success — partial turns don't pollute follow-ups.
                _sessions[request.session_id].append({"role": "user", "content": request.message})
                _sessions[request.session_id].append({
                    "role": "assistant",
                    "content": final_answer["answer"]["answer_markdown"],
                })
                del _sessions[request.session_id][:-12]
                _last_seen[request.session_id] = time.time()
        except Exception as exc:
            log.error("chat_stream_failed", error=str(exc))
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/sessions/{session_id}")
def reset_session(session_id: str) -> dict:
    _sessions.pop(session_id, None)
    _last_seen.pop(session_id, None)
    return {"session_id": session_id, "cleared": True}
