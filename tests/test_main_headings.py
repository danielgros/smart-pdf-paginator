"""Regression tests for the main-heading rule using the real article PDF.

Rules verified:

* Every main section heading (font size >= median * main_heading_size_ratio)
  appears at the very top of an output page.
* Subsection headings flow with the body text and may appear anywhere on a
  page.
* No cut lands strictly inside an atomic block (image / table / figure).
"""
from __future__ import annotations

import os

import fitz
import pytest

from smart_pdf_splitter.boundary_detection import detect_boundaries
from smart_pdf_splitter.config import SplitConfig
from smart_pdf_splitter.extractor import extract_layout
from smart_pdf_splitter.models import BlockKind
from smart_pdf_splitter.planner import plan_splits


ARTICLE_PDF = os.path.join(
    os.path.dirname(__file__),
    "..",
    "Article - Best Practices for Claude Code - Claude Code Docs.pdf",
)


@pytest.fixture(scope="module")
def article_layout_and_plan():
    if not os.path.exists(ARTICLE_PDF):
        pytest.skip(f"Article PDF not present at {ARTICLE_PDF}")
    cfg = SplitConfig()
    with fitz.open(ARTICLE_PDF) as doc:
        layout = extract_layout(doc, cfg)
        cands = detect_boundaries(layout, cfg)
        plan = plan_splits(layout, cands, cfg)
    return layout, plan


def test_article_main_headings_classified(article_layout_and_plan):
    layout, _ = article_layout_and_plan
    main_texts = [
        b.lines[0].text.strip()
        for b in layout.blocks
        if b.kind == BlockKind.MAIN_HEADING and b.lines
    ]
    # Sanity: must include the user-cited examples.
    expected = {
        "Give Claude a way to verify its work",
        "Configure your environment",
    }
    assert expected.issubset(set(main_texts)), (
        f"missing main headings; got {main_texts}"
    )

    # And the user-cited subsection examples must NOT be MAIN_HEADING.
    sub_texts = {
        b.lines[0].text.strip()
        for b in layout.blocks
        if b.kind == BlockKind.HEADING and b.lines
    }
    assert "Provide rich content" in sub_texts
    assert "Set up hooks" in sub_texts
    assert "Provide rich content" not in main_texts
    assert "Set up hooks" not in main_texts


def test_main_headings_start_a_new_page(article_layout_and_plan):
    """Each main heading must sit at the top of some output page (i.e. its y0
    is within ~one line of a slice's y0). Headings that fall within the very
    first ~50pt of content (e.g. the document title) are exempt — they are
    already at the top of the document."""
    layout, plan = article_layout_and_plan
    page_starts = [sl.y0 for sl in plan.slices]
    tol = max(layout.median_line_height * 1.5, 25.0)
    skip_top = 50.0
    main_blocks = [b for b in layout.blocks if b.kind == BlockKind.MAIN_HEADING]
    for h in main_blocks:
        if h.y0 - page_starts[0] < skip_top:
            continue  # essentially at the top of the document
        nearest = min(page_starts, key=lambda y: abs(y - h.y0))
        assert abs(nearest - h.y0) <= tol, (
            f"Main heading {h.lines[0].text!r} at y={h.y0:.1f} not near any "
            f"page start; nearest={nearest:.1f}; starts={page_starts}"
        )


def test_no_cuts_inside_atomic_blocks(article_layout_and_plan):
    layout, plan = article_layout_and_plan
    atomic = [(b.y0, b.y1) for b in layout.blocks if b.is_atomic]
    for sl in plan.slices[1:]:
        for a0, a1 in atomic:
            if a1 - a0 > plan.slice_capacity:
                continue  # too tall: unavoidable
            assert not (a0 + 0.5 < sl.y0 < a1 - 0.5), (
                f"Cut at y={sl.y0:.1f} sliced atomic block [{a0:.1f},{a1:.1f}]"
            )


def test_no_main_heading_cut_through(article_layout_and_plan):
    """Make sure no cut falls inside a main heading's block (would split the
    heading itself)."""
    layout, plan = article_layout_and_plan
    for sl in plan.slices[1:]:
        for b in layout.blocks:
            if b.kind != BlockKind.MAIN_HEADING:
                continue
            assert not (b.y0 + 0.5 < sl.y0 < b.y1 - 0.5), (
                f"Cut at y={sl.y0:.1f} sliced main heading "
                f"{b.lines[0].text!r} [{b.y0:.1f},{b.y1:.1f}]"
            )
