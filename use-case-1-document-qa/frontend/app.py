"""Streamlit chat UI — production-grade UX for the Insurance Document Q&A system.

Design principles:
- Zero unnecessary clicks. Files are ingested the moment they're dropped (no
  Ingest button). Demo corpus loads from the empty-state CTA.
- Zero flicker. Polling only happens when there is in-flight ingestion work,
  and only the polling fragment re-runs — not the whole page. No `st.rerun()`
  after a chat turn; everything renders into placeholders in-place.
- Real token-by-token streaming during chat: SSE `token` events from the
  backend stream straight into the answer container as the model emits them.
- Citations are first-class. Each `[n]` becomes a chip; clicking it opens an
  `st.dialog` modal with the verbatim quote and an embedded PDF/image preview
  of the cited page — without disturbing the conversation layout.

The UI talks only to the FastAPI backend. No Azure SDK calls here."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

import requests
import streamlit as st
import streamlit.components.v1 as components

API = os.environ.get("API_BASE_URL", "http://localhost:8000")
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample-documents"
STAGE_ORDER = ["uploaded", "extracting", "classifying", "chunking", "indexing", "ready"]
STAGE_LABEL = {
    "uploaded": "Queued",
    "extracting": "Extracting layout (Document Intelligence)",
    "classifying": "Classifying document type",
    "chunking": "Chunking by structure",
    "indexing": "Embedding & indexing",
    "ready": "Ready for questions",
    "failed": "Failed",
}
SUGGESTED_QUESTIONS = [
    ("📋", "Coverage lookup",
     "What is the maximum coverage for outpatient treatment under the Gold Shield policy?"),
    ("🧾", "Claim form facts",
     "What is the claim amount and the date of service on the uploaded claim form?"),
    ("🔁", "Follow-up reasoning",
     "What is the Gold Shield deductible?"),
    ("⚖️", "Cross-document comparison",
     "Compare the deductible clauses across all uploaded policies."),
]

st.set_page_config(
    page_title="Insurance Document Intelligence",
    page_icon="🛡️", layout="wide", initial_sidebar_state="collapsed",
)

# ── Visual system (single CSS injection) ──────────────────────────────────────
st.markdown("""
<style>
:root {
    --navy:#0B2447; --deep:#19376D; --accent:#576CBC; --soft:#A5D7E8;
    --teal:#0E7C86; --amber:#D97706;
    --ink:#0F172A; --ink-2:#475569; --ink-3:#94A3B8;
    --line:#E2E8F0; --bg:#F8FAFC; --card:#FFFFFF;
    --ok:#16A34A; --err:#DC2626;
    --shadow: 0 1px 2px rgba(15,23,42,.04), 0 6px 20px rgba(15,23,42,.06);
}
html, body, [class*="css"] {
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
.block-container { padding-top:1.2rem!important; padding-bottom:6rem!important; max-width:1560px; }

/* ── Top bar ───────────────────────────────────────────────────────────── */
.topbar {
    display:flex; align-items:center; gap:14px; padding:14px 22px;
    background: linear-gradient(120deg, var(--navy) 0%, var(--deep) 55%, var(--accent) 100%);
    border-radius: 16px; color:#fff;
    box-shadow: 0 1px 2px rgba(15,23,42,.05), 0 12px 32px rgba(11,36,71,.18);
    margin-bottom: 18px;
}
.topbar .mark { font-size:28px; }
.topbar h1 { color:#fff; font-size:18px; font-weight:700; margin:0; letter-spacing:-.01em; }
.topbar .sub { color:#CBD5E1; font-size:12px; margin-top:2px; }
.topbar .right { margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.pill {
    display:inline-flex; align-items:center; gap:6px;
    padding:6px 11px; border-radius:999px; font-size:12px; font-weight:500;
    background: rgba(255,255,255,.13); color:#fff; backdrop-filter: blur(6px);
}
.pill.ok { background: rgba(22,163,74,.30); }
.pill.warn { background: rgba(217,119,6,.34); }
.pill.err { background: rgba(220,38,38,.32); }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.dot.ok  { background:#4ADE80; box-shadow:0 0 8px #4ADE80; }
.dot.warn{ background:#FBBF24; }
.dot.err { background:#F87171; }

/* ── Section heading ───────────────────────────────────────────────────── */
.sec-title { font-size:13px; font-weight:600; color:var(--ink-2);
    letter-spacing:.06em; text-transform:uppercase; margin: 4px 0 10px 0; }

/* ── Document card ─────────────────────────────────────────────────────── */
.card {
    background: var(--card); border:1px solid var(--line); border-radius:14px;
    padding:14px 16px; margin-bottom:12px; box-shadow: var(--shadow);
    transition: border-color .2s, transform .15s;
}
.card:hover { border-color:#CBD5E1; }
.card.ready  { border-left: 3px solid var(--ok); }
.card.failed { border-left: 3px solid var(--err); }
.card .name { font-weight:600; color:var(--ink); font-size:14px; word-break: break-word; }
.card .meta { font-size:11px; color:var(--ink-3); margin-top:2px; }
.card .badge {
    font-size:10px; padding:3px 9px; border-radius:999px; font-weight:600;
    background:#EEF2FF; color:var(--deep); border:1px solid #DBEAFE; letter-spacing:.02em;
}
.card .badge.failed { background:#FEF2F2; color:var(--err); border-color:#FECACA; }
.card .badge.ready  { background:#ECFDF5; color:var(--ok); border-color:#A7F3D0; }
.bar { height:6px; background:#E2E8F0; border-radius:99px; overflow:hidden; margin-top:10px; }
.bar > div { height:100%; background: linear-gradient(90deg, var(--accent), var(--teal));
    border-radius:99px; transition: width .4s ease; }
.bar.active > div { animation: shimmer 1.6s linear infinite; background-size: 200% 100%;
    background-image: linear-gradient(90deg, var(--accent), var(--teal), var(--accent)); }
.bar.failed > div { background: var(--err); width:100%; }
@keyframes shimmer { from {background-position:200% 0} to {background-position:0 0} }
.stage-line {
    font-size:11px; color:var(--ink-2); margin-top:6px;
    display:flex; justify-content:space-between; align-items:center;
}
.detail { font-size:11px; color:var(--err); margin-top:6px; }

/* ── Empty state ───────────────────────────────────────────────────────── */
.empty-hero {
    border: 1px solid var(--line); border-radius:18px; padding:38px 32px;
    background: linear-gradient(180deg, #FFFFFF 0%, #F1F5F9 100%);
    box-shadow: var(--shadow);
}
.empty-hero h2 { color:var(--ink); font-size:24px; margin:0 0 8px 0; font-weight:700; letter-spacing:-.01em; }
.empty-hero p { color:var(--ink-2); font-size:14px; max-width:620px; margin:0 0 14px 0; }
.empty-hero .ribbon {
    display:inline-block; font-size:11px; font-weight:600; letter-spacing:.08em;
    background:#EEF2FF; color:var(--deep); padding:4px 11px; border-radius:99px;
    margin-bottom:12px; text-transform:uppercase;
}

/* ── Suggestion chips ──────────────────────────────────────────────────── */
.sugg-grid { display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:14px; }
.sugg-card {
    background:#FFF; border:1px solid var(--line); border-radius:12px; padding:14px 16px;
    box-shadow: var(--shadow); cursor:pointer; display:flex; align-items:flex-start; gap:12px;
    transition: transform .15s, border-color .2s, box-shadow .2s;
}
.sugg-card:hover { border-color: var(--accent); transform: translateY(-1px); box-shadow: 0 4px 16px rgba(87,108,188,.16); }
.sugg-card .ic { font-size:22px; }
.sugg-card .title { font-weight:600; color:var(--ink); font-size:13px; }
.sugg-card .q { font-size:12px; color:var(--ink-2); margin-top:3px; line-height:1.4; }

/* ── Live agentic trace ───────────────────────────────────────────────── */
.trace {
    display:flex; flex-direction:column; gap:8px;
    padding:14px 16px; background:#F1F5F9; border-radius:12px;
    border:1px solid var(--line); margin-bottom:10px;
}
.trace .row { display:flex; gap:10px; align-items:center; font-size:13px; color:var(--ink-2); }
.trace .row.done   { color: var(--ok); }
.trace .row.active { color: var(--deep); font-weight:500; }
.trace .ic { width:18px; text-align:center; }
.trace .note { font-size:11px; color:var(--ink-3); margin-left:auto; }
.trace .row.active .ic { animation: spin 1.2s linear infinite; display:inline-block; }
@keyframes spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }

/* ── Chat bubbles ─────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background: transparent !important;
    padding: 6px 0 !important;
    border: none !important;
}
[data-testid="stChatMessage"] > div:first-child {
    /* avatar */
    background: linear-gradient(135deg, var(--navy), var(--accent)) !important;
    color: #fff !important;
}
[data-testid="stChatInput"] textarea { font-size: 15px !important; }
[data-testid="stFileUploaderDropzone"] {
    background: linear-gradient(180deg, #FFFFFF, #F8FAFC);
    border: 1.5px dashed var(--line) !important;
    border-radius: 14px !important;
    transition: border-color .2s, background .2s;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--accent) !important;
    background: linear-gradient(180deg, #FFFFFF, #EEF2FF);
}

/* ── Citation chips + intent / meta ───────────────────────────────────── */
.meta-footer { font-size:11px; color:var(--ink-3); margin-top:10px; }
.intent-badge {
    display:inline-block; font-size:10px; padding:2px 8px; border-radius:99px; font-weight:600;
    margin-left:6px; background:#E0F2FE; color:#075985; border:1px solid #BAE6FD;
}
.intent-badge.comp { background:#FEF3C7; color:#92400E; border-color:#FDE68A; }

.stButton button {
    font-weight:500; border-radius:10px; border:1px solid var(--line);
    transition: all .15s;
}
.stButton button:hover { border-color: var(--accent); }
.stButton button[kind="primary"] {
    background: linear-gradient(135deg, var(--navy), var(--accent));
    color: white; border: none;
}
.stButton button[kind="primary"]:hover {
    background: linear-gradient(135deg, var(--deep), var(--accent));
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(11,36,71,.20);
}

/* Hide Streamlit default chrome */
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
</style>
""", unsafe_allow_html=True)


# ── State init ────────────────────────────────────────────────────────────────
def _ss(key: str, default: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = default


_ss("session_id", uuid.uuid4().hex[:10])
_ss("messages", [])            # list of {role, content?, answer?, citations?, meta?}
_ss("uploaded_signatures", set())   # which file-uploader items we've already POSTed
_ss("ingestion_lock", False)
_ss("pending_question", None)
_ss("active_citation", None)


# ── HTTP ──────────────────────────────────────────────────────────────────────
def _get(path: str, **kw) -> Any:
    return requests.get(f"{API}{path}", timeout=kw.pop("timeout", 6), **kw)


def _post(path: str, **kw) -> requests.Response:
    return requests.post(f"{API}{path}", timeout=kw.pop("timeout", 180), **kw)


@st.cache_data(ttl=5)
def fetch_health() -> dict | None:
    try:
        r = _get("/health", timeout=3)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


def fetch_documents() -> list[dict] | None:
    try:
        r = _get("/documents", timeout=5)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


def stream_chat(question: str) -> Iterator[tuple[str, dict]]:
    """Parse SSE stream from /chat/stream into (event, data) tuples."""
    with _post("/chat/stream",
               json={"session_id": st.session_state.session_id, "message": question},
               stream=True, timeout=180) as response:
        response.raise_for_status()
        event: str | None = None
        for raw in response.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            if raw == "":
                event = None
                continue
            if raw.startswith("event:"):
                event = raw.split(":", 1)[1].strip()
            elif raw.startswith("data:") and event:
                payload = raw.split(":", 1)[1].strip()
                try:
                    yield event, json.loads(payload)
                except json.JSONDecodeError:
                    yield event, {"raw": payload}


# ── Top bar ───────────────────────────────────────────────────────────────────
def render_topbar(health: dict | None) -> None:
    if health is None:
        health_pill = '<span class="pill err"><span class="dot err"></span>Backend offline</span>'
        model_pill = ""
    else:
        services = health.get("services", {})
        n_ok = sum(1 for v in services.values() if v)
        cls = "ok" if n_ok >= 3 else ("warn" if n_ok >= 1 else "err")
        health_pill = (f'<span class="pill {cls}"><span class="dot {cls}"></span>'
                       f'Azure: {n_ok}/{len(services)} configured</span>')
        model_pill = f'<span class="pill">🤖 {health.get("chat_model","")}</span>'
    session_pill = f'<span class="pill">🪪 {st.session_state.session_id}</span>'
    st.markdown(f"""
    <div class="topbar">
        <div class="mark">🛡️</div>
        <div>
            <h1>Insurance Document Intelligence</h1>
            <div class="sub">Grounded answers · page-level citations · multi-turn · cross-document comparisons</div>
        </div>
        <div class="right">{model_pill}{session_pill}{health_pill}</div>
    </div>
    """, unsafe_allow_html=True)


# ── Document card ────────────────────────────────────────────────────────────
def _bar_pct(status: str) -> int:
    try:
        return int((STAGE_ORDER.index(status) + 1) / len(STAGE_ORDER) * 100)
    except ValueError:
        return 100


def _bar_cls(status: str) -> str:
    if status == "failed":
        return "failed"
    if status not in ("ready", "failed"):
        return "active"
    return ""


def render_document_card(doc: dict) -> None:
    status = doc.get("status", "uploaded")
    card_cls = "card " + ("ready" if status == "ready" else "failed" if status == "failed" else "")
    doc_type = doc.get("doc_type") or ""
    badge_cls = "ready" if status == "ready" else ("failed" if status == "failed" else "")
    badge = (f'<span class="badge {badge_cls}">{doc_type or status}</span>'
             if doc_type or status in ("ready", "failed") else "")
    detail = (f'<div class="detail">⚠ {doc["detail"]}</div>'
              if status == "failed" and doc.get("detail") else "")
    extras = f"{doc.get('pages') or 0}p · {doc.get('chunks') or 0} chunks" if status == "ready" else ""
    pct = _bar_pct(status)
    bar_cls = _bar_cls(status)
    st.markdown(f"""
    <div class="{card_cls}">
        <div style="display:flex; align-items:flex-start; gap:8px;">
            <div style="flex:1; min-width:0;">
                <div class="name">{doc['doc_name']}</div>
                <div class="meta">{doc['doc_id']}</div>
            </div>
            {badge}
        </div>
        <div class="bar {bar_cls}"><div style="width:{pct}%;"></div></div>
        <div class="stage-line">
            <span>{STAGE_LABEL.get(status, status)}</span>
            <span>{extras}</span>
        </div>
        {detail}
    </div>
    """, unsafe_allow_html=True)


# ── Auto-ingestion (no Ingest button) ─────────────────────────────────────────
def auto_ingest(uploaded_files: list[Any] | None) -> None:
    """POST any newly-dropped files immediately. Re-uploads of the same file
    are detected by (name, size) and skipped so a polling re-render doesn't
    double-post."""
    if not uploaded_files or st.session_state.ingestion_lock:
        return
    new_payload: list[tuple[str, tuple[str, bytes]]] = []
    seen = st.session_state.uploaded_signatures
    for f in uploaded_files:
        sig = (f.name, getattr(f, "size", None) or len(f.getvalue()))
        if sig in seen:
            continue
        new_payload.append(("files", (f.name, f.getvalue())))
        seen.add(sig)
    if not new_payload:
        return
    st.session_state.ingestion_lock = True
    try:
        r = _post("/documents", files=new_payload, timeout=60)
        if r.status_code == 202:
            st.toast(f"Accepted {len(r.json())} document(s)", icon="🚀")
        else:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            st.error(detail)
    except requests.RequestException as exc:
        st.error(f"API unreachable: {exc}")
    finally:
        st.session_state.ingestion_lock = False


def load_demo_corpus() -> None:
    if not SAMPLE_DIR.exists():
        st.error(f"sample-documents/ not found at {SAMPLE_DIR}.")
        return
    files = sorted(SAMPLE_DIR.glob("*"))
    files = [f for f in files if f.suffix.lower() in
             {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}]
    if not files:
        st.error("No sample documents found.")
        return
    payload = [("files", (f.name, f.read_bytes())) for f in files]
    try:
        r = _post("/documents", files=payload, timeout=90)
        if r.status_code == 202:
            st.toast(f"Loaded {len(r.json())} sample document(s).", icon="📚")
        else:
            st.error(r.json().get("detail", r.text))
    except requests.RequestException as exc:
        st.error(f"API unreachable: {exc}")


# ── Documents rail (fragment that polls ONLY when needed) ────────────────────
@st.fragment
def documents_panel() -> None:
    """Render the corpus list. Auto-polls every ~1.5s ONLY while there's
    in-flight ingestion work; once everything is ready/failed the fragment
    stops re-running, so the UI is calm and doesn't flicker."""
    docs = fetch_documents()
    if docs is None:
        st.warning("Backend not reachable — start it with `uvicorn src.api.main:app --reload`.")
        return
    if not docs:
        st.markdown(
            '<div style="padding:24px; text-align:center; color:var(--ink-3); '
            'border:1px dashed var(--line); border-radius:12px; background:#FFF;">'
            '<div style="font-size:36px;">📭</div>'
            '<div style="margin-top:8px; font-weight:600; color:var(--ink-2);">No documents yet</div>'
            '<div style="font-size:12px; margin-top:4px;">'
            'Drop files above or load the demo corpus.</div></div>',
            unsafe_allow_html=True,
        )
        return

    in_flight = [d for d in docs if d["status"] not in ("ready", "failed")]
    if in_flight:
        st.caption(f"⏳ {len(in_flight)} processing · live")
    for doc in docs:
        render_document_card(doc)

    # Conditional auto-poll: re-run THIS FRAGMENT only, only when needed.
    # This is the standard Streamlit pattern; the rest of the page stays calm.
    if in_flight:
        time.sleep(1.5)
        st.rerun()


# ── Suggestion chips ─────────────────────────────────────────────────────────
def render_suggestions() -> None:
    cols = st.columns(2)
    for i, (icon, title, question) in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(f"{icon}  {title}\n\n{question}",
                         key=f"sugg_{i}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()


# ── Citation modal ───────────────────────────────────────────────────────────
@st.dialog("Source preview", width="large")
def citation_dialog(citation: dict) -> None:
    st.markdown(f"**[{citation['source_id']}] {citation['doc_name']} · page {citation['page']}**")
    st.markdown("**Verbatim quote from the source**")
    st.info(citation.get("quote", ""))
    doc_id = citation.get("doc_id")
    if not doc_id:
        st.caption("Source document id unavailable for this citation.")
        return
    file_url = f"{API}/documents/{doc_id}/file"
    ext = Path(citation["doc_name"]).suffix.lower()
    st.markdown(f"**Original document — [open in new tab ↗]({file_url})**")
    if ext == ".pdf":
        components.iframe(f"{file_url}#page={citation['page']}", height=620, scrolling=True)
    elif ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        st.image(file_url, use_container_width=True)
    else:
        st.caption(f"{ext.upper()} preview not supported inline; use the link above.")


# ── Chat turn rendering ──────────────────────────────────────────────────────
TRACE_STAGES = [
    ("planning",  "🧭 Rewriting your question into a standalone query"),
    ("retrieving", "🔎 Hybrid search across the document index"),
    ("generating", "✍️  Grounding the answer in sources"),
]


def render_trace_html(state: dict[str, str]) -> str:
    rows = []
    for key, label in TRACE_STAGES:
        st_status = state.get(key, "pending")
        if st_status == "done":
            ic, cls = "✅", "done"
        elif st_status == "active":
            ic, cls = "⏳", "active"
        else:
            ic, cls = "•", ""
        note = state.get(f"{key}_note", "")
        note_html = f'<span class="note">{note}</span>' if note else ""
        rows.append(f'<div class="row {cls}"><span class="ic">{ic}</span>'
                    f'<span>{label}</span>{note_html}</div>')
    return f'<div class="trace">{"".join(rows)}</div>'


def _meta_html(meta: dict, citation_count: int) -> str:
    intent = meta.get("intent", "simple")
    intent_cls = "comp" if intent == "comparison" else ""
    return (f'<div class="meta-footer">🔍 query: <em>{meta.get("standalone_query","")}</em>'
            f'<span class="intent-badge {intent_cls}">{intent}</span>'
            f' · confidence: <strong>{meta.get("confidence","—")}</strong>'
            f' · {citation_count} citation(s)</div>')


def render_citation_chips(citations: list[dict], msg_idx: int) -> None:
    if not citations:
        return
    cols = st.columns(min(len(citations), 4))
    for i, c in enumerate(citations):
        with cols[i % len(cols)]:
            label = f"[{c['source_id']}] {c['doc_name']} · p{c['page']}"
            if st.button(label, key=f"cite_{msg_idx}_{i}", use_container_width=True):
                st.session_state.active_citation = c
                citation_dialog(c)


def render_history() -> None:
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            with st.chat_message("user", avatar="🧑‍💼"):
                st.markdown(message["content"])
        else:
            with st.chat_message("assistant", avatar="🛡️"):
                ans = message["answer"]
                st.markdown(ans["answer_markdown"])
                render_citation_chips(message.get("citations", []), idx)
                if message.get("meta"):
                    st.markdown(_meta_html(message["meta"], len(message.get("citations", []))),
                                unsafe_allow_html=True)


def run_chat_turn(question: str) -> None:
    """Stream one full chat turn: user msg → trace → tokens → citations → meta.
    No `st.rerun()` is called here — everything renders into stable placeholders,
    then the message is appended to history so the next natural rerun (from the
    chat_input) finds it there."""
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🛡️"):
        trace_placeholder = st.empty()
        answer_placeholder = st.empty()
        cite_placeholder = st.empty()
        meta_placeholder = st.empty()

        trace_state: dict[str, str] = {"planning": "active"}
        trace_placeholder.markdown(render_trace_html(trace_state), unsafe_allow_html=True)

        answer_buffer = ""
        final: dict | None = None
        try:
            for event, data in stream_chat(question):
                if event == "planning":
                    trace_state["planning"] = "active"
                elif event == "planned":
                    trace_state["planning"] = "done"
                    trace_state["planning_note"] = f"intent: {data.get('intent','—')}"
                    trace_state["retrieving"] = "active"
                elif event == "retrieving":
                    trace_state["retrieving"] = "active"
                elif event == "retrieved":
                    trace_state["retrieving"] = "done"
                    trace_state["retrieving_note"] = (
                        f"{data.get('chunk_count',0)} chunks · "
                        f"{len(data.get('documents',[]))} doc(s)"
                    )
                    trace_state["generating"] = "active"
                elif event == "generating":
                    trace_state["generating"] = "active"
                elif event == "token":
                    answer_buffer += data.get("delta", "")
                    # render the in-progress answer with a caret
                    answer_placeholder.markdown(answer_buffer + " ▌")
                    continue  # don't re-render trace on every token
                elif event == "done":
                    trace_state["generating"] = "done"
                    final = data
                elif event == "error":
                    answer_placeholder.error(f"Answer generation failed: {data.get('error','unknown')}")
                    return
                trace_placeholder.markdown(render_trace_html(trace_state), unsafe_allow_html=True)
        except requests.RequestException as exc:
            answer_placeholder.error(f"Request failed: {exc}")
            return

        if not final:
            answer_placeholder.error("No answer received from the backend.")
            return

        trace_placeholder.empty()
        answer = final["answer"]
        sources = final.get("sources", [])
        doc_ids = {s["doc_name"]: s["doc_id"] for s in sources}
        for c in answer["citations"]:
            c["doc_id"] = doc_ids.get(c["doc_name"], "")

        # Final answer (no caret); also use the streamed text if it's longer
        # (some token deltas may have been emitted *after* the parsed answer)
        final_text = answer["answer_markdown"]
        if len(answer_buffer) > len(final_text):
            final_text = answer_buffer
        answer_placeholder.markdown(final_text)

        meta = {
            "standalone_query": final["standalone_query"],
            "intent": final["intent"],
            "confidence": answer["confidence"],
        }
        msg = {
            "role": "assistant",
            "answer": {"answer_markdown": final_text, "confidence": answer["confidence"]},
            "citations": answer["citations"],
            "meta": meta,
        }
        st.session_state.messages.append(msg)

        # Render citation chips + meta footer inline (no rerun needed)
        msg_idx = len(st.session_state.messages) - 1
        with cite_placeholder.container():
            render_citation_chips(answer["citations"], msg_idx)
        meta_placeholder.markdown(_meta_html(meta, len(answer["citations"])),
                                  unsafe_allow_html=True)


# ── Chat controls ────────────────────────────────────────────────────────────
def render_chat_controls() -> None:
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("🆕 New chat", use_container_width=True, key="new_chat"):
            try:
                requests.delete(f"{API}/sessions/{st.session_state.session_id}", timeout=4)
            except requests.RequestException:
                pass
            st.session_state.session_id = uuid.uuid4().hex[:10]
            st.session_state.messages = []
            st.session_state.active_citation = None
            st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────
health = fetch_health()
render_topbar(health)

LEFT, RIGHT = st.columns([0.34, 0.66], gap="large")

with LEFT:
    st.markdown('<div class="sec-title">📂 Document corpus</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "Drop PDF / DOCX / JPG / PNG / TIFF here",
        type=["pdf", "docx", "jpg", "jpeg", "png", "tif", "tiff"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="uploader",
    )
    auto_ingest(uploaded)
    if st.button("📚 Load demo corpus", use_container_width=True, key="load_demo"):
        load_demo_corpus()
    st.markdown("<br>", unsafe_allow_html=True)
    documents_panel()

with RIGHT:
    render_chat_controls()
    if not st.session_state.messages and not st.session_state.pending_question:
        st.markdown("""
        <div class="empty-hero">
            <div class="ribbon">Ready when you are</div>
            <h2>Ask anything about your insurance documents</h2>
            <p>Answers are grounded only in the documents you've uploaded. Every fact is cited
            to the exact source page, with an embedded preview you can verify in one click.
            Follow-up questions remember the context.</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('<div class="sec-title" style="margin-top:18px;">Try one of these</div>',
                    unsafe_allow_html=True)
        render_suggestions()
    else:
        render_history()

    pending = st.session_state.pending_question
    if pending:
        st.session_state.pending_question = None
        run_chat_turn(pending)

    if question := st.chat_input("Ask about the uploaded documents…"):
        run_chat_turn(question)
