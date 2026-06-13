"""Hybrid structural chunker (assignment §4.2 — strategy justified in README).

Strategy: structure-first, size-capped.
1. Split on the layout model's detected Markdown headings (H1–H3) — chunk
   boundaries follow the document's own semantics, detected by the AI model.
2. Size-cap oversized sections at CHUNK_MAX_TOKENS with CHUNK_OVERLAP_TOKENS
   of overlap (Microsoft's documented starting point: 512 tokens / ~15-25%).
3. Tables are atomic: never split mid-table; an oversized table stays whole.
4. Every chunk gets its heading breadcrumb prepended ("Policy > Section 4 >
   Outpatient Benefits") so mid-document chunks keep their context.

Character offsets into the original markdown are tracked through every split so
each chunk can be mapped to exact page numbers via DI's pages[].spans."""
import re
from dataclasses import dataclass
from functools import lru_cache

from src.core.config import get_settings


@lru_cache(maxsize=1)
def _encoder():
    """Load the BPE encoder lazily, once. Importing tiktoken and loading the
    cl100k_base table costs ~1s; doing it on first chunk (not module import)
    keeps backend reloads fast. Returns None when tiktoken is unavailable."""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - offline fallback
        return None


def _tokens(text: str) -> int:
    enc = _encoder()
    return len(enc.encode(text)) if enc is not None else max(1, len(text) // 4)

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_HTML_TABLE_RE = re.compile(r"<table>.*?</table>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Chunk:
    text: str           # breadcrumb + body (what gets embedded and indexed)
    heading_path: str
    start_offset: int   # char offset of body start in the ORIGINAL markdown
    end_offset: int


@dataclass
class _Part:
    text: str
    start: int
    end: int
    atomic: bool  # tables are never split


def _sections(content: str) -> list[tuple[str, int, int]]:
    """Split markdown into (heading_path, body_start, body_end) on H1–H3."""
    sections: list[tuple[str, int, int]] = []
    stack: dict[int, str] = {}
    body_start = 0
    offset = 0
    for line in content.splitlines(keepends=True):
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match:
            if offset > body_start:
                sections.append((_breadcrumb(stack), body_start, offset))
            level = len(match.group(1))
            stack[level] = match.group(2).strip()
            for deeper in list(stack):
                if deeper > level:
                    del stack[deeper]
            body_start = offset + len(line)
        offset += len(line)
    if offset > body_start:
        sections.append((_breadcrumb(stack), body_start, offset))
    return sections


def _breadcrumb(stack: dict[int, str]) -> str:
    return " > ".join(stack[level] for level in sorted(stack) if stack.get(level))


def _split_parts(content: str, start: int, end: int) -> list[_Part]:
    """Segment a section body into atomic tables and splittable paragraphs."""
    body = content[start:end]
    parts: list[_Part] = []
    cursor = 0
    for table in _HTML_TABLE_RE.finditer(body):
        if table.start() > cursor:
            parts.extend(_paragraphs(body[cursor:table.start()], start + cursor))
        parts.append(_Part(body[table.start():table.end()], start + table.start(),
                           start + table.end(), atomic=True))
        cursor = table.end()
    if cursor < len(body):
        parts.extend(_paragraphs(body[cursor:], start + cursor))
    return [p for p in parts if p.text.strip()]


def _paragraphs(text: str, base: int) -> list[_Part]:
    parts: list[_Part] = []
    cursor = 0
    for para in re.split(r"(\n\s*\n)", text):
        if para.strip() and not re.fullmatch(r"\n\s*\n", para):
            parts.append(_Part(para, base + cursor, base + cursor + len(para), atomic=False))
        cursor += len(para)
    return parts


def _clean(text: str) -> str:
    """Strip DI page-header/footer/number comments — noise for embeddings."""
    return _COMMENT_RE.sub("", text).strip()


def chunk_markdown(content: str) -> list[Chunk]:
    settings = get_settings()
    max_tokens, overlap_tokens = settings.chunk_max_tokens, settings.chunk_overlap_tokens
    chunks: list[Chunk] = []

    for heading_path, body_start, body_end in _sections(content):
        parts = _split_parts(content, body_start, body_end)
        if not parts:
            continue
        breadcrumb = f"[{heading_path}]\n\n" if heading_path else ""
        current: list[_Part] = []
        current_tokens = _tokens(breadcrumb)

        def flush() -> None:
            nonlocal current, current_tokens
            if not current:
                return
            body = _clean("\n\n".join(p.text.strip() for p in current))
            if body:
                chunks.append(Chunk(
                    text=breadcrumb + body,
                    heading_path=heading_path,
                    start_offset=current[0].start,
                    end_offset=current[-1].end,
                ))
            # overlap: carry trailing non-atomic parts into the next chunk
            tail: list[_Part] = []
            tail_tokens = 0
            for part in reversed(current):
                if part.atomic or tail_tokens + _tokens(part.text) > overlap_tokens:
                    break
                tail.insert(0, part)
                tail_tokens += _tokens(part.text)
            current = list(tail)
            current_tokens = _tokens(breadcrumb) + tail_tokens

        for part in parts:
            part_tokens = _tokens(part.text)
            if part.atomic and part_tokens > max_tokens:
                flush()
                current, current_tokens = [part], _tokens(breadcrumb) + part_tokens
                flush()
                current, current_tokens = [], _tokens(breadcrumb)
                continue
            if current and current_tokens + part_tokens > max_tokens:
                flush()
                if current_tokens + part_tokens > max_tokens:  # overlap tail still too full
                    current, current_tokens = [], _tokens(breadcrumb)
            current.append(part)
            current_tokens += part_tokens
        flush()

    return chunks
