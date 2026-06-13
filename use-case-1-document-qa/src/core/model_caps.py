"""Runtime capability detection for the configured chat deployment.

Azure OpenAI gpt-4o models support **Structured Outputs** (`response_format=`
a Pydantic schema); free serverless models such as Kimi-k2.6 do not and reject
the request. Without this module, every planner + answerer call would *first*
attempt Structured Outputs, eat a failed network round-trip, and only then fall
back to JSON mode — two wasted Azure calls on every single chat turn.

We probe once and cache the answer process-wide. Behaviour is controlled by the
`AZURE_OPENAI_STRUCTURED_OUTPUTS` setting:

* ``auto`` (default) — attempt once; the first rejection disables it forever.
* ``on``  — force the Structured-Outputs path (use on gpt-4o / gpt-4o-mini).
* ``off`` — never attempt it (Kimi & other serverless models) → straight to
  JSON mode, zero wasted calls from turn one.
"""
import threading

from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("model_caps")

_lock = threading.Lock()
_mode: str | None = None
_auto_supported: bool | None = None  # auto-mode probe result: None=unknown, then True/False


def _mode_value() -> str:
    global _mode
    if _mode is None:
        value = (get_settings().structured_outputs or "auto").strip().lower()
        _mode = value if value in ("auto", "on", "off") else "auto"
    return _mode


def supports_structured_outputs() -> bool:
    """Whether the next call should ATTEMPT Structured Outputs.

    In ``auto`` mode this is True until the first failure flips it off."""
    mode = _mode_value()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return _auto_supported is not False  # unknown or known-good → attempt


def mark_unsupported() -> None:
    """Record that the deployment rejected Structured Outputs (auto mode only)."""
    global _auto_supported
    if _mode_value() != "auto":
        return  # respect an explicit on/off override
    with _lock:
        if _auto_supported is not False:
            _auto_supported = False
            log.info("structured_outputs_auto_disabled",
                     hint="deployment rejected response_format=schema; using JSON mode for the rest of this run")
