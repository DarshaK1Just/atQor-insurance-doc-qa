"""Streamlit Cloud entry point — Insurance Doc Intelligence.

Three jobs, in order:
  1. Sync Streamlit Cloud secrets → os.environ so pydantic Settings picks them up.
  2. Boot the FastAPI backend on 127.0.0.1:8001 in a daemon thread.
  3. exec() the Streamlit frontend (frontend/app.py) in-process.

Local single-process use: `streamlit run streamlit_app.py`
Local split-process use: uvicorn on port 8001 in one terminal, Streamlit in another.
Streamlit Cloud: connect this repo, set main file to streamlit_app.py,
paste secrets from use-case-1-document-qa/.streamlit/secrets.toml.example
into the Secrets panel.
"""
import os
import sys
import time
import threading
from pathlib import Path

import streamlit as st

# ── 1. Resolve project root and make src.* importable ────────────────────────
_HERE = Path(__file__).resolve().parent / "use-case-1-document-qa"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# Relative paths in config (data_dir = "./data") must resolve to here, not to
# wherever Streamlit Cloud's CWD happens to be.
os.chdir(_HERE)

# ── 2. Sync Streamlit Cloud secrets → os.environ ─────────────────────────────
# On Streamlit Cloud, secrets are in st.secrets (set via the dashboard).
# On local dev, st.secrets is empty and pydantic-settings loads .env directly.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass  # no secrets configured — local dev mode, .env file handles credentials

# ── 3. Start the FastAPI backend exactly once per Streamlit process ───────────
# @st.cache_resource persists across sessions (process-level singleton), so
# uvicorn only starts once even when many users have the app open.
@st.cache_resource(show_spinner="Starting document backend…")
def _start_backend() -> str:
    """Spin up uvicorn in a daemon thread and return the base URL."""
    import uvicorn
    import logging

    port = 8000  # Fixed port that frontend expects

    def _serve() -> None:
        try:
            # Configure uvicorn logger
            uvicorn_logger = logging.getLogger("uvicorn")
            uvicorn_logger.setLevel(logging.INFO)
            
            uvicorn.run(
                "src.api.main:app",
                host="0.0.0.0",  # Listen on all interfaces for cloud environments
                port=port,
                log_level="info",
                access_log=True,
            )
        except Exception as e:
            import streamlit as st
            st.error(f"Backend startup failed: {e}")
            raise

    threading.Thread(target=_serve, name="fastapi-backend", daemon=True).start()
    # Give uvicorn time to bind the port on cloud environments
    time.sleep(10)
    return f"http://127.0.0.1:{port}"


_api_url = _start_backend()

# Tell the frontend where the API lives (it reads API_BASE_URL at exec time).
os.environ["API_BASE_URL"] = _api_url  # Force override, don't use setdefault

# ── 4. Run the Streamlit frontend in-process ──────────────────────────────────
# Override __file__ in the exec namespace so the SAMPLE_DIR path calculation
# inside frontend/app.py (Path(__file__).parent.parent / "sample-documents")
# resolves to use-case-1-document-qa/sample-documents/ as expected.
_frontend = _HERE / "frontend" / "app.py"
_g = globals().copy()
_g["__file__"] = str(_frontend)
exec(_frontend.read_text(encoding="utf-8"), _g)  # noqa: S102
