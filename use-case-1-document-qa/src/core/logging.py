"""Structured JSON logging with correlation IDs (assignment §6: trace the full
pipeline from upload → extraction → chunking → indexing → retrieval → answer)."""
import logging
import sys
import uuid

import structlog


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(component: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(component=component)


def new_correlation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
