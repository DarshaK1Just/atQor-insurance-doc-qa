"""Chunk → page mapping via DI `pages[].spans` character offsets.

DI returns one continuous markdown string; each page's spans give its
{offset, length} window into that same string. A chunk's page range is the set
of pages whose spans overlap the chunk's [start_offset, end_offset)."""
from bisect import bisect_right

from src.ingestion.extractor import PageSpan


class PageMapper:
    def __init__(self, page_spans: list[PageSpan]) -> None:
        self._spans = sorted(page_spans, key=lambda s: s.start)
        self._starts = [s.start for s in self._spans]

    def page_range(self, start_offset: int, end_offset: int) -> tuple[int, int]:
        """Return (page_start, page_end) for a character range. Falls back to the
        nearest preceding page when an offset lands between spans (whitespace
        joins)."""
        if not self._spans:
            return (1, 1)
        first = self._page_for(start_offset)
        last = self._page_for(max(start_offset, end_offset - 1))
        return (min(first, last), max(first, last))

    def _page_for(self, offset: int) -> int:
        idx = bisect_right(self._starts, offset) - 1
        if idx < 0:
            return self._spans[0].page_number
        return self._spans[idx].page_number
