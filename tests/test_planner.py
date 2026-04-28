"""Tests for the planner."""
from __future__ import annotations

import fitz

from smart_pdf_splitter.boundary_detection import detect_boundaries
from smart_pdf_splitter.config import SplitConfig, Strategy
from smart_pdf_splitter.extractor import extract_layout
from smart_pdf_splitter.planner import plan_splits


def _plan(path, **cfg_kwargs):
    cfg = SplitConfig(**cfg_kwargs)
    with fitz.open(path) as doc:
        layout = extract_layout(doc)
        cands = detect_boundaries(layout, cfg)
        plan = plan_splits(layout, cands, cfg)
    return layout, plan, cfg


def test_plan_covers_full_height(simple_tall_pdf):
    layout, plan, _ = _plan(simple_tall_pdf)
    assert len(plan.slices) >= 2
    # Slices are contiguous and ordered.
    for a, b in zip(plan.slices, plan.slices[1:]):
        assert abs(a.y1 - b.y0) < 0.01
    assert plan.slices[0].y0 >= 0
    assert plan.slices[-1].y1 <= layout.page_height + 0.5


def test_no_slice_exceeds_capacity(simple_tall_pdf):
    _, plan, _ = _plan(simple_tall_pdf)
    for s in plan.slices:
        assert s.height <= plan.slice_capacity + 1.0


def test_visual_strategy_runs(simple_tall_pdf):
    _, plan, _ = _plan(simple_tall_pdf, strategy=Strategy.VISUAL)
    assert len(plan.slices) >= 2
