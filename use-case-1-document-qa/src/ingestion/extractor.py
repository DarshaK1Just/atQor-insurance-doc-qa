"""Layout-aware extraction via Azure AI Document Intelligence `prebuilt-layout`
(API 2024-11-30) with Markdown output.

Free-tier (F0) design note: F0 silently analyzes ONLY the first 2 pages of any
request. For multi-page PDFs we therefore split into N-page windows (pypdf —
pure plumbing, no intelligence in Python), analyze each window separately, and
merge results with correct page-number offsets. On a paid S0 resource set
DOCINTEL_PAGE_WINDOW=0 to send documents whole.

Citation lineage: DI's `pages[].spans` give each page's {offset, length} window
into the markdown `content` string. We carry these through the merge (shifting
offsets and page numbers) so every chunk can later be mapped to exact pages."""
import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from azure.ai.documentintelligence.models import DocumentAnalysisFeature
from azure.core.exceptions import HttpResponseError

from src.core.azure_clients import docintel_client
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger("extractor")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass(frozen=True)
class PageSpan:
    """A page's character window into the merged markdown content."""
    page_number: int
    start: int
    end: int


@dataclass
class ExtractionResult:
    content: str
    page_spans: list[PageSpan]
    page_count: int
    synthetic_pages: bool  # True for DOCX (3,000 chars = 1 "page"; cite by section)


class ExtractionError(Exception):
    pass


def _is_throttle(exc: BaseException) -> bool:
    return isinstance(exc, HttpResponseError) and exc.status_code == 429


_OCR_FORMATS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@retry(retry=retry_if_exception(_is_throttle), wait=wait_exponential(min=2, max=30),
       stop=stop_after_attempt(5), reraise=True)
def _analyze(data: bytes, file_ext: str = ".pdf") -> object:
    """One DI layout call (markdown). Retries with backoff on 429 throttling.

    OCR_HIGH_RESOLUTION add-on is enabled for OCR-able formats (PDF + image)
    — it noticeably improves digit fidelity on thin-stroke tables. The feature
    is rejected by DI for Office formats (.docx etc.), which use direct text
    extraction, so we omit it there."""
    features = ([DocumentAnalysisFeature.OCR_HIGH_RESOLUTION]
                if file_ext.lower() in _OCR_FORMATS else None)
    kwargs = dict(
        body=data,
        content_type="application/octet-stream",
        output_content_format="markdown",
    )
    if features:
        kwargs["features"] = features
    poller = docintel_client().begin_analyze_document("prebuilt-layout", **kwargs)
    return poller.result()


def _result_to_extraction(result: object, page_offset: int, char_shift: int) -> tuple[str, list[PageSpan]]:
    spans: list[PageSpan] = []
    for page in result.pages:
        for span in page.spans:
            spans.append(PageSpan(
                page_number=page.page_number + page_offset,
                start=span.offset + char_shift,
                end=span.offset + span.length + char_shift,
            ))
    return result.content, spans


def _pdf_windows(data: bytes, window: int) -> list[bytes]:
    reader = PdfReader(io.BytesIO(data))
    windows: list[bytes] = []
    for start in range(0, len(reader.pages), window):
        writer = PdfWriter()
        for page in reader.pages[start:start + window]:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        windows.append(buf.getvalue())
    return windows


def extract_document(path: Path, correlation_id: str) -> ExtractionResult:
    """Extract a document to markdown + page spans, defeating the F0 trap."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(f"Unsupported file format '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    data = path.read_bytes()
    settings = get_settings()
    window = settings.docintel_page_window

    if ext == ".pdf" and window > 0:
        expected_pages = len(PdfReader(io.BytesIO(data)).pages)
        if expected_pages > window:
            return _extract_windowed(data, window, expected_pages, correlation_id, ext)

    result = _analyze(data, ext)
    content, spans = _result_to_extraction(result, page_offset=0, char_shift=0)
    page_count = len(result.pages)

    # F0 trap detector: truncation must never pass silently.
    if ext == ".pdf":
        expected = len(PdfReader(io.BytesIO(data)).pages)
        if page_count < expected:
            raise ExtractionError(
                f"Document Intelligence returned {page_count}/{expected} pages — "
                f"likely the F0 free-tier 2-page truncation. Set DOCINTEL_PAGE_WINDOW=2 "
                f"(splitter) or use an S0 resource."
            )

    log.info("extraction_complete", correlation_id=correlation_id, file=path.name,
             pages=page_count, chars=len(content), windowed=False)
    return ExtractionResult(content=content, page_spans=spans, page_count=page_count,
                            synthetic_pages=(ext == ".docx"))


def _extract_windowed(data: bytes, window: int, expected_pages: int,
                      correlation_id: str, file_ext: str = ".pdf") -> ExtractionResult:
    """Parallel-fanout windowed extraction.

    On F0, each 2-page window is its own DI call. Sequentially that's
    O(pages/2) round trips — for a 10-page policy, 5 calls × ~4s = 20s. Running
    the windows concurrently against the DI endpoint (rate-limit permitting)
    collapses this to roughly the time of the slowest window. azure-core
    clients are thread-safe; we just need to merge by window index so page
    numbers and character offsets stay correct."""
    from concurrent.futures import ThreadPoolExecutor

    windows = _pdf_windows(data, window)
    with ThreadPoolExecutor(max_workers=min(8, len(windows))) as pool:
        results = list(pool.map(lambda w: _analyze(w, file_ext), windows))

    contents: list[str] = []
    spans: list[PageSpan] = []
    char_shift = 0
    pages_seen = 0
    for i, result in enumerate(results):
        content, window_spans = _result_to_extraction(result, page_offset=i * window, char_shift=char_shift)
        contents.append(content)
        spans.extend(window_spans)
        pages_seen += len(result.pages)
        char_shift += len(content) + 2  # joined with "\n\n"
        log.info("extraction_window", correlation_id=correlation_id, window=i + 1,
                 pages_in_window=len(result.pages))

    if pages_seen != expected_pages:
        raise ExtractionError(
            f"Windowed extraction returned {pages_seen}/{expected_pages} pages — aborting "
            f"to avoid silently incomplete answers."
        )
    merged = "\n\n".join(contents)
    log.info("extraction_complete", correlation_id=correlation_id, pages=pages_seen,
             chars=len(merged), windowed=True)
    return ExtractionResult(content=merged, page_spans=spans, page_count=pages_seen,
                            synthetic_pages=False)
