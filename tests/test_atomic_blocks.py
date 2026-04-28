"""Atomic-block protection: tables/images/figures must not be split across
pages unless they are taller than a single output page.
"""
from __future__ import annotations

import fitz

from smart_pdf_splitter.api import split_pdf
from smart_pdf_splitter.boundary_detection import detect_boundaries
from smart_pdf_splitter.config import LETTER, SplitConfig
from smart_pdf_splitter.extractor import extract_layout
from smart_pdf_splitter.models import BlockKind
from smart_pdf_splitter.planner import plan_splits


def _atomic_block_for_image(layout):
    """Find the (only) image/figure/table block in the layout."""
    return next(b for b in layout.blocks if b.is_atomic)


def test_image_extracted_as_atomic_block(pdf_with_figure_factory):
    path, _, fig_top = pdf_with_figure_factory(figure_height_pt=240.0)
    with fitz.open(path) as doc:
        layout = extract_layout(doc, SplitConfig())
    atomic = [b for b in layout.blocks if b.is_atomic]
    assert len(atomic) == 1
    blk = atomic[0]
    assert blk.kind == BlockKind.IMAGE
    # Top should match the position we recorded (loose tolerance).
    assert abs(blk.y0 - fig_top) < 4.0


def test_figure_fits_one_page_is_not_split(pdf_with_figure_factory):
    """If the diagram fits on one output page, no slice may cut through it."""
    path, page_h, _ = pdf_with_figure_factory(figure_height_pt=240.0)
    cfg = SplitConfig()
    with fitz.open(path) as doc:
        layout = extract_layout(doc, cfg)
        # Sanity: total page is taller than one Letter slice (so we will split).
        cands = detect_boundaries(layout, cfg)
        plan = plan_splits(layout, cands, cfg)
    assert len(plan.slices) >= 2

    blk = _atomic_block_for_image(layout)
    # Slice capacity must comfortably exceed block height for this fixture.
    assert blk.height < plan.slice_capacity, "fixture invalidated"

    # No cut may land strictly inside the atomic block.
    for sl in plan.slices[1:]:  # skip the very first y0=0
        assert not (blk.y0 + 0.5 < sl.y0 < blk.y1 - 0.5), (
            f"Cut at y={sl.y0:.1f} sliced atomic block "
            f"[{blk.y0:.1f}, {blk.y1:.1f}]"
        )


def test_figure_fits_one_page_round_trip(pdf_with_figure_factory, tmp_path):
    """End-to-end: rasterize the output and confirm the distinctive figure
    color (a light blue fill) appears on exactly one output page.
    """
    path, _, _ = pdf_with_figure_factory(figure_height_pt=240.0)
    out = str(tmp_path / "out.pdf")
    n = split_pdf(path, out, SplitConfig())
    assert n >= 2

    # Our fixture's figure is a 200x200 image filled with RGB (200, 220, 240).
    # Look for that color on each output page.
    target = (200, 220, 240)
    pages_with_figure = 0
    with fitz.open(out) as outdoc:
        for page in outdoc:
            pix = page.get_pixmap(dpi=72, alpha=False)
            samples = pix.samples  # bytes; RGB
            stride = 3
            # Scan a coarse grid; if many pixels match the target, this page has the figure.
            hits = 0
            step = max(1, (len(samples) // stride) // 4000)
            for i in range(0, len(samples) - stride, stride * step):
                r, g, b = samples[i], samples[i + 1], samples[i + 2]
                if abs(r - target[0]) <= 6 and abs(g - target[1]) <= 6 and abs(b - target[2]) <= 6:
                    hits += 1
            if hits >= 50:
                pages_with_figure += 1
    assert pages_with_figure == 1, (
        f"Figure was visually rendered on {pages_with_figure} pages; expected exactly 1."
    )


def test_figure_taller_than_page_is_split(pdf_with_figure_factory):
    """When the figure exceeds slice capacity, the planner is allowed to cut it."""
    cfg = SplitConfig()
    # Slice capacity ~= content_height / scale where scale = content_w / page_w.
    # For Letter with default margins: content_w=540, content_h=720; if page_w
    # is 8.5in*72 = 612, scale=540/612~=0.882, capacity=720/0.882~=816 src-pt.
    # Make the figure taller than this:
    figure_h = 1000.0
    path, _, _ = pdf_with_figure_factory(figure_height_pt=figure_h)
    with fitz.open(path) as doc:
        layout = extract_layout(doc, cfg)
        cands = detect_boundaries(layout, cfg)
        plan = plan_splits(layout, cands, cfg)
    blk = _atomic_block_for_image(layout)
    assert blk.height > plan.slice_capacity, "fixture invalidated"

    # Whether the planner cuts inside or not, it must NOT raise and must cover
    # the whole height. Since the figure is taller than a page, at least one
    # cut must intersect it.
    inside_cuts = [
        sl.y0 for sl in plan.slices[1:]
        if blk.y0 + 0.5 < sl.y0 < blk.y1 - 0.5
    ]
    assert len(inside_cuts) >= 1, (
        "Figure taller than a page should be sliced by at least one cut."
    )


def test_multi_block_table_is_detected_and_atomic(pdf_with_multi_block_table_factory):
    """Tables whose cells PyMuPDF emits as separate blocks should be merged
    into a single atomic ``TABLE`` block."""
    path, _, top, bot = pdf_with_multi_block_table_factory(n_rows=4, n_cols=3)
    with fitz.open(path) as doc:
        layout = extract_layout(doc, SplitConfig())
    tables = [b for b in layout.blocks if b.kind == BlockKind.TABLE]
    assert len(tables) == 1, f"Expected one TABLE block, got {len(tables)}"
    t = tables[0]
    # The merged table bbox must cover the actual table region (with the
    # header line included via auto-attachment).
    assert t.y0 <= top + 4.0
    assert t.y1 >= bot - 4.0


def test_multi_block_table_not_split(pdf_with_multi_block_table_factory):
    """No cut may land inside the merged multi-block table when it fits
    within a single output page."""
    cfg = SplitConfig()
    path, _, _, _ = pdf_with_multi_block_table_factory(n_rows=4, n_cols=3)
    with fitz.open(path) as doc:
        layout = extract_layout(doc, cfg)
        cands = detect_boundaries(layout, cfg)
        plan = plan_splits(layout, cands, cfg)
    tables = [b for b in layout.blocks if b.kind == BlockKind.TABLE]
    assert tables
    t = tables[0]
    assert t.height < plan.slice_capacity, "fixture invalidated"
    assert len(plan.slices) >= 2, "PDF should be tall enough to span multiple pages"
    for sl in plan.slices[1:]:
        assert not (t.y0 + 0.5 < sl.y0 < t.y1 - 0.5), (
            f"Cut at y={sl.y0:.1f} sliced multi-block table "
            f"[{t.y0:.1f}, {t.y1:.1f}]"
        )
