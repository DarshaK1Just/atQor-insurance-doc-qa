"""Golden tests for span→page citation mapping — no Azure calls."""
from src.indexing.page_mapper import PageMapper
from src.ingestion.extractor import PageSpan

SPANS = [
    PageSpan(page_number=1, start=0, end=100),
    PageSpan(page_number=2, start=102, end=250),
    PageSpan(page_number=3, start=252, end=400),
]


def test_single_page_chunk():
    assert PageMapper(SPANS).page_range(10, 90) == (1, 1)


def test_chunk_spanning_pages():
    assert PageMapper(SPANS).page_range(80, 200) == (1, 2)


def test_offset_in_join_gap_falls_back_to_previous_page():
    assert PageMapper(SPANS).page_range(101, 150) == (1, 2)


def test_windowed_merge_page_offsets():
    # Simulates the F0 two-page-window merge: window 2 pages are 3 and 4.
    spans = [PageSpan(1, 0, 50), PageSpan(2, 50, 100),
             PageSpan(3, 102, 150), PageSpan(4, 150, 200)]
    assert PageMapper(spans).page_range(120, 190) == (3, 4)


def test_empty_spans_safe():
    assert PageMapper([]).page_range(0, 10) == (1, 1)
