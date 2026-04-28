"""Tests for layout extraction and boundary detection."""
from __future__ import annotations

import fitz

from smart_pdf_splitter.boundary_detection import detect_boundaries
from smart_pdf_splitter.config import SplitConfig
from smart_pdf_splitter.extractor import extract_layout
from smart_pdf_splitter.models import BlockKind, BoundaryReason


def test_extract_layout_finds_blocks_and_headings(simple_tall_pdf):
    with fitz.open(simple_tall_pdf) as doc:
        layout = extract_layout(doc)

    assert layout.page_width > 0 and layout.page_height > 1000  # tall
    assert len(layout.blocks) > 5
    assert layout.median_line_height > 0

    cfg = SplitConfig()
    candidates = detect_boundaries(layout, cfg)

    headings = [b for b in layout.blocks if b.kind == BlockKind.HEADING]
    assert len(headings) >= 4, f"expected to find headings, got {len(headings)}"

    reasons = {c.reason for c in candidates}
    assert BoundaryReason.PAGE_TOP in reasons
    assert BoundaryReason.PAGE_BOTTOM in reasons
    assert BoundaryReason.BEFORE_HEADING in reasons


def test_candidates_are_sorted_and_unique(simple_tall_pdf):
    with fitz.open(simple_tall_pdf) as doc:
        layout = extract_layout(doc)
    candidates = detect_boundaries(layout, SplitConfig())
    ys = [c.y for c in candidates]
    assert ys == sorted(ys)
    # No two candidates within 1pt.
    for a, b in zip(ys, ys[1:]):
        assert b - a >= 0.99
