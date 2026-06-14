"""Streamlit UI — Insurance Document Intelligence.

A grounded document-Q&A workspace built as a real product shell, not a script:

    Sidebar (control panel)            Main (conversation surface)
    ───────────────────────            ───────────────────────────
    · brand + grounded-RAG mark        · one compact hero / welcome
    · upload + load demo               · suggestion cards (Material icons)
    · live corpus list                 · grounded, cited chat thread
    · system-status card               · agentic trace per turn
    · tech footer                      · light, pinned chat input

Design language is shared with the Plum Claims console (same Inter + violet
token system) so the two apps read as one product family.

Key engineering decisions (and the bugs they retire):

* APP SHELL, NOT A SPLIT PAGE.  Documents live in Streamlit's real sidebar; the
  main column is a single chat surface.  This is what makes it feel like an app
  instead of two competing panels.

* ZERO-FLICKER CORPUS.  The corpus renders as ONE html injection inside an
  `@st.fragment` that auto-polls with `run_every` *only while ingestion is in
  flight* and reruns ITSELF — never the whole page.  The old code painted ~15
  separate markdown blocks inside a height-container every poll, which flashed.

* CHAT INPUT IS ALWAYS LIGHT.  Selectors target Streamlit 1.58's actual chat-input
  DOM and force every inner baseweb wrapper transparent, so the dark fill that
  bled through before can't appear.

* NO RAW HTML LEAKS.  All markup goes through `html()`, which dedents + strips so
  the first line sits at column 0 and Markdown never treats it as a code block.

The UI talks only to the FastAPI backend. No Azure SDK calls here."""
from __future__ import annotations

import base64
import json
import os
import re
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
# (material icon, category, question) — icons render via Streamlit's :material/: syntax.
# Each maps to a real capability on the demo corpus: limit lookup, key-value
# extraction from a scanned claim form, clinical summarisation, and a multi-policy
# comparison fan-out — so the suggestions demonstrate genuine, gradeable value.
SUGGESTED_QUESTIONS = [
    (":material/fact_check:", "Claim eligibility check",
     "Jane Q. Member has submitted an appendicitis claim (ICD-10 K35.80) for $9,560 under the Gold Shield policy. Is the claim likely eligible? Check the relevant waiting periods and exclusions, then calculate the approximate member out-of-pocket after deductible and co-insurance."),
    (":material/summarize:", "Full clinical extraction",
     "Extract a complete structured summary from the medical report: patient name and MRN, admission and discharge dates, length of stay, primary and secondary diagnoses with ICD codes, procedures performed, attending physician, discharge condition, prescribed medications, and follow-up instructions."),
    (":material/calculate:", "Out-of-pocket estimate",
     "Under the Gold Shield policy, what would a member pay out-of-pocket for a 5-day inpatient hospitalization billed at $15,000? Break down the individual deductible, co-insurance, any applicable annual sub-limits, and the final member liability."),
    (":material/compare_arrows:", "Best-value policy comparison",
     "Compare inpatient hospitalization and outpatient treatment benefits — annual limits, individual deductibles, co-payments, and any notable exclusions — across all three policies. Which plan offers the lowest member cost for a major surgery requiring hospitalization?"),
]

# Inline shield mark — crisper than an emoji inside the brand square.
SHIELD_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
    '<path d="m9 12 2 2 4-4"/></svg>'
)
# Person glyph for the (right-aligned) user bubble avatar — clean line icon, no emoji.
USER_SVG = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
)
# Assistant avatar — a Material shield icon (Streamlit renders it cleanly; not an emoji).
ASSISTANT_AVATAR = ":material/shield:"

st.set_page_config(
    page_title="Insurance Document Intelligence",
    page_icon="🛡️", layout="wide", initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════════ design system
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root{
  --violet:#6D28D9; --violet-2:#7C3AED; --violet-3:#5B21B6; --indigo:#4F46E5;
  --ink:#1E1B2E; --ink-2:#5B5772; --ink-3:#8B86A3; --ink-4:#A8A3BC;
  --line:#ECE9F4; --line-2:#E9E7F3; --bg:#F6F7FB; --card:#FFFFFF; --soft:#F8F7FD;
  --ok:#10B981; --ok-ink:#15803D; --ok-bg:#ECFDF5; --ok-br:#A7F3D0;
  --warn:#F59E0B; --warn-ink:#B45309; --warn-bg:#FFFBEB; --warn-br:#FDE68A;
  --err:#EF4444; --err-ink:#B91C1C; --err-bg:#FEF2F2; --err-br:#FECACA;
  --info:#3B82F6;
  --ring:rgba(124,58,237,.20);
  --shadow-sm:0 1px 6px rgba(16,24,40,.05);
  --shadow-md:0 10px 30px rgba(76,29,149,.10);
  --shadow-hero:0 14px 38px rgba(76,29,149,.30);
}
html, body, [class*="css"], .stApp { font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif; color:var(--ink); }
.stApp { background:var(--bg); }

/* Keep the native header — it hosts the sidebar collapse/expand toggle, so we
   must NOT zero it (that was hiding the re-open control). Just make it
   transparent and pull the content up so there's no big top gap. */
[data-testid="stHeader"]{ background:transparent; }
#MainMenu, footer { visibility:hidden; }
.block-container{ padding-top:.4rem !important; padding-bottom:2rem !important; max-width:1180px; }
/* Trim the empty gap under the pinned chat input. */
[data-testid="stBottom"] > div{ padding-bottom:.4rem !important; }
[data-testid="stBottomBlockContainer"]{ padding-top:.3rem !important; padding-bottom:.5rem !important; }
[data-testid="stVerticalBlock"]{ gap:.7rem; }

/* Hide only the "Running…" status widget — NOT the whole toolbar (the sidebar
   re-open control can live there). Deploy/menu are already hidden via
   toolbarMode="minimal" in config.toml. */
[data-testid="stStatusWidget"]{ display:none !important; }
/* ALWAYS keep the sidebar collapse/expand controls clickable and on top so the
   sidebar can never get stuck hidden. */
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapseButton"]{
  visibility:visible !important; opacity:1 !important; z-index:1001 !important; }
[data-stale="true"], [data-stale="true"] *{ opacity:1 !important; }
[data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] *{ transition:none !important; }
[data-testid="stSkeleton"]{ display:none !important; }

/* shared micro-label (uppercase eyebrow) */
.microlabel{ font-size:.7rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-4); margin:.2rem .1rem .35rem; }
.section-title{ font-size:1.05rem; font-weight:800; color:var(--ink); margin:.2rem 0 .35rem; letter-spacing:-.01em; }
.section-sub{ color:var(--ink-2); font-size:.86rem; margin:-.2rem 0 .7rem; line-height:1.45; }

/* ───────────────────────── sidebar (app shell) ───────────────────────── */
/* Wider rail so the brand title fits cleanly — but ONLY when expanded, so the
   collapse control still hands the full width back to the main column. */
[data-testid="stSidebar"]{ background:#fff; border-right:1px solid var(--line-2); }
[data-testid="stSidebar"][aria-expanded="true"]{ width:340px !important; min-width:340px !important; }
[data-testid="stSidebar"] .block-container{ padding-top:1.2rem; padding-left:1.1rem; padding-right:1.1rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{ gap:.55rem; }
/* brand is its own header band, separated from the controls below it */
.brand{ display:flex; align-items:center; gap:.7rem; padding:.1rem .1rem 1rem; margin-bottom:.6rem;
  border-bottom:1px solid var(--line); }
.brand-logo{ width:44px; height:44px; border-radius:13px; flex:0 0 44px; display:grid; place-items:center;
  background:linear-gradient(135deg,var(--violet-2),var(--indigo));
  box-shadow:0 6px 16px rgba(109,40,217,.35), inset 0 1px 0 rgba(255,255,255,.3); }
.brand-name{ font-weight:800; font-size:1.02rem; color:var(--ink); line-height:1.15; letter-spacing:-.01em; }
.brand-sub{ font-size:.64rem; color:var(--ink-3); letter-spacing:.14em; margin-top:.3rem; text-transform:uppercase; font-weight:700; }

/* upload zone */
[data-testid="stFileUploaderDropzone"]{
  background:linear-gradient(180deg,#fff,#FAF9FE); border:1.5px dashed #D6CFEC !important;
  border-radius:12px !important; padding:12px 14px !important; transition:border-color .18s, background .18s; }
[data-testid="stFileUploaderDropzone"]:hover{ border-color:var(--violet-2) !important;
  background:linear-gradient(180deg,#fff,#F3EFFC); }
[data-testid="stFileUploaderDropzone"] button{
  background:linear-gradient(135deg,var(--violet-3),var(--violet-2)) !important; color:#fff !important;
  border:none !important; border-radius:9px !important; font-weight:600 !important;
  box-shadow:0 2px 8px rgba(109,40,217,.25); transition:filter .15s, transform .15s; }
[data-testid="stFileUploaderDropzone"] button:hover{ filter:brightness(1.07); transform:translateY(-1px); color:#fff !important; }

/* corpus list — single injection, scrolls internally */
.corpus-head{ display:flex; align-items:baseline; justify-content:space-between; margin:.5rem .1rem .25rem; }
.corpus-head .ct{ font-size:.7rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3); }
.corpus-head .cs{ font-size:.72rem; color:var(--ink-3); font-weight:500; }
.corpus{ display:flex; flex-direction:column; gap:.5rem; max-height:42vh; overflow-y:auto;
  padding:.1rem .15rem .2rem 0; margin-right:-.15rem; }
.corpus::-webkit-scrollbar{ width:7px; }
.corpus::-webkit-scrollbar-thumb{ background:#DAD4EC; border-radius:8px; }
.corpus::-webkit-scrollbar-thumb:hover{ background:#C4BCE0; }
.doc{ background:#fff; border:1px solid var(--line); border-left:3px solid var(--line);
  border-radius:11px; padding:.6rem .7rem; box-shadow:var(--shadow-sm); }
.doc.ready{ border-left-color:var(--ok); } .doc.failed{ border-left-color:var(--err); }
.doc.proc{ border-left-color:var(--violet-2); }
.doc-top{ display:flex; align-items:center; gap:.4rem; }
.doc-name{ flex:1; min-width:0; font-weight:600; font-size:.82rem; color:var(--ink);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tag{ font-size:.58rem; font-weight:700; letter-spacing:.04em; padding:.13rem .42rem; border-radius:6px;
  text-transform:uppercase; white-space:nowrap; flex:0 0 auto;
  background:#EDE9FE; color:var(--violet); }
.tag.ok{ background:var(--ok-bg); color:var(--ok-ink); } .tag.err{ background:var(--err-bg); color:var(--err-ink); }
.tag.proc{ background:#EDE9FE; color:var(--violet); }
.d-meta{ font-size:.72rem; color:var(--ink-3); margin-top:.4rem; }
.d-stage{ font-size:.7rem; color:var(--ink-2); margin-top:.35rem; font-weight:500; }
.d-fail{ font-size:.72rem; color:var(--err-ink); margin-top:.4rem; }
.bar{ height:5px; background:#EEE9F8; border-radius:99px; overflow:hidden; margin-top:.45rem; }
.bar>div{ height:100%; border-radius:99px; background:linear-gradient(90deg,var(--violet-2),var(--indigo));
  transition:width .5s ease; }
.bar.active>div{ background-size:200% 100%; animation:shimmer 1.5s linear infinite;
  background-image:linear-gradient(90deg,var(--violet-2),var(--indigo),var(--violet-2)); }
@keyframes shimmer{ from{background-position:200% 0} to{background-position:0 0} }

/* status card */
.status-card{ background:var(--soft); border:1px solid var(--line); border-radius:13px;
  padding:.8rem .9rem; margin-top:.6rem; }
.status-row{ display:flex; align-items:center; gap:.5rem; font-size:.78rem; color:var(--ink-2); margin:.28rem 0; }
.status-row b{ color:var(--ink); font-weight:600; }
.dot{ width:8px; height:8px; border-radius:50%; flex:0 0 8px; }
.dot-on{ background:var(--ok); box-shadow:0 0 7px rgba(16,185,129,.6); }
.dot-warn{ background:var(--warn); } .dot-off{ background:#94A3B8; }
.mono{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.7rem; }
.tech-foot{ color:var(--ink-4); font-size:.68rem; margin-top:.8rem; line-height:1.5; }

/* ───────────────────────── buttons ───────────────────────── */
.stButton button{ font-weight:600; border-radius:11px; border:1px solid var(--line);
  background:#fff; color:var(--ink); transition:all .15s; }
.stButton button:hover{ border-color:var(--violet-2); color:var(--violet); }
.stButton button[kind="primary"]{ background:linear-gradient(135deg,var(--violet-2),var(--indigo));
  color:#fff; border:none; box-shadow:0 4px 12px rgba(91,33,182,.26); }
.stButton button[kind="primary"]:hover{ transform:translateY(-1px); color:#fff;
  box-shadow:0 8px 20px rgba(91,33,182,.34); }
/* sidebar buttons full-bleed and calm */
[data-testid="stSidebar"] .stButton button{ text-align:left; justify-content:flex-start; }

/* ───────────────────────── hero (compact) ───────────────────────── */
.hero{ border-radius:16px; padding:1.1rem 1.35rem; color:#fff; margin-bottom:.85rem;
  background:radial-gradient(900px 300px at 0% 0%, var(--violet-2) 0%, var(--violet-3) 50%, #3B1E78 100%);
  box-shadow:var(--shadow-hero); position:relative; overflow:hidden; }
.hero::before{ content:""; position:absolute; inset:0;
  background:linear-gradient(180deg,rgba(255,255,255,.10),transparent 38%); pointer-events:none; }
.hero .eyebrow{ display:inline-block; font-size:.64rem; font-weight:700; letter-spacing:.12em;
  text-transform:uppercase; color:#E9E2FF; background:rgba(255,255,255,.14);
  border:1px solid rgba(255,255,255,.22); padding:.2rem .55rem; border-radius:999px; margin-bottom:.5rem; }
.hero h1{ font-size:1.22rem; font-weight:800; margin:0 0 .3rem; letter-spacing:-.01em; line-height:1.2; color:#fff; }
.hero p{ font-size:.86rem; color:#E9E2FF; margin:0; max-width:660px; line-height:1.5; }
.hero p strong{ color:#fff; }
.hero-chips{ display:flex; flex-wrap:wrap; gap:.4rem; margin-top:.7rem; }
.hero-chip{ background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.24);
  padding:.24rem .6rem; border-radius:999px; font-size:.7rem; font-weight:600; color:#fff;
  display:inline-flex; align-items:center; gap:.35rem; }

/* capabilities strip — the tech line, moved out of the sidebar into the overview */
.caps{ display:grid; grid-template-columns:repeat(4,1fr); gap:.7rem; margin:.2rem 0 1.1rem; }
.cap{ display:flex; align-items:flex-start; gap:.6rem; background:#fff; border:1px solid var(--line);
  border-radius:14px; padding:.85rem .9rem; box-shadow:var(--shadow-sm); position:relative; overflow:hidden;
  transition:border-color .15s, box-shadow .15s, transform .15s; }
.cap::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
  background:linear-gradient(180deg,var(--violet-2),var(--indigo)); }
.cap:hover{ border-color:#D8CFF0; box-shadow:var(--shadow-md); transform:translateY(-1px); }
.cap-ic{ width:34px; height:34px; flex:0 0 34px; border-radius:10px; display:grid; place-items:center;
  background:linear-gradient(135deg,#EDE9FE,#E0E7FF); color:var(--violet); }
.cap-ic svg{ width:18px; height:18px; }
.cap b{ display:block; font-size:.85rem; color:var(--ink); font-weight:800; margin-bottom:.15rem; letter-spacing:-.01em; }
.cap span{ font-size:.74rem; color:var(--ink-3); line-height:1.4; }
@media (max-width:900px){ .caps{ grid-template-columns:repeat(2,1fr); } }

/* source-preview modal: compact header, generous page area */
.src-head{ font-size:1rem; font-weight:800; color:var(--ink); letter-spacing:-.01em; margin:.1rem 0 .6rem; }
.src-head span{ color:var(--ink-3); font-weight:600; }
[data-testid="stDialog"] [data-testid="stDialogContent"]{ padding-top:1rem !important; }

/* ───────────────────────── pipeline strip (how it works) ───────────────────────── */
.pipe{ display:flex; align-items:stretch; gap:0; flex-wrap:wrap; margin:.1rem 0 .3rem; }
.pstep{ flex:1 1 0; min-width:130px; background:#fff; border:1px solid var(--line); border-radius:11px;
  padding:.6rem .75rem; box-shadow:var(--shadow-sm); }
.pstep .pn{ font-size:.86rem; font-weight:700; color:var(--ink); display:flex; align-items:center; gap:.4rem; }
.pstep .pi{ width:9px; height:9px; border-radius:50%;
  background:linear-gradient(135deg,var(--violet-2),var(--indigo)); display:inline-block; }
.pstep .pd{ font-size:.72rem; color:var(--ink-3); margin-top:.25rem; line-height:1.4; }
.parrow{ display:flex; align-items:center; color:#CFC8E4; font-size:1.1rem; padding:0 .25rem; }

/* generic note / state panels */
.note{ border:1px solid var(--line); border-radius:14px; padding:1.4rem 1.5rem; background:#fff; box-shadow:var(--shadow-sm); }
.note.center{ text-align:center; }
.note h3{ font-size:1rem; font-weight:700; color:var(--ink); margin:0 0 .35rem; }
.note p{ font-size:.86rem; color:var(--ink-2); margin:0; line-height:1.5; }
.note.err-panel{ border-color:var(--err-br); background:var(--err-bg); }
.note.err-panel h3{ color:var(--err-ink); }
.note code{ background:#F1EFF8; padding:.1rem .35rem; border-radius:5px; font-size:.8rem; color:var(--violet-3); }
.spinner{ width:30px; height:30px; margin:0 auto; border-radius:50%;
  border:3px solid #ECE6F8; border-top-color:var(--violet-2); animation:spin .9s linear infinite; }
@keyframes spin{ from{transform:rotate(0)} to{transform:rotate(360deg)} }

/* ───────────────────────── agentic trace ───────────────────────── */
.trace{ display:flex; flex-direction:column; gap:.5rem; padding:.8rem .95rem; background:var(--soft);
  border:1px solid var(--line); border-radius:12px; margin-bottom:.4rem; }
.trace .row{ display:flex; gap:.6rem; align-items:center; font-size:.84rem; color:var(--ink-3); }
.trace .row.done{ color:var(--ok-ink); } .trace .row.active{ color:var(--violet); font-weight:600; }
.trace .ic{ width:18px; text-align:center; }
.trace .note-r{ font-size:.72rem; color:var(--ink-3); margin-left:auto; font-weight:500; }
.trace .row.active .ic{ animation:spin 1.1s linear infinite; display:inline-block; }

/* ───────────────────────── chat: assistant card (left) ───────────────────────── */
[data-testid="stChatMessage"]{ background:#fff; border:1px solid var(--line); border-radius:16px;
  padding:1rem 1.2rem 1.2rem !important; box-shadow:var(--shadow-sm); margin-bottom:.4rem; }
/* clean branded avatar circle (we pass a :material/shield: icon, never an emoji) */
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarCustom"],
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"]{
  background:linear-gradient(135deg,var(--violet-2),var(--indigo)) !important; color:#fff !important; border:none; }
/* assistant answer body: comfortable reading rhythm */
[data-testid="stChatMessage"] p{ font-size:.95rem; line-height:1.6; }
/* Wide tables (e.g. 13-column comparisons) scroll horizontally INSIDE the card
   instead of overflowing the page and colliding with other components. */
[data-testid="stChatMessage"] table{ display:block; overflow-x:auto; white-space:nowrap; max-width:100%;
  border-collapse:collapse; margin:.6rem 0; font-size:.86rem; }
[data-testid="stChatMessage"] table::-webkit-scrollbar{ height:8px; }
[data-testid="stChatMessage"] table::-webkit-scrollbar-thumb{ background:#DAD4EC; border-radius:8px; }
[data-testid="stChatMessage"] th{ background:var(--soft); color:var(--ink); font-weight:700; text-align:left;
  padding:.5rem .7rem; border-bottom:1px solid var(--line); }
[data-testid="stChatMessage"] td{ padding:.5rem .7rem; border-bottom:1px solid var(--line-2); color:var(--ink-2); }
[data-testid="stChatMessage"] tr:last-child td{ border-bottom:none; }
[data-testid="stChatMessage"] td:first-child{ color:var(--ink); font-weight:600; }
/* footer chips never touch the card's bottom edge */
.ans-foot{ margin-bottom:.15rem; }
/* compact, minimal source-citation buttons (they render inside the chat message,
   so this scope never touches the suggestion cards on the overview) */
[data-testid="stChatMessage"] .stButton button{ font-size:.72rem !important; font-weight:600 !important;
  padding:.3rem .5rem !important; border-radius:9px !important; line-height:1.25 !important;
  min-height:unset !important; text-align:left; color:var(--ink-2); }
[data-testid="stChatMessage"] .stButton button:hover{ border-color:var(--violet-2); color:var(--violet); }
[data-testid="stChatMessage"] .stButton button p{ font-size:.72rem !important; }

/* ───────────────────────── chat: user bubble (right) ───────────────────────── */
.umsg{ display:flex; justify-content:flex-end; align-items:flex-start; gap:.55rem; margin:.2rem 0 .7rem; }
.umsg .ubub{ background:linear-gradient(135deg,var(--violet-2),var(--indigo)); color:#fff;
  padding:.6rem .95rem; border-radius:16px 16px 4px 16px; max-width:78%; font-size:.95rem; line-height:1.5;
  box-shadow:0 4px 12px rgba(91,33,182,.22); overflow-wrap:anywhere; }
.umsg .uav{ width:34px; height:34px; border-radius:10px; flex:0 0 34px; display:grid; place-items:center;
  background:#EDE9FE; color:var(--violet-3); margin-top:.05rem; }

/* ───────────────────────── chat input — force light, never dark ───────────────────────── */
/* the pinned bottom bar must read as the SAME canvas colour — no seam/shade */
[data-testid="stBottom"], [data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"]{ background:var(--bg) !important; border:none !important;
  box-shadow:none !important; }
[data-testid="stChatInput"]{ background:var(--card) !important; border:1px solid var(--line) !important;
  border-radius:14px !important; box-shadow:var(--shadow-sm); transition:border-color .15s, box-shadow .15s; }
[data-testid="stChatInput"]:focus-within{ border-color:var(--violet-2) !important; box-shadow:0 0 0 3px var(--ring); }
/* every inner baseweb wrapper transparent so the container white always wins */
[data-testid="stChatInput"] *{ background:transparent !important; }
[data-testid="stChatInput"] textarea, [data-testid="stChatInputTextArea"]{
  color:var(--ink) !important; -webkit-text-fill-color:var(--ink) !important; font-size:15px !important; }
[data-testid="stChatInput"] textarea::placeholder, [data-testid="stChatInputTextArea"]::placeholder{
  color:var(--ink-3) !important; opacity:1; }
[data-testid="stChatInput"] button{ color:var(--violet) !important; }
[data-testid="stChatInput"]:has(textarea:disabled){ background:#F1EFF8 !important; border-style:dashed !important; box-shadow:none; }
[data-testid="stChatInput"] textarea:disabled, [data-testid="stChatInputTextArea"]:disabled{
  color:var(--ink-3) !important; -webkit-text-fill-color:var(--ink-3) !important; }

/* ───────────────────────── answer meta + citations ───────────────────────── */
.cite-label{ font-size:.68rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
  color:var(--ink-3); margin:.7rem 0 .3rem; }
.ans-foot{ display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin-top:.8rem;
  padding-top:.7rem; border-top:1px dashed var(--line); }
.chip{ font-size:.68rem; font-weight:600; padding:.2rem .55rem; border-radius:999px;
  background:#F4F2FB; color:var(--ink-2); border:1px solid var(--line); }
.chip.conf-high{ background:var(--ok-bg); color:var(--ok-ink); border-color:var(--ok-br); }
.chip.conf-medium{ background:var(--warn-bg); color:var(--warn-ink); border-color:var(--warn-br); }
.chip.conf-low{ background:var(--err-bg); color:var(--err-ink); border-color:var(--err-br); }
.chip.intent{ background:#EDE9FE; color:var(--violet-3); border-color:#DDD6FE; }
.chip.intent.comparison{ background:#FEF3C7; color:#92400E; border-color:#FDE68A; }
.chip.q{ background:#fff; color:var(--ink-3); font-weight:500; max-width:420px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.insuf{ font-size:.84rem; color:var(--warn-ink); background:var(--warn-bg); border:1px solid var(--warn-br);
  border-radius:10px; padding:.6rem .8rem; margin-top:.55rem; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════ helpers
def html(markup: str) -> None:
    """Render raw HTML safely. `dedent` + `strip` guarantees the first line sits at
    column 0, so Markdown never mistakes indented markup for a code block."""
    st.markdown(textwrap.dedent(markup).strip(), unsafe_allow_html=True)


def _md(text: str) -> str:
    """Prepare answer markdown for display:
    1. Strip inline [n] / [n][m] citation markers — they're visual noise in the
       prose and tables; the Sources chips below carry the attribution.
    2. Escape '$' — Streamlit renders `$…$` as LaTeX math, which silently ate
       dollar amounts and bold markers ('$20,000 ... **' became italic math).
    3. Insert a blank line before a markdown table — without it Streamlit prints
       the raw pipes and a long dash run (the 'infinite ----') instead of a table."""
    # drop [5], [5][6]… but NOT a markdown link like [1](url) — the (?!\() guard
    t = re.sub(r"[ \t]*\[\d+\](?:\[\d+\])*(?!\()", "", text or "")
    t = t.replace("$", "\\$")
    t = re.sub(r"([^\n|])\n(\|[^\n]*\|)", r"\1\n\n\2", t)
    return t


def render_user_msg(text: str) -> None:
    """A right-aligned user bubble with a clean avatar — the ChatGPT/Claude vibe."""
    html(f'<div class="umsg"><div class="ubub">{escape(text)}</div>'
         f'<div class="uav">{USER_SVG}</div></div>')


def _ss(key: str, default: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = default


_ss("session_id", uuid.uuid4().hex[:10])
_ss("messages", [])
_ss("uploaded_signatures", set())
_ss("ingestion_lock", False)
_ss("pending_question", None)
_ss("active_citation", None)
_ss("_streaming_active", False)


# ════════════════════════════════════════════════════════════ HTTP
def _get(path: str, **kw) -> Any:
    return requests.get(f"{API}{path}", timeout=kw.pop("timeout", 6), **kw)


def _post(path: str, **kw) -> requests.Response:
    return requests.post(f"{API}{path}", timeout=kw.pop("timeout", 180), **kw)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_health() -> dict | None:
    try:
        r = _get("/health", timeout=3)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


@st.cache_data(ttl=2, show_spinner=False)
def fetch_documents() -> list[dict] | None:
    # Cached briefly + no spinner: a single rerun touches this from both the main
    # gate and the sidebar fragment, so caching collapses that to one call and
    # removes the per-rerun flicker. Mutations call fetch_documents.clear().
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


# ════════════════════════════════════════════════════════════ corpus cards
def _bar_pct(status: str) -> int:
    try:
        return int((STAGE_ORDER.index(status) + 1) / len(STAGE_ORDER) * 100)
    except ValueError:
        return 100


def document_card_html(doc: dict) -> str:
    """Return ONE card's markup. All cards are concatenated into a single
    injection so a poll repaints one element, not fifteen — no flicker."""
    status = doc.get("status", "uploaded")
    name = escape(doc.get("doc_name", "document"))
    doc_type = escape((doc.get("doc_type") or "").strip())
    pages, chunks = doc.get("pages") or 0, doc.get("chunks") or 0

    if status == "ready":
        accent, badge = "ready", '<span class="tag ok">Ready</span>'
        type_tag = f'<span class="tag">{doc_type}</span>' if doc_type else ""
        body = f'<div class="d-meta">{pages} pages · {chunks} searchable chunks</div>'
    elif status == "failed":
        accent, badge, type_tag = "failed", '<span class="tag err">Failed</span>', ""
        body = f'<div class="d-fail">{escape(doc.get("detail") or "Processing failed")}</div>'
    else:
        accent, badge, type_tag = "proc", '<span class="tag proc">Processing</span>', ""
        body = (f'<div class="bar active"><div style="width:{_bar_pct(status)}%"></div></div>'
                f'<div class="d-stage">{STAGE_LABEL.get(status, status)}…</div>')

    return (f'<div class="doc {accent}"><div class="doc-top">'
            f'<div class="doc-name" title="{name}">{name}</div>{type_tag}{badge}</div>{body}</div>')


def corpus_panel_body() -> None:
    """Render the live corpus as a single html injection. Decorated at call-time
    with `run_every` so it re-runs *itself* (fragment scope) on a timer while
    documents are processing, and stops the moment everything settles."""
    docs = fetch_documents()
    if docs is None:
        html('<div class="note err-panel"><h3>Backend not reachable</h3>'
             '<p>Start the API (<code>uvicorn src.api.main:app</code>) on port 8000.</p></div>')
        return
    if not docs:
        html('<div class="note center" style="padding:1.3rem .9rem;">'
             '<div style="font-size:1.6rem;">🗂️</div>'
             '<h3 style="margin-top:.5rem;font-size:.92rem;">Corpus is empty</h3>'
             '<p style="font-size:.8rem;">Drop files above, or load the demo corpus.</p></div>')
        return

    ready = sum(1 for d in docs if d["status"] == "ready")
    in_flight = [d for d in docs if d["status"] not in ("ready", "failed")]
    failed = sum(1 for d in docs if d["status"] == "failed")
    summary = f"{ready} ready"
    if in_flight:
        summary += f" · {len(in_flight)} processing"
    if failed:
        summary += f" · {failed} failed"

    # Processing first, so the live action sits at the top of the rail.
    order = {"uploaded": 0, "extracting": 0, "classifying": 0, "chunking": 0,
             "indexing": 0, "failed": 1, "ready": 2}
    ordered = sorted(docs, key=lambda d: order.get(d["status"], 0))
    cards = "".join(document_card_html(d) for d in ordered)
    html(f'<div class="corpus-head"><span class="ct">Corpus · {len(docs)}</span>'
         f'<span class="cs">{summary}</span></div>'
         f'<div class="corpus">{cards}</div>')

    # When everything has settled, do exactly ONE app rerun so the chat gate and
    # the polling interval recompute. Skip it while a chat answer is streaming
    # (awaiting_stream) so a doc settling mid-conversation can't interrupt the turn.
    if (not in_flight and st.session_state.get("_corpus_polling")
            and not st.session_state.get("_streaming_active")):
        st.session_state["_corpus_polling"] = False
        st.rerun()


# ════════════════════════════════════════════════════════════ ingestion
def auto_ingest(uploaded_files: list[Any] | None) -> bool:
    """POST newly-dropped files immediately (no Ingest button). Re-uploads of the
    same (name, size) are skipped so a re-render never double-posts."""
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
    # Content-based de-dupe: skip samples already in the corpus (ready or still
    # processing) so a second click — even after a page refresh — never creates
    # duplicates. Only genuinely-missing or previously-failed samples reload.
    existing = fetch_documents() or []
    present = {d["doc_name"] for d in existing if d.get("status") != "failed"}
    pending = [f for f in files if f.name not in present]
    if not pending:
        st.toast("Demo corpus is already loaded.", icon="📚")
        return False
    payload = [("files", (f.name, f.read_bytes())) for f in pending]
    try:
        r = _post("/documents", files=payload, timeout=90)
        if r.status_code == 202:
            st.toast(f"Loaded {len(r.json())} sample document(s)", icon="📚")
            return True
        st.error(r.json().get("detail", r.text))
    except requests.RequestException as exc:
        st.error(f"API unreachable: {exc}")
    return False


# ════════════════════════════════════════════════════════════ citation modal
@st.dialog("Source preview", width="large")
def citation_dialog(c: dict) -> None:
    # Compact header only — no quote block — so the page render gets the space.
    html(f'<div class="src-head">[{c["source_id"]}] {escape(str(c["doc_name"]))} '
         f'<span>· page {c["page"]}</span></div>')
    doc_id = c.get("doc_id")
    if not doc_id:
        st.caption("Source document id unavailable for this citation.")
        return

    # Fetch the original SERVER-SIDE and embed it inline. The browser may be on a
    # different host than the API (e.g. it sees the server's LAN IP, not its
    # localhost), so a raw <iframe src="http://localhost:8000/…"> resolves to the
    # *viewer's* machine and Chrome blocks it. Pulling the bytes here and inlining
    # them as a data-URI / st.image makes the preview work regardless of network.
    ext = Path(c["doc_name"]).suffix.lower()
    try:
        resp = requests.get(f"{API}/documents/{doc_id}/file", timeout=15)
        resp.raise_for_status()
        data = resp.content
    except requests.RequestException as exc:
        st.warning(f"Couldn't load the original document for preview ({exc}).")
        return

    if ext == ".pdf":
        # Render the cited page with PDF.js to a <canvas>. Chrome blocks PDFs via
        # data:/blob: in a sandboxed component iframe (the broken box you saw), but
        # PDF.js is pure JS + canvas, so it renders reliably. The library loads
        # from a CDN (the browser has internet); on failure we fall back to download.
        b64 = base64.b64encode(data).decode()
        page = int(c.get("page") or 1)
        components.html(
            """
<div id="pv" style="height:660px;overflow:auto;border:1px solid #ECE9F4;border-radius:10px;
     background:#F8F7FD;display:flex;justify-content:center;align-items:flex-start;padding:10px;"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script>
(function(){
  const box=document.getElementById("pv");
  const fail=m=>{box.innerHTML='<p style="color:#8B86A3;font:14px Inter,sans-serif;margin:auto">'+m+'</p>';};
  if(!window.pdfjsLib){ fail('Preview unavailable — use Download below.'); return; }
  pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  const raw=atob("%B64%"); const bytes=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++) bytes[i]=raw.charCodeAt(i);
  pdfjsLib.getDocument({data:bytes}).promise
    .then(pdf=>pdf.getPage(Math.min(%PAGE%, pdf.numPages)))
    .then(page=>{
      const vp=page.getViewport({scale:1.5});
      const cv=document.createElement("canvas");
      cv.width=vp.width; cv.height=vp.height;
      cv.style.maxWidth="100%"; cv.style.height="auto";
      cv.style.boxShadow="0 2px 12px rgba(16,24,40,.14)"; cv.style.borderRadius="6px";
      box.appendChild(cv);
      page.render({canvasContext:cv.getContext("2d"), viewport:vp});
    }).catch(()=>fail("Couldn't render this PDF — use Download below."));
})();
</script>
""".replace("%B64%", b64).replace("%PAGE%", str(page)),
            height=682,
        )
    elif ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        st.image(data, use_container_width=True)
    else:
        st.caption(f"{ext.upper()} preview not supported inline — use the download below.")
    st.download_button("Download original", data, file_name=c["doc_name"],
                       use_container_width=True)


# ════════════════════════════════════════════════════════════ chat rendering
# A fixed four-step reasoning timeline. All four render from the first frame
# (pending → active → done) so the step count never changes mid-turn, and each
# row carries a live note (rewritten query, passages found, evidence verdict).
TRACE_STAGES = [
    ("planning",   "Understanding the question"),
    ("retrieving", "Searching your documents"),
    ("grading",    "Verifying the evidence"),
    ("generating", "Composing a grounded answer"),
]


def render_trace_html(state: dict[str, str]) -> str:
    rows = []
    for key, label in TRACE_STAGES:
        s = state.get(key, "pending")
        ic, cls = ("✓", "done") if s == "done" else (("◐", "active") if s == "active" else ("○", ""))
        note = escape(state.get(f"{key}_note", ""))
        note_html = f'<span class="note-r">{note}</span>' if note else ""
        rows.append(f'<div class="row {cls}"><span class="ic">{ic}</span><span>{label}</span>{note_html}</div>')
    return f'<div class="trace">{"".join(rows)}</div>'


def _short_doc(name: str) -> str:
    """Compact a document name for a citation chip: drop the extension and the
    common 'policy-/claim-/medical-' prefix so the chips stay small."""
    base = re.sub(r"\.(pdf|docx|png|jpe?g|tiff?)$", "", name or "", flags=re.I)
    return re.sub(r"^(policy|claim|medical)[-_]", "", base, flags=re.I)


def render_citation_chips(citations: list[dict], msg_idx: int) -> None:
    if not citations:
        return
    html('<div class="cite-label">Sources</div>')
    cols = st.columns(min(len(citations), 6))   # denser grid = smaller, minimal chips
    for i, c in enumerate(citations):
        with cols[i % len(cols)]:
            if st.button(f"[{c['source_id']}] {_short_doc(c['doc_name'])} · p{c['page']}",
                         key=f"cite_{msg_idx}_{i}", use_container_width=True,
                         help=f"{c['doc_name']} · page {c['page']}"):
                st.session_state.active_citation = c
                citation_dialog(c)


def render_answer_footer(meta: dict, n_citations: int) -> None:
    conf = escape(meta.get("confidence") or "—")
    intent = escape(meta.get("intent", "simple"))
    html(f"""
    <div class="ans-foot">
        <span class="chip conf-{conf}">confidence: {conf}</span>
        <span class="chip intent {intent}">{intent}</span>
        <span class="chip">{n_citations} citation(s)</span>
    </div>
    """)


def render_answer(msg: dict, idx: int) -> None:
    st.markdown(_md(msg["answer_markdown"]))
    if msg.get("insufficient_context"):
        html('<div class="insuf">The uploaded documents don\'t contain enough information '
             'to fully answer this. Try adding the relevant policy or rephrasing.</div>')
    render_citation_chips(msg.get("citations", []), idx)
    if msg.get("meta"):
        render_answer_footer(msg["meta"], len(msg.get("citations", [])))


def render_history() -> None:
    for idx, m in enumerate(st.session_state.messages):
        if m["role"] == "user":
            render_user_msg(m["content"])
        else:
            with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
                render_answer(m, idx)


def run_chat_turn(question: str) -> None:
    """Stream the assistant turn for `question`. The user message has already been
    appended to st.session_state.messages and rendered by render_history() in the
    same pass, so this function only handles the assistant card."""
    st.session_state["_streaming_active"] = True
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        trace_ph = st.empty()
        answer_ph = st.empty()
        cite_ph = st.empty()
        foot_ph = st.empty()

        trace: dict[str, str] = {"planning": "active"}
        chitchat = False
        trace_ph.markdown(render_trace_html(trace), unsafe_allow_html=True)

        buffer, final = "", None
        try:
            for event, data in stream_chat(question):
                if event == "planned":
                    # Greetings/small-talk get a friendly reply with no retrieval —
                    # hide the reasoning trace entirely for those turns.
                    if data.get("intent") == "chitchat":
                        chitchat = True
                        trace_ph.empty()
                        continue
                    trace["planning"] = "done"
                    trace["planning_note"] = f"intent: {data.get('intent', '—')}"
                    trace["retrieving"] = "active"
                elif event == "grading":
                    trace["retrieving"] = "done"
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
                    continue  # accumulate only; render the finished markdown ONCE at the
                    # end so partial tables never flash as raw pipes/dashes mid-stream
                elif event == "done":
                    trace["generating"] = "done"
                    final = data
                elif event == "error":
                    answer_ph.error(f"Answer generation failed: {data.get('error', 'unknown')}")
                    return
                if not chitchat:
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
        answer_ph.markdown(_md(final_text))
        if msg["insufficient_context"]:
            html('<div class="insuf">The uploaded documents don\'t contain enough '
                 'information to fully answer this.</div>')
        with cite_ph.container():
            render_citation_chips(answer["citations"], idx)
        with foot_ph.container():
            render_answer_footer(msg["meta"], len(answer["citations"]))
    st.session_state["_streaming_active"] = False


# ════════════════════════════════════════════════════════════ main-area states
def render_capabilities() -> None:
    """The platform's capabilities as a prominent, structured strip on the overview
    (above the sample questions) — the headline 'what this does' for the product."""
    svg = {
        "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
        "doc": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/></svg>',
        "cite": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
        "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>',
    }
    html(f"""
    <div class="caps">
        <div class="cap"><div class="cap-ic">{svg['search']}</div>
            <div><b>Azure AI Search</b><span>Hybrid BM25 + vector retrieval</span></div></div>
        <div class="cap"><div class="cap-ic">{svg['doc']}</div>
            <div><b>Document Intelligence</b><span>Layout-aware extraction &amp; OCR</span></div></div>
        <div class="cap"><div class="cap-ic">{svg['cite']}</div>
            <div><b>Page-level citations</b><span>Every fact traced to its source</span></div></div>
        <div class="cap"><div class="cap-ic">{svg['shield']}</div>
            <div><b>Agentic grounding</b><span>Evidence checked before answering</span></div></div>
    </div>
    """)


def render_hero_cold() -> None:
    html("""
    <div class="hero">
        <span class="eyebrow">Grounded · cited · auditable</span>
        <h1>Ask your insurance documents, get cited answers</h1>
        <p>Upload policies, claim forms and medical reports, then ask in plain English —
        every answer is grounded <strong>only</strong> in your documents and traced to the exact page.</p>
    </div>
    """)


def render_howitworks() -> None:
    html('<div class="section-title">How it works</div>'
         '<div class="section-sub">Three stages — add documents on the left, and the answer side '
         'unlocks the moment the first file is ready.</div>')
    html("""
    <div class="pipe">
        <div class="pstep"><div class="pn"><span class="pi"></span>Ingest</div>
            <div class="pd">Azure Document Intelligence reads the layout of every PDF, scan and report.</div></div>
        <div class="parrow">›</div>
        <div class="pstep"><div class="pn"><span class="pi"></span>Index</div>
            <div class="pd">Content is classified, chunked by structure and embedded into a hybrid search index.</div></div>
        <div class="parrow">›</div>
        <div class="pstep"><div class="pn"><span class="pi"></span>Interrogate</div>
            <div class="pd">Ask in natural language — every answer is cited to the exact source page for audit.</div></div>
    </div>
    """)


def render_indexing_wait(in_flight: int) -> None:
    plural = "s" if in_flight != 1 else ""
    html(f"""
    <div class="note center" style="padding:2.4rem 1.5rem;">
        <div class="spinner"></div>
        <h3 style="margin-top:.9rem;">Building your knowledge base</h3>
        <p>Extracting, classifying and embedding {in_flight} document{plural}. Questions unlock
        automatically the moment the first document is ready — live progress is on the left.</p>
    </div>
    """)


def render_ready_welcome() -> None:
    html("""
    <div class="hero">
        <span class="eyebrow">Knowledge base ready</span>
        <h1>Ask anything across your corpus</h1>
        <p>Answers are grounded only in your documents and cited to the exact source page — verifiable in one click.</p>
    </div>
    """)


def render_suggestions() -> None:
    html('<div class="microlabel">Start with a question</div>')
    cols = st.columns(2, gap="medium")
    for i, (icon, title, question) in enumerate(SUGGESTED_QUESTIONS):
        with cols[i % 2]:
            if st.button(f"**{title}**\n\n{question}", key=f"sugg_{i}",
                         icon=icon, use_container_width=True):
                st.session_state.pending_question = question
                # No explicit st.rerun(): Streamlit reruns naturally on button click.
                # Calling st.rerun() inside `with overview_slot.container()` would
                # abort the context manager mid-execution, causing stale content to
                # persist during the next render.


# ════════════════════════════════════════════════════════════ data + gate
health = fetch_health()
docs_now = fetch_documents()
backend_ok = docs_now is not None
ready_count = sum(1 for d in (docs_now or []) if d["status"] == "ready")
in_flight_count = sum(1 for d in (docs_now or []) if d["status"] not in ("ready", "failed"))
st.session_state["_corpus_polling"] = in_flight_count > 0


# ════════════════════════════════════════════════════════════ sidebar (shell)
with st.sidebar:
    html(f'<div class="brand"><div class="brand-logo">{SHIELD_SVG}</div>'
         '<div><div class="brand-name">Insurance Doc Intelligence</div>'
         '<div class="brand-sub">Grounded RAG</div></div></div>')

    html('<div class="microlabel">Documents</div>')
    uploaded = st.file_uploader(
        "Drop PDF / DOCX / JPG / PNG / TIFF",
        type=["pdf", "docx", "jpg", "jpeg", "png", "tif", "tiff"],
        accept_multiple_files=True, label_visibility="collapsed", key="uploader",
    )
    if auto_ingest(uploaded):
        fetch_documents.clear()
        st.session_state["_corpus_polling"] = True
        st.rerun()
    if st.button("Load demo corpus", icon=":material/library_books:",
                 use_container_width=True, key="demo_side"):
        # De-dupe is now content-based inside load_demo_corpus(): it skips samples
        # already present and toasts "already loaded" when there's nothing new.
        if load_demo_corpus():
            fetch_documents.clear()
            st.session_state["_corpus_polling"] = True
            st.rerun()

    # Live corpus — polls only while ingestion is in flight; otherwise renders once.
    interval = 2.0 if in_flight_count else None
    st.fragment(run_every=interval)(corpus_panel_body)()

    # System status card.
    if health is None:
        html('<div class="status-card">'
             '<div class="microlabel" style="margin:0 0 .45rem;">System status</div>'
             '<div class="status-row"><span class="dot dot-off"></span>Backend <b>offline</b></div>'
             '<div class="status-row mono" style="color:#9A96AE;">'
             f'session {st.session_state.session_id}</div></div>')
    else:
        services = health.get("services", {})
        n_ok = sum(1 for v in services.values() if v)
        n_all = len(services) or 1
        svc_dot = "dot-on" if n_ok == n_all else ("dot-warn" if n_ok else "dot-off")
        provider = escape((health.get("provider") or "").title()) or "LLM"
        model = escape(health.get("chat_model", "")) or "—"
        html(f'<div class="status-card">'
             f'<div class="microlabel" style="margin:0 0 .45rem;">System status</div>'
             f'<div class="status-row"><span class="dot dot-on"></span>{provider} <b>{model}</b></div>'
             f'<div class="status-row"><span class="dot {svc_dot}"></span>Azure services <b>{n_ok}/{n_all}</b></div>'
             f'<div class="status-row mono" style="color:#9A96AE;">session {st.session_state.session_id}</div>'
             f'</div>')


# ════════════════════════════════════════════════════════════ main (conversation)
# Capture chat input FIRST (pinned to bottom by Streamlit regardless of call order).
chat_ready = backend_ok and ready_count > 0
placeholder = ("Ask about your documents…" if chat_ready
               else "Add and index at least one document to start asking…")
typed = st.chat_input(placeholder, disabled=not chat_ready)
if typed:
    st.session_state.pending_question = typed

pending = st.session_state.pending_question
has_thread = bool(st.session_state.messages or pending)

# ── STABLE LAYOUT ANCHOR ─────────────────────────────────────────────────────
# header_area is rendered on EVERY run (even empty), so it's always exactly one
# element. That keeps `overview_slot` (declared right after it) at a FIXED delta
# position across runs — which is what lets overview_slot.empty() actually clear
# the suggestion cards. Previously the New-chat bar was conditional, so the slot
# shifted position between the overview run and the chat run and never cleared,
# leaving the cards lingering behind the streaming answer (and over the button).
header_area = st.container()
with header_area:
    if has_thread:
        bar = st.columns([1, 0.22], vertical_alignment="center")
        with bar[0]:
            html('<div class="microlabel" style="margin:.1rem 0 0;">Conversation</div>')
        with bar[1]:
            if st.button("🗨️ New chat", key="new_chat", use_container_width=True,
                         help="Start a new conversation"):
                _old_sid = st.session_state.session_id
                st.session_state.session_id = uuid.uuid4().hex[:10]
                st.session_state.messages = []
                st.session_state.active_citation = None
                st.session_state.pending_question = None
                st.session_state["_streaming_active"] = False
                try:
                    requests.delete(f"{API}/sessions/{_old_sid}", timeout=2)
                except Exception:
                    pass
                st.rerun()

# The overview lives in ONE placeholder at this fixed position. On a conversation
# turn we EMPTY it first — an immediate clear delta — so the cards are gone before
# the (long) streaming run starts, instead of lingering until the run ends.
overview_slot = st.empty()

if not backend_ok:
    with overview_slot.container():
        html('<div class="note err-panel"><h3>Backend not reachable</h3>'
             '<p>Start the API with <code>uvicorn src.api.main:app</code> and confirm it is '
             'listening on <code>http://localhost:8000</code>, then reload this page.</p></div>')
elif has_thread:
    overview_slot.empty()            # clear the overview immediately (stable position)
    question_to_stream = None
    if pending:
        st.session_state.messages.append({"role": "user", "content": pending})
        st.session_state.pending_question = None
        question_to_stream = pending
    render_history()
    if question_to_stream:
        run_chat_turn(question_to_stream)
elif ready_count == 0 and in_flight_count == 0:
    with overview_slot.container():
        render_hero_cold()
        render_capabilities()
        render_howitworks()
elif ready_count == 0 and in_flight_count > 0:
    with overview_slot.container():
        render_indexing_wait(in_flight_count)
else:
    with overview_slot.container():
        render_ready_welcome()
        render_capabilities()
        render_suggestions()
