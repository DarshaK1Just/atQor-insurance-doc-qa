"""Streamlit UI — Insurance Document Intelligence.

A grounded document-Q&A workspace, modelled as a two-stage flow the user can
always follow:

    1 · Add documents   →   we extract + index them   →   2 · Ask in plain English
                                                            →   cited, page-level answers

Design decisions (and the bugs they replace):

* THEME IS LOCKED.  `.streamlit/config.toml` pins base="light" so Streamlit's own
  chrome matches this CSS.  Previously the light card design rendered on a dark
  inherited theme, which is what made the corpus cards look broken/noisy.

* ZERO FLICKER.  The corpus list lives in an `@st.fragment` that auto-polls with
  `run_every` *only while ingestion is in flight*, and reruns ITSELF — never the
  whole page.  The old code did `time.sleep(1.5)` + a bare `st.rerun()` (app
  scope) which re-executed and repainted the entire page every 1.5 s.

* NO RAW HTML LEAKS.  All markup goes through `html()`, which `dedent`s + strips
  so the first line sits at column 0.  The old indented f-strings were
  intermittently parsed as Markdown *code blocks*, printing literal `</div>`.

* GUIDED & GATED.  Chat is disabled until at least one document is "ready", with
  state-aware empty screens (cold start → indexing → ready) so the user is never
  staring at an input that can't help them yet.

The UI talks only to the FastAPI backend. No Azure SDK calls here."""
from __future__ import annotations

import json
import os
import textwrap
import uuid
from html import escape
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
    "extracting": "Reading layout",
    "classifying": "Classifying type",
    "chunking": "Structuring content",
    "indexing": "Embedding & indexing",
    "ready": "Ready",
    "failed": "Failed",
}
SUGGESTED_QUESTIONS = [
    ("📋", "Coverage lookup",
     "What is the maximum coverage for outpatient treatment under the Gold Shield policy?"),
    ("🧾", "Claim-form facts",
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

# ── Visual system (single CSS injection, light enterprise theme) ──────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --brand:#0A1F44; --brand-2:#15336B; --brand-3:#1E4A8A;
    --accent:#4F6BED; --accent-2:#6E8BF4; --violet:#7C5CFC; --teal:#0E8E8E;
    --ink:#0B1220; --ink-2:#475569; --ink-3:#8A97A8;
    --line:#E6EAF1; --line-2:#EFF2F7; --bg:#F4F6FB; --card:#FFFFFF;
    --ok:#15A34A; --ok-bg:#ECFDF5; --ok-br:#A7F3D0;
    --warn:#D97706; --warn-bg:#FFFBEB; --warn-br:#FDE68A;
    --err:#DC2626;  --err-bg:#FEF2F2;  --err-br:#FECACA;
    --ring: rgba(79,107,237,.28);
    --shadow-sm: 0 1px 2px rgba(11,18,32,.04), 0 1px 3px rgba(11,18,32,.06);
    --shadow-md: 0 6px 18px rgba(11,18,32,.07), 0 16px 40px rgba(11,18,32,.07);
    --shadow-brand: 0 10px 30px rgba(10,31,68,.28);
}

html, body, [class*="css"] {
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    color: var(--ink);
}
/* Soft, premium canvas — a barely-there cool gradient instead of flat grey. */
.stApp {
    background:
        radial-gradient(1100px 480px at 88% -8%, rgba(79,107,237,.07), transparent 60%),
        radial-gradient(900px 420px at 0% 0%, rgba(124,92,252,.05), transparent 55%),
        var(--bg);
}

/* Tight, deliberate page rhythm — kills the big empty gap under the header. */
.block-container {
    padding-top: .75rem !important;
    padding-bottom: 7rem !important;
    max-width: 1500px;
}
/* Calm, consistent vertical spacing between stacked blocks. */
[data-testid="stVerticalBlock"] { gap: .7rem; }
[data-testid="column"] [data-testid="stVerticalBlock"] { gap: .55rem; }

/* Hide Streamlit default chrome. */
#MainMenu, footer, header[data-testid="stHeader"] { visibility:hidden; height:0; }

/* ── Top bar (enterprise header with depth) ─────────────────────────────────── */
.topbar {
    position:relative; overflow:hidden;
    display:flex; align-items:center; gap:16px; padding:20px 26px;
    background:
        radial-gradient(680px 220px at 82% -40%, rgba(124,92,252,.45), transparent 70%),
        radial-gradient(520px 200px at 12% 140%, rgba(79,107,237,.40), transparent 70%),
        linear-gradient(118deg, #081A3A 0%, var(--brand) 42%, var(--brand-2) 78%, var(--brand-3) 100%);
    border-radius:20px; color:#fff; margin-bottom:18px;
    box-shadow: var(--shadow-brand);
    border:1px solid rgba(255,255,255,.08);
}
/* hairline top highlight for a glassy, premium edge */
.topbar::before {
    content:""; position:absolute; inset:0; border-radius:20px; pointer-events:none;
    background:linear-gradient(180deg, rgba(255,255,255,.10), transparent 36%);
}
.topbar .mark {
    width:48px; height:48px; border-radius:14px; display:grid; place-items:center;
    font-size:25px; flex-shrink:0;
    background:linear-gradient(150deg, rgba(255,255,255,.22), rgba(255,255,255,.06));
    border:1px solid rgba(255,255,255,.28);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.3), 0 6px 16px rgba(0,0,0,.22);
}
.topbar .btitle { display:flex; align-items:center; gap:10px; }
.topbar h1 { color:#fff; font-size:20px; font-weight:800; margin:0; letter-spacing:-.02em; }
.topbar .kicker {
    font-size:9.5px; font-weight:700; letter-spacing:.16em; text-transform:uppercase;
    color:#A8C0E8; padding:3px 8px; border-radius:6px;
    background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.12);
}
.topbar .sub { color:#AFC2E0; font-size:12.5px; margin-top:4px; font-weight:450; letter-spacing:.005em; }
.topbar .right { margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.pill {
    display:inline-flex; align-items:center; gap:7px; padding:7px 13px; border-radius:999px;
    font-size:12px; font-weight:600; background:rgba(255,255,255,.10); color:#EAF0FA;
    border:1px solid rgba(255,255,255,.16); backdrop-filter: blur(8px);
}
.pill.ok  { background:rgba(22,163,74,.24);  border-color:rgba(74,222,128,.45); color:#D7FBE4; }
.pill.warn{ background:rgba(217,119,6,.30);  border-color:rgba(251,191,36,.45); color:#FDE7C2; }
.pill.err { background:rgba(220,38,38,.28);  border-color:rgba(248,113,113,.45); color:#FEDada; }
.pill .dot{ width:7px; height:7px; border-radius:50%; }
.pill.ok .dot  { background:#4ADE80; box-shadow:0 0 8px #4ADE80; animation:pulse 2s ease-in-out infinite; }
.pill.warn .dot{ background:#FBBF24; }
.pill.err .dot { background:#F87171; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.45} }

/* ── Panel headers (the numbered flow: 1 add docs · 2 ask) ─────────────────── */
.phead { display:flex; align-items:center; gap:10px; margin:2px 0 10px 0; }
.phead .step {
    width:24px; height:24px; border-radius:8px; display:grid; place-items:center;
    background: linear-gradient(135deg, var(--accent), var(--accent-2)); color:#fff;
    font-size:13px; font-weight:700; box-shadow:0 2px 6px rgba(79,107,237,.35);
}
.phead .t { font-size:14px; font-weight:700; color:var(--ink); letter-spacing:-.01em; }
.phead .h { font-size:12px; color:var(--ink-3); margin-left:auto; font-weight:500; }

/* ── Document cards ────────────────────────────────────────────────────────── */
.doc {
    background:var(--card); border:1px solid var(--line); border-radius:13px;
    padding:13px 15px; box-shadow:var(--shadow-sm); transition:border-color .2s, box-shadow .2s;
}
.doc:hover { border-color:#D5DCEA; box-shadow:var(--shadow-md); }
.doc.ready  { border-left:3px solid var(--ok); }
.doc.failed { border-left:3px solid var(--err); }
.doc.proc   { border-left:3px solid var(--accent); }
.doc-top { display:flex; align-items:center; gap:8px; }
.doc-name {
    flex:1; min-width:0; font-weight:600; font-size:13.5px; color:var(--ink);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;   /* no overflow past the card edge */
}
.doc-tags { display:flex; gap:5px; flex-shrink:0; }
.tag {
    font-size:10px; font-weight:600; padding:3px 8px; border-radius:999px; letter-spacing:.02em;
    background:#EEF2FF; color:var(--brand-2); border:1px solid #DBE3FF; text-transform:capitalize;
}
.tag.ok  { background:var(--ok-bg);  color:var(--ok);  border-color:var(--ok-br); }
.tag.err { background:var(--err-bg); color:var(--err); border-color:var(--err-br); }
.tag.proc{ background:#EFF6FF; color:var(--accent); border-color:#BFD3FF; }
.d-meta  { font-size:11.5px; color:var(--ink-3); margin-top:7px; }
.d-stage { font-size:11px; color:var(--ink-2); margin-top:6px; font-weight:500; }
.d-fail  { font-size:11.5px; color:var(--err); margin-top:7px; }
.bar { height:5px; background:#EAEFF6; border-radius:99px; overflow:hidden; margin-top:9px; }
.bar > div {
    height:100%; border-radius:99px; transition:width .5s ease;
    background:linear-gradient(90deg, var(--accent), var(--teal));
}
.bar.active > div {
    background-size:200% 100%; animation:shimmer 1.5s linear infinite;
    background-image:linear-gradient(90deg, var(--accent), var(--teal), var(--accent));
}
@keyframes shimmer { from{background-position:200% 0} to{background-position:0 0} }

/* ── File uploader ─────────────────────────────────────────────────────────── */
[data-testid="stFileUploaderDropzone"] {
    background:linear-gradient(180deg,#FFFFFF,#F7F9FF);
    border:1.5px dashed #C7D2E6 !important; border-radius:13px !important;
    transition:border-color .2s, background .2s; padding:14px 16px !important;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color:var(--accent) !important; background:linear-gradient(180deg,#FFFFFF,#EEF2FF);
}
/* The "Browse files" / upload button — branded, with a darken (never white) hover. */
[data-testid="stFileUploaderDropzone"] button {
    background:linear-gradient(135deg, var(--brand-2), var(--accent)) !important;
    color:#fff !important; border:none !important; border-radius:10px !important;
    font-weight:600 !important; box-shadow:0 2px 8px rgba(79,107,237,.28);
    transition:filter .15s, box-shadow .15s, transform .15s;
}
[data-testid="stFileUploaderDropzone"] button:hover {
    filter:brightness(1.07); color:#fff !important; transform:translateY(-1px);
    box-shadow:0 6px 16px rgba(79,107,237,.40); border:none !important;
}
[data-testid="stFileUploaderDropzone"] button:active { transform:translateY(0); }

/* ── Buttons ───────────────────────────────────────────────────────────────── */
.stButton button {
    font-weight:600; border-radius:11px; border:1px solid var(--line);
    background:var(--card); color:var(--ink); transition:all .15s; text-align:left;
}
.stButton button:hover { border-color:var(--accent); color:var(--brand-2); }
.stButton button[kind="primary"] {
    background:linear-gradient(135deg, var(--accent), var(--accent-2)); color:#fff; border:none;
    box-shadow:0 2px 8px rgba(79,107,237,.3);
}
.stButton button[kind="primary"]:hover {
    transform:translateY(-1px); box-shadow:0 6px 18px rgba(79,107,237,.4); color:#fff;
}

/* ── Empty / state hero ────────────────────────────────────────────────────── */
.hero {
    border:1px solid var(--line); border-radius:18px; padding:30px 30px 26px;
    background:linear-gradient(180deg,#FFFFFF 0%, #F1F5FF 100%); box-shadow:var(--shadow-md);
}
.hero .eyebrow {
    display:inline-block; font-size:11px; font-weight:700; letter-spacing:.1em;
    color:var(--accent); background:#EEF2FF; border:1px solid #DBE3FF;
    padding:4px 11px; border-radius:99px; text-transform:uppercase; margin-bottom:12px;
}
.hero h2 { color:var(--ink); font-size:23px; margin:0 0 8px; font-weight:800; letter-spacing:-.02em; }
.hero p  { color:var(--ink-2); font-size:14px; max-width:600px; margin:0; line-height:1.55; }

/* 3-step "how it works" strip */
.steps { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:20px; }
.step-c {
    background:#fff; border:1px solid var(--line); border-radius:13px; padding:15px 16px;
    box-shadow:var(--shadow-sm);
}
.step-c .n {
    width:26px; height:26px; border-radius:8px; display:grid; place-items:center; font-weight:700;
    font-size:13px; color:#fff; background:linear-gradient(135deg,var(--brand),var(--accent)); margin-bottom:9px;
}
.step-c .n { transition:transform .15s; }
.step-c:hover { border-color:#D5DCEA; box-shadow:var(--shadow-md); }
.step-c .st-t { font-size:13.5px; font-weight:700; color:var(--ink); }
.step-c .st-d { font-size:12px; color:var(--ink-2); margin-top:3px; line-height:1.45; }
.hintbar {
    margin-top:16px; padding:12px 16px; border-radius:12px; font-size:13px; color:var(--ink-2);
    background:linear-gradient(90deg,#EEF2FF,#F5F7FF); border:1px solid #DCE3F7;
    display:flex; align-items:center; gap:8px;
}
.hintbar::before { content:"←"; font-weight:800; color:var(--accent); font-size:15px; }

/* generic info panel (indexing / offline states) */
.note {
    border:1px solid var(--line); border-radius:14px; padding:22px 24px; background:#fff;
    box-shadow:var(--shadow-sm);
}
.note.center { text-align:center; }
.note h3 { font-size:16px; font-weight:700; color:var(--ink); margin:0 0 6px; }
.note p  { font-size:13px; color:var(--ink-2); margin:0; line-height:1.5; }
.note.err-panel { border-color:var(--err-br); background:var(--err-bg); }
.note.err-panel h3 { color:var(--err); }
.spinner {
    width:30px; height:30px; margin:0 auto; border-radius:50%;
    border:3px solid #E3E9F7; border-top-color:var(--accent);
    animation:spin 0.9s linear infinite;
}

/* ── Agentic trace ─────────────────────────────────────────────────────────── */
.trace {
    display:flex; flex-direction:column; gap:9px; padding:14px 16px; background:#F4F7FE;
    border:1px solid #E3E9F7; border-radius:13px; margin-bottom:6px;
}
.trace .row { display:flex; gap:10px; align-items:center; font-size:13px; color:var(--ink-3); }
.trace .row.done   { color:var(--ok); }
.trace .row.active { color:var(--brand-2); font-weight:600; }
.trace .ic { width:18px; text-align:center; }
.trace .note-r { font-size:11px; color:var(--ink-3); margin-left:auto; font-weight:500; }
.trace .row.active .ic { animation:spin 1.1s linear infinite; display:inline-block; }
@keyframes spin { from{transform:rotate(0)} to{transform:rotate(360deg)} }

/* ── Chat bubbles ──────────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:14px 18px !important; box-shadow:var(--shadow-sm); margin-bottom:2px;
}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarCustom"],
[data-testid="stChatMessage"] > div:first-child > div:first-child {
    background:linear-gradient(135deg, var(--brand), var(--accent)) !important; color:#fff !important;
}
/* ── Chat input — force light; disabled = soft grey, never dark ────────────── */
[data-testid="stBottom"], [data-testid="stBottomBlockContainer"] { background:transparent !important; }
[data-testid="stChatInput"] {
    background:var(--card) !important; border:1px solid var(--line) !important;
    border-radius:14px !important; box-shadow:var(--shadow-sm);
    transition:border-color .15s, box-shadow .15s;
}
[data-testid="stChatInput"]:focus-within {
    border-color:var(--accent) !important; box-shadow:0 0 0 3px var(--ring);
}
[data-testid="stChatInput"] > div, [data-testid="stChatInput"] textarea {
    background:transparent !important;
}
[data-testid="stChatInput"] textarea { font-size:15px !important; color:var(--ink) !important; }
[data-testid="stChatInput"] textarea::placeholder { color:var(--ink-3) !important; opacity:1; }
/* disabled state — light grey with muted text, not the default dark fill */
[data-testid="stChatInput"]:has(textarea:disabled) {
    background:#EEF1F7 !important; border-style:dashed !important; box-shadow:none;
}
[data-testid="stChatInput"] textarea:disabled {
    color:var(--ink-3) !important; -webkit-text-fill-color:var(--ink-3) !important;
}
[data-testid="stChatInput"] button { color:var(--accent) !important; }

/* ── Scrollable corpus rail — fixed height so many docs never blow up the page ── */
.corpus-scroll [data-testid="stVerticalBlockBorderWrapper"] { background:transparent; }
[data-testid="stVerticalBlock"]::-webkit-scrollbar { width:8px; }
[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb { background:#D3DAE8; border-radius:8px; }
[data-testid="stVerticalBlock"]::-webkit-scrollbar-thumb:hover { background:#B9C3D8; }

/* ── Answer meta + citations ───────────────────────────────────────────────── */
.ans-foot { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:12px;
    padding-top:11px; border-top:1px dashed var(--line); }
.chip {
    font-size:11px; font-weight:600; padding:3px 9px; border-radius:99px;
    background:#F1F5F9; color:var(--ink-2); border:1px solid var(--line);
}
.chip.conf-high { background:var(--ok-bg);   color:var(--ok);   border-color:var(--ok-br); }
.chip.conf-medium{ background:var(--warn-bg); color:var(--warn); border-color:var(--warn-br); }
.chip.conf-low  { background:var(--err-bg);  color:var(--err);  border-color:var(--err-br); }
.chip.intent    { background:#E0F2FE; color:#075985; border-color:#BAE6FD; }
.chip.intent.comparison { background:#FEF3C7; color:#92400E; border-color:#FDE68A; }
.chip.q { background:#fff; color:var(--ink-3); font-weight:500; max-width:420px;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.insuf {
    font-size:13px; color:var(--warn); background:var(--warn-bg); border:1px solid var(--warn-br);
    border-radius:10px; padding:9px 12px; margin-top:8px;
}
.cite-label { font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
    color:var(--ink-3); margin:10px 0 4px; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def html(markup: str) -> None:
    """Render raw HTML safely. `dedent` + `strip` guarantees the first line is at
    column 0, so Markdown never mistakes indented markup for a code block (the
    bug that printed literal `</div>` on screen)."""
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


def _ss(key: str, default: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = default


_ss("session_id", uuid.uuid4().hex[:10])
_ss("messages", [])
_ss("uploaded_signatures", set())
_ss("ingestion_lock", False)
_ss("pending_question", None)
_ss("active_citation", None)


# ── HTTP ────────────────────────────────────────────────────────────────────--
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
    """Parse the SSE stream from /chat/stream into (event, data) tuples."""
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


# ── Top bar ─────────────────────────────────────────────────────────────────--
def render_topbar(health: dict | None) -> None:
    if health is None:
        right = ('<span class="pill err"><span class="dot"></span>Backend offline</span>')
    else:
        services = health.get("services", {})
        n_ok = sum(1 for v in services.values() if v)
        n_all = len(services) or 1
        cls = "ok" if n_ok == n_all else ("warn" if n_ok else "err")
        model = escape(health.get("chat_model", ""))
        right = (
            (f'<span class="pill">🤖 {model}</span>' if model else "")
            + f'<span class="pill">🪪 {st.session_state.session_id}</span>'
            + f'<span class="pill {cls}"><span class="dot"></span>Azure {n_ok}/{n_all}</span>'
        )
    html(f"""
    <div class="topbar">
        <div class="mark">🛡️</div>
        <div>
            <div class="btitle">
                <h1>Insurance Document Intelligence</h1>
                <span class="kicker">Grounded&nbsp;RAG</span>
            </div>
            <div class="sub">Grounded, auditable answers from your policies, claims and medical records — every fact traced to its exact source page.</div>
        </div>
        <div class="right">{right}</div>
    </div>
    """)


# ── Document cards ────────────────────────────────────────────────────────────
def _bar_pct(status: str) -> int:
    try:
        return int((STAGE_ORDER.index(status) + 1) / len(STAGE_ORDER) * 100)
    except ValueError:
        return 100


def render_document_card(doc: dict) -> None:
    status = doc.get("status", "uploaded")
    name = escape(doc.get("doc_name", "document"))
    doc_type = escape((doc.get("doc_type") or "").strip())
    pages, chunks = doc.get("pages") or 0, doc.get("chunks") or 0

    if status == "ready":
        accent, badge = "ready", '<span class="tag ok">✓ Ready</span>'
        type_tag = f'<span class="tag">{doc_type}</span>' if doc_type else ""
        body = f'<div class="d-meta">{pages} pages · {chunks} searchable chunks</div>'
    elif status == "failed":
        accent, badge, type_tag = "failed", '<span class="tag err">Failed</span>', ""
        body = f'<div class="d-fail">⚠ {escape(doc.get("detail") or "Processing failed")}</div>'
    else:
        accent, badge, type_tag = "proc", '<span class="tag proc">Processing</span>', ""
        body = (f'<div class="bar active"><div style="width:{_bar_pct(status)}%"></div></div>'
                f'<div class="d-stage">{STAGE_LABEL.get(status, status)}…</div>')

    html(f"""
    <div class="doc {accent}">
        <div class="doc-top">
            <div class="doc-name" title="{name}">{name}</div>
            <div class="doc-tags">{type_tag}{badge}</div>
        </div>
        {body}
    </div>
    """)


# ── Ingestion ─────────────────────────────────────────────────────────────────
def auto_ingest(uploaded_files: list[Any] | None) -> bool:
    """POST newly-dropped files immediately (no Ingest button). Re-uploads of the
    same (name, size) are skipped so a re-render never double-posts. Returns True
    when something new was accepted, so the caller can refresh the view at once."""
    if not uploaded_files or st.session_state.ingestion_lock:
        return False
    seen = st.session_state.uploaded_signatures
    payload: list[tuple[str, tuple[str, bytes]]] = []
    for f in uploaded_files:
        sig = (f.name, getattr(f, "size", None) or len(f.getvalue()))
        if sig in seen:
            continue
        payload.append(("files", (f.name, f.getvalue())))
        seen.add(sig)
    if not payload:
        return False
    st.session_state.ingestion_lock = True
    try:
        r = _post("/documents", files=payload, timeout=60)
        if r.status_code == 202:
            st.toast(f"Added {len(r.json())} document(s) — indexing now", icon="🚀")
            return True
        try:
            st.error(r.json().get("detail", r.text))
        except ValueError:
            st.error(r.text)
    except requests.RequestException as exc:
        st.error(f"API unreachable: {exc}")
    finally:
        st.session_state.ingestion_lock = False
    return False


def load_demo_corpus() -> bool:
    if not SAMPLE_DIR.exists():
        st.error(f"sample-documents/ not found at {SAMPLE_DIR}.")
        return False
    files = [f for f in sorted(SAMPLE_DIR.glob("*"))
             if f.suffix.lower() in {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}]
    if not files:
        st.error("No sample documents found.")
        return False
    payload = [("files", (f.name, f.read_bytes())) for f in files]
    try:
        r = _post("/documents", files=payload, timeout=90)
        if r.status_code == 202:
            st.toast(f"Loaded {len(r.json())} sample document(s)", icon="📚")
            return True
        st.error(r.json().get("detail", r.text))
    except requests.RequestException as exc:
        st.error(f"API unreachable: {exc}")
    return False


# ── Corpus panel (fragment: polls only while ingestion is in flight) ──────────
def corpus_panel_body() -> None:
    """Render the live corpus list. Decorated at call-time with `run_every` so it
    re-runs *itself* (fragment scope) on a timer while documents are processing,
    and stops the moment everything settles — no full-page rerun, no flicker."""
    docs = fetch_documents()
    if docs is None:
        html('<div class="note err-panel"><h3>Backend not reachable</h3>'
             '<p>Start the API (<code>uvicorn src.api.main:app</code>) and confirm it is '
             'listening on port 8000.</p></div>')
        return

    if not docs:
        html("""
        <div class="note center" style="padding:28px 18px;">
            <div style="font-size:30px;">📁</div>
            <h3 style="margin-top:10px;">Your corpus is empty</h3>
            <p>Add documents above, or load the demo corpus to explore the experience instantly.</p>
        </div>
        """)
        return

    ready = sum(1 for d in docs if d["status"] == "ready")
    in_flight = [d for d in docs if d["status"] not in ("ready", "failed")]
    failed = sum(1 for d in docs if d["status"] == "failed")

    summary = f"{ready} ready"
    if in_flight:
        summary += f" · {len(in_flight)} processing"
    if failed:
        summary += f" · {failed} failed"
    html(f'<div class="phead" style="margin:2px 0 6px;">'
         f'<span class="t" style="font-size:12px;font-weight:700;letter-spacing:.04em;'
         f'text-transform:uppercase;color:var(--ink-3);">Corpus · {len(docs)}</span>'
         f'<span class="h">{summary}</span></div>')

    # Processing first, so the live action is at the top of the list.
    order = {"uploaded": 0, "extracting": 0, "classifying": 0, "chunking": 0,
             "indexing": 0, "failed": 1, "ready": 2}
    ordered = sorted(docs, key=lambda d: order.get(d["status"], 0))
    # Fixed-height, internally-scrolling rail: a large corpus scrolls inside this
    # box instead of stretching the whole page and leaving the chat side blank.
    if len(ordered) > 4:
        with st.container(height=460):
            for doc in ordered:
                render_document_card(doc)
    else:
        for doc in ordered:
            render_document_card(doc)

    # When everything has settled, do exactly ONE app rerun so the chat gate and
    # the polling interval recompute. After that the fragment stays calm.
    if not in_flight and st.session_state.get("_corpus_polling"):
        st.session_state["_corpus_polling"] = False
        st.rerun()


# ── Onboarding / state-aware right panel ───────────────────────────────────────
def render_steps_strip() -> None:
    html("""
    <div class="steps">
        <div class="step-c"><div class="n">1</div><div class="st-t">Ingest</div>
            <div class="st-d">Add policies, claim forms, scans or medical reports. Azure Document Intelligence extracts the layout automatically.</div></div>
        <div class="step-c"><div class="n">2</div><div class="st-t">Index</div>
            <div class="st-d">Content is classified, chunked by structure and embedded into a hybrid search index — progress streams live on the left.</div></div>
        <div class="step-c"><div class="n">3</div><div class="st-t">Interrogate</div>
            <div class="st-d">Ask in natural language. Every answer is grounded in your corpus and cited to the exact source page for audit.</div></div>
    </div>
    """)


def render_cold_start() -> None:
    html("""
    <div class="hero">
        <span class="eyebrow">Retrieval-augmented · grounded · auditable</span>
        <h2>Turn dense insurance documents into precise, cited answers</h2>
        <p>Upload your policies, claim forms and medical reports, then ask in plain English.
        Every answer is grounded <strong>only</strong> in your own documents and traced to the
        exact source page — so each fact can be verified in a single click.</p>
    </div>
    """)
    render_steps_strip()
    html('<div class="hintbar">Begin in the <strong>Your documents</strong> panel on the left — '
         'drop your files, or load the demo corpus to explore instantly.</div>')


def render_indexing_wait(in_flight: int) -> None:
    plural = "s" if in_flight != 1 else ""
    html(f"""
    <div class="note center" style="padding:38px 24px;">
        <div class="spinner"></div>
        <h3 style="margin-top:14px;">Building your knowledge base</h3>
        <p>Extracting, classifying and embedding {in_flight} document{plural}. Questions unlock
        automatically the moment the first document is ready — live progress is on the left.</p>
    </div>
    """)


def render_suggestions() -> None:
    html('<div class="cite-label" style="margin-top:2px;">Start with a question</div>')
    cols = st.columns(2)
    for i, (icon, title, question) in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(f"{icon}  {title}\n\n{question}",
                         key=f"sugg_{i}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()


# ── Citation modal ─────────────────────────────────────────────────────────────
@st.dialog("Source preview", width="large")
def citation_dialog(c: dict) -> None:
    st.markdown(f"#### [{c['source_id']}] {c['doc_name']} · page {c['page']}")
    st.caption("Verbatim quote from the source")
    st.info(c.get("quote", ""))
    doc_id = c.get("doc_id")
    if not doc_id:
        st.caption("Source document id unavailable for this citation.")
        return
    file_url = f"{API}/documents/{doc_id}/file"
    ext = Path(c["doc_name"]).suffix.lower()
    st.markdown(f"**Original document — [open in new tab ↗]({file_url})**")
    if ext == ".pdf":
        components.iframe(f"{file_url}#page={c['page']}", height=620, scrolling=True)
    elif ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        st.image(file_url, use_container_width=True)
    else:
        st.caption(f"{ext.upper()} preview not supported inline; use the link above.")


# ── Chat rendering ─────────────────────────────────────────────────────────────
TRACE_STAGES = [
    ("planning",   "Understanding your question"),
    ("retrieving", "Searching the document index"),
    ("grading",    "Checking the evidence is sufficient"),
    ("generating", "Grounding the answer in sources"),
]


def render_trace_html(state: dict[str, str]) -> str:
    rows = []
    for key, label in TRACE_STAGES:
        # The agentic evidence-check only runs on simple-intent turns; hide the
        # row entirely when it didn't fire (comparison mode / AGENTIC_RAG off).
        if key == "grading" and "grading" not in state:
            continue
        s = state.get(key, "pending")
        ic, cls = ("✅", "done") if s == "done" else (("⏳", "active") if s == "active" else ("•", ""))
        note = escape(state.get(f"{key}_note", ""))
        note_html = f'<span class="note-r">{note}</span>' if note else ""
        rows.append(f'<div class="row {cls}"><span class="ic">{ic}</span><span>{label}</span>{note_html}</div>')
    return f'<div class="trace">{"".join(rows)}</div>'


def render_citation_chips(citations: list[dict], msg_idx: int) -> None:
    if not citations:
        return
    html('<div class="cite-label">Sources</div>')
    cols = st.columns(min(len(citations), 4))
    for i, c in enumerate(citations):
        with cols[i % len(cols)]:
            if st.button(f"[{c['source_id']}] {c['doc_name']} · p{c['page']}",
                         key=f"cite_{msg_idx}_{i}", use_container_width=True):
                st.session_state.active_citation = c
                citation_dialog(c)


def render_answer_footer(meta: dict, n_citations: int) -> None:
    conf = escape(meta.get("confidence") or "—")
    intent = escape(meta.get("intent", "simple"))
    query = escape(meta.get("standalone_query", ""))
    html(f"""
    <div class="ans-foot">
        <span class="chip conf-{conf}">confidence: {conf}</span>
        <span class="chip intent {intent}">{intent}</span>
        <span class="chip">{n_citations} citation(s)</span>
        <span class="chip q" title="{query}">🔎 {query}</span>
    </div>
    """)


def render_answer(msg: dict, idx: int) -> None:
    st.markdown(msg["answer_markdown"])
    if msg.get("insufficient_context"):
        html('<div class="insuf">⚠ The uploaded documents don\'t contain enough information '
             'to fully answer this. Try adding the relevant policy or rephrasing.</div>')
    render_citation_chips(msg.get("citations", []), idx)
    if msg.get("meta"):
        render_answer_footer(msg["meta"], len(msg.get("citations", [])))


def render_history() -> None:
    for idx, m in enumerate(st.session_state.messages):
        if m["role"] == "user":
            with st.chat_message("user", avatar="🧑‍💼"):
                st.markdown(m["content"])
        else:
            with st.chat_message("assistant", avatar="🛡️"):
                render_answer(m, idx)


def run_chat_turn(question: str) -> None:
    """Stream one turn: user msg → trace → tokens → citations → footer. No
    `st.rerun()` — everything renders into stable placeholders, then the message
    is appended so the next natural rerun finds it in history."""
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🛡️"):
        trace_ph = st.empty()
        answer_ph = st.empty()
        cite_ph = st.empty()
        foot_ph = st.empty()

        trace: dict[str, str] = {"planning": "active"}
        trace_ph.markdown(render_trace_html(trace), unsafe_allow_html=True)

        buffer, final = "", None
        try:
            for event, data in stream_chat(question):
                if event == "planned":
                    trace["planning"] = "done"
                    trace["planning_note"] = f"intent: {data.get('intent', '—')}"
                    trace["retrieving"] = "active"
                elif event == "grading":
                    trace["retrieving"] = "done"          # first search is complete
                    trace["grading"] = "active"
                elif event == "refining":
                    trace["grading"] = "active"
                    rq = (data.get("refined_query") or "").strip()
                    trace["grading_note"] = f"weak → re-searching: {rq[:46]}"
                elif event == "graded":
                    trace["grading"] = "done"
                    trace["grading_note"] = ("evidence sufficient" if data.get("sufficient")
                                             else f"re-searched · +{data.get('added', 0)} chunk(s)")
                elif event == "retrieved":
                    trace["retrieving"] = "done"
                    trace["retrieving_note"] = (f"{data.get('chunk_count', 0)} chunks · "
                                                f"{len(data.get('documents', []))} doc(s)")
                elif event == "generating":
                    trace["generating"] = "active"
                elif event == "token":
                    buffer += data.get("delta", "")
                    answer_ph.markdown(buffer + " ▌")
                    continue
                elif event == "done":
                    trace["generating"] = "done"
                    final = data
                elif event == "error":
                    answer_ph.error(f"Answer generation failed: {data.get('error', 'unknown')}")
                    return
                trace_ph.markdown(render_trace_html(trace), unsafe_allow_html=True)
        except requests.RequestException as exc:
            answer_ph.error(f"Request failed: {exc}")
            return

        if not final:
            answer_ph.error("No answer received from the backend.")
            return

        trace_ph.empty()
        answer = final["answer"]
        doc_ids = {s["doc_name"]: s["doc_id"] for s in final.get("sources", [])}
        for c in answer["citations"]:
            c["doc_id"] = doc_ids.get(c["doc_name"], "")

        final_text = answer["answer_markdown"]
        if len(buffer) > len(final_text):
            final_text = buffer
        answer_ph.markdown(final_text)

        msg = {
            "role": "assistant",
            "answer_markdown": final_text,
            "citations": answer["citations"],
            "insufficient_context": answer.get("insufficient_context", False),
            "meta": {"standalone_query": final["standalone_query"],
                     "intent": final["intent"], "confidence": answer["confidence"]},
        }
        st.session_state.messages.append(msg)
        idx = len(st.session_state.messages) - 1
        if msg["insufficient_context"]:
            with answer_ph.container():
                st.markdown(final_text)
                html('<div class="insuf">⚠ The uploaded documents don\'t contain enough '
                     'information to fully answer this.</div>')
        with cite_ph.container():
            render_citation_chips(answer["citations"], idx)
        with foot_ph.container():
            render_answer_footer(msg["meta"], len(answer["citations"]))


# ── Main ───────────────────────────────────────────────────────────────────────
health = fetch_health()
render_topbar(health)

docs_now = fetch_documents()
backend_ok = docs_now is not None
ready_count = sum(1 for d in (docs_now or []) if d["status"] == "ready")
in_flight_count = sum(1 for d in (docs_now or []) if d["status"] not in ("ready", "failed"))
st.session_state["_corpus_polling"] = in_flight_count > 0

LEFT, RIGHT = st.columns([0.33, 0.67], gap="large")

with LEFT:
    html('<div class="phead"><span class="step">1</span><span class="t">Your documents</span></div>')
    uploaded = st.file_uploader(
        "Drop PDF / DOCX / JPG / PNG / TIFF",
        type=["pdf", "docx", "jpg", "jpeg", "png", "tif", "tiff"],
        accept_multiple_files=True, label_visibility="collapsed", key="uploader",
    )
    if auto_ingest(uploaded):
        st.session_state["_corpus_polling"] = True
        st.rerun()
    if st.button("📚  Load demo corpus", use_container_width=True, key="demo_side"):
        # Guard against re-adding the same five samples on a second click.
        if st.session_state.get("demo_loaded") and docs_now:
            st.toast("Demo corpus is already loaded.", icon="📚")
        elif load_demo_corpus():
            st.session_state["demo_loaded"] = True
            st.session_state["_corpus_polling"] = True
            st.rerun()

    # Poll only while ingestion is in flight; otherwise render once and stay calm.
    interval = 2.0 if in_flight_count else None
    st.fragment(run_every=interval)(corpus_panel_body)()

with RIGHT:
    head = st.columns([1, 0.28])
    with head[0]:
        html('<div class="phead"><span class="step">2</span><span class="t">Ask your documents</span></div>')
    with head[1]:
        if st.session_state.messages:
            if st.button("🆕 New chat", use_container_width=True, key="new_chat"):
                try:
                    requests.delete(f"{API}/sessions/{st.session_state.session_id}", timeout=4)
                except requests.RequestException:
                    pass
                st.session_state.session_id = uuid.uuid4().hex[:10]
                st.session_state.messages = []
                st.session_state.active_citation = None
                st.rerun()

    # State-aware body: offline → cold start → indexing → ready/suggestions → chat.
    if not backend_ok:
        html('<div class="note err-panel"><h3>Backend not reachable</h3>'
             '<p>Start the API with <code>uvicorn src.api.main:app</code> and confirm it is '
             'listening on <code>http://localhost:8000</code>, then reload this page.</p></div>')
    elif st.session_state.messages or st.session_state.pending_question:
        render_history()
    elif ready_count == 0 and in_flight_count == 0:
        render_cold_start()
    elif ready_count == 0 and in_flight_count > 0:
        render_indexing_wait(in_flight_count)
    else:
        html("""
        <div class="hero" style="padding:22px 26px;">
            <span class="eyebrow">Knowledge base ready</span>
            <h2 style="font-size:20px;">Ask anything across your corpus</h2>
            <p>Answers are grounded only in your documents and cited to the exact source page — verifiable in one click.</p>
        </div>
        """)
        render_suggestions()

    # Run a queued suggestion, then accept new input.
    pending = st.session_state.pending_question
    if pending:
        st.session_state.pending_question = None
        run_chat_turn(pending)

    chat_ready = backend_ok and ready_count > 0
    placeholder = ("Ask about your documents…" if chat_ready
                   else "Add and index at least one document to start asking…")
    if question := st.chat_input(placeholder, disabled=not chat_ready):
        run_chat_turn(question)
