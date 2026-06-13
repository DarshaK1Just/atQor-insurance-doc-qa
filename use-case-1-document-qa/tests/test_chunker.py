"""Golden tests for the hybrid structural chunker — no Azure calls."""
from src.indexing.chunker import chunk_markdown

SAMPLE = """# Gold Shield Policy

## Section 2: Coverage Schedule

Intro paragraph about coverage.

<table><tr><th>Benefit</th><th>Limit</th></tr><tr><td>Outpatient</td><td>$20,000</td></tr></table>

<!-- PageBreak -->

## Section 3: Deductibles

The annual deductible is $500 per member.

After the deductible, the plan pays 80% of eligible expenses.
"""


def test_chunks_follow_headings():
    chunks = chunk_markdown(SAMPLE)
    paths = {c.heading_path for c in chunks}
    assert any("Section 2" in p for p in paths)
    assert any("Section 3" in p for p in paths)


def test_breadcrumb_prepended():
    chunks = chunk_markdown(SAMPLE)
    section3 = next(c for c in chunks if "Section 3" in c.heading_path)
    assert section3.text.startswith("[Gold Shield Policy > Section 3")
    assert "$500" in section3.text


def test_table_kept_whole():
    chunks = chunk_markdown(SAMPLE)
    table_chunks = [c for c in chunks if "<table>" in c.text]
    assert table_chunks, "table content must be chunked"
    assert all("</table>" in c.text for c in table_chunks), "tables must never be split"


def test_page_comments_stripped():
    chunks = chunk_markdown(SAMPLE)
    assert all("PageBreak" not in c.text for c in chunks)


def test_offsets_point_into_original():
    chunks = chunk_markdown(SAMPLE)
    for chunk in chunks:
        assert 0 <= chunk.start_offset < chunk.end_offset <= len(SAMPLE)
