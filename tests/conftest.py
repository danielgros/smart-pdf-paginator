"""Shared fixtures: synthetic tall PDFs built with reportlab."""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import pytest

try:
    from reportlab.lib.pagesizes import inch
    from reportlab.pdfgen import canvas
    HAVE_REPORTLAB = True
except Exception:  # pragma: no cover
    HAVE_REPORTLAB = False


def _make_tall_pdf(
    path: str,
    sections: List[Tuple[str, int]],  # (heading, num_paragraphs)
    width_in: float = 8.5,
    line_height_pt: float = 14.0,
    paragraph_lines: int = 6,
    section_gap_pt: float = 28.0,
) -> None:
    """Generate a tall single-page PDF with a deterministic layout."""
    if not HAVE_REPORTLAB:
        pytest.skip("reportlab not installed")

    # Compute total page height.
    body_size = 11
    heading_size = 18
    margin = 0.5 * inch
    y_used = margin
    for _, n_par in sections:
        y_used += heading_size + 6  # heading + spacing
        y_used += n_par * (paragraph_lines * line_height_pt + 10)
        y_used += section_gap_pt
    y_used += margin
    page_h = y_used

    width_pt = width_in * inch
    c = canvas.Canvas(path, pagesize=(width_pt, page_h))

    # We draw from top-down: reportlab origin is bottom-left.
    cur_y_top = page_h - margin
    for heading, n_par in sections:
        # Heading
        c.setFont("Helvetica-Bold", heading_size)
        c.drawString(margin, cur_y_top - heading_size, heading)
        cur_y_top -= heading_size + 6

        c.setFont("Helvetica", body_size)
        for p in range(n_par):
            for ln in range(paragraph_lines):
                txt = f"{heading[:8]} para {p+1} line {ln+1}: " + ("lorem ipsum " * 6)
                c.drawString(margin, cur_y_top - line_height_pt, txt)
                cur_y_top -= line_height_pt
            cur_y_top -= 10  # paragraph gap
        cur_y_top -= section_gap_pt

    c.showPage()
    c.save()


@pytest.fixture
def tall_pdf_factory(tmp_path):
    def make(name="tall.pdf", **kwargs):
        path = os.path.join(tmp_path, name)
        _make_tall_pdf(path, **kwargs)
        return path
    return make


@pytest.fixture
def simple_tall_pdf(tall_pdf_factory):
    return tall_pdf_factory(
        sections=[
            ("Introduction", 2),
            ("Background", 3),
            ("Methods", 2),
            ("Results", 4),
            ("Discussion", 3),
            ("Conclusion", 1),
        ],
    )


def _make_pdf_with_figure(
    path: str,
    figure_height_pt: float,
    width_in: float = 8.5,
    line_height_pt: float = 14.0,
    paragraph_lines: int = 6,
    paragraphs_before: int = 4,
    paragraphs_after: int = 4,
) -> Tuple[float, float]:
    """Build a tall PDF with paragraphs, then an embedded raster image of
    the requested height, then more paragraphs.

    Returns ``(page_height_pt, figure_top_pt)`` where ``figure_top_pt`` is in
    PDF/PyMuPDF coordinates (origin top-left).
    """
    if not HAVE_REPORTLAB:
        pytest.skip("reportlab not installed")

    body_size = 11
    margin = 0.5 * inch
    width_pt = width_in * inch
    figure_width_pt = width_pt - 2 * margin

    body_block_h = paragraph_lines * line_height_pt + 10
    page_h = (
        margin
        + paragraphs_before * body_block_h
        + 12  # spacer
        + figure_height_pt
        + 12
        + paragraphs_after * body_block_h
        + margin
    )

    # Create a small in-memory raster image to embed.
    from reportlab.lib.utils import ImageReader
    try:
        from PIL import Image
    except Exception:  # pragma: no cover
        pytest.skip("Pillow not installed")
    import io
    img = Image.new("RGB", (200, 200), (200, 220, 240))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    image_reader = ImageReader(buf)

    c = canvas.Canvas(path, pagesize=(width_pt, page_h))
    cur_y_top = page_h - margin  # top y in reportlab (bottom-left origin) reference
    c.setFont("Helvetica", body_size)
    for p in range(paragraphs_before):
        for ln in range(paragraph_lines):
            txt = f"Body para {p+1} line {ln+1}: " + ("lorem ipsum dolor sit amet " * 4)
            c.drawString(margin, cur_y_top - line_height_pt, txt)
            cur_y_top -= line_height_pt
        cur_y_top -= 10
    cur_y_top -= 12
    # Reportlab origin is bottom-left; image is drawn from its bottom-left corner.
    img_bottom = cur_y_top - figure_height_pt
    c.drawImage(
        image_reader,
        margin,
        img_bottom,
        width=figure_width_pt,
        height=figure_height_pt,
        preserveAspectRatio=False,
        mask="auto",
    )
    figure_top_pdf = page_h - cur_y_top  # convert to top-down (PyMuPDF) coords
    cur_y_top = img_bottom - 12
    for p in range(paragraphs_after):
        for ln in range(paragraph_lines):
            txt = f"Tail para {p+1} line {ln+1}: " + ("lorem ipsum dolor sit amet " * 4)
            c.drawString(margin, cur_y_top - line_height_pt, txt)
            cur_y_top -= line_height_pt
        cur_y_top -= 10
    c.showPage()
    c.save()
    return page_h, figure_top_pdf


def _make_pdf_with_multi_block_table(
    path: str,
    n_rows: int = 4,
    n_cols: int = 3,
    row_height_pt: float = 32.0,
    col_width_pt: float = 150.0,
    width_in: float = 8.5,
    paragraphs_before: int = 12,
    paragraphs_after: int = 12,
) -> Tuple[float, float, float]:
    """Build a tall PDF with a header line followed by a grid of cells, each
    drawn as a *separate* ``c.drawString`` so that PyMuPDF extracts every cell
    as its own block (the realistic pattern that broke the old detector).

    Returns ``(page_h, table_top_pdf, table_bottom_pdf)`` in PyMuPDF
    (top-down) coordinates.
    """
    if not HAVE_REPORTLAB:
        pytest.skip("reportlab not installed")

    body_size = 11
    line_height_pt = 14.0
    paragraph_lines = 6
    margin = 0.5 * inch
    width_pt = width_in * inch

    body_block_h = paragraph_lines * line_height_pt + 10
    table_h = (n_rows + 1) * row_height_pt  # +1 for header line
    page_h = (
        margin
        + paragraphs_before * body_block_h
        + 24
        + table_h
        + 24
        + paragraphs_after * body_block_h
        + margin
    )

    c = canvas.Canvas(path, pagesize=(width_pt, page_h))
    cur_y_top = page_h - margin
    c.setFont("Helvetica", body_size)
    for p in range(paragraphs_before):
        for ln in range(paragraph_lines):
            c.drawString(margin, cur_y_top - line_height_pt,
                         f"Pre para {p+1} line {ln+1}: " + "lorem ipsum dolor sit amet " * 4)
            cur_y_top -= line_height_pt
        cur_y_top -= 10
    cur_y_top -= 24

    # Header (single short line spanning the table width).
    c.setFont("Helvetica-Bold", body_size)
    c.drawString(margin, cur_y_top - line_height_pt,
                 "  ".join(f"Col{j+1}" for j in range(n_cols)))
    table_top_rl = cur_y_top  # reportlab top of table (bottom-left origin)
    cur_y_top -= row_height_pt

    # Cell rows: draw each cell as its OWN multi-line paragraph so PyMuPDF
    # emits a separate block per cell (matching the real-world extraction).
    c.setFont("Helvetica", body_size)
    cell_lines = 2
    for r in range(n_rows):
        for j in range(n_cols):
            cell_x = margin + j * col_width_pt
            for ln in range(cell_lines):
                c.drawString(
                    cell_x,
                    cur_y_top - line_height_pt - ln * line_height_pt,
                    f"r{r+1}c{j+1} line{ln+1} content",
                )
        cur_y_top -= row_height_pt
    table_bottom_rl = cur_y_top
    cur_y_top -= 24

    for p in range(paragraphs_after):
        for ln in range(paragraph_lines):
            c.drawString(margin, cur_y_top - line_height_pt,
                         f"Post para {p+1} line {ln+1}: " + "lorem ipsum dolor sit amet " * 4)
            cur_y_top -= line_height_pt
        cur_y_top -= 10
    c.showPage()
    c.save()

    table_top_pdf = page_h - table_top_rl
    table_bottom_pdf = page_h - table_bottom_rl
    return page_h, table_top_pdf, table_bottom_pdf


@pytest.fixture
def pdf_with_multi_block_table_factory(tmp_path):
    def make(name="table.pdf", **kwargs):
        path = os.path.join(tmp_path, name)
        page_h, top, bot = _make_pdf_with_multi_block_table(path, **kwargs)
        return path, page_h, top, bot
    return make


@pytest.fixture
def pdf_with_figure_factory(tmp_path):
    """Factory: returns ``(path, page_h, figure_top_y)`` for a PDF with one image.

    ``figure_height_pt`` controls how tall the embedded image is.
    """
    def make(name="figure.pdf", figure_height_pt: float = 250.0, **kwargs):
        path = os.path.join(tmp_path, name)
        page_h, fig_top = _make_pdf_with_figure(
            path, figure_height_pt=figure_height_pt, **kwargs
        )
        return path, page_h, fig_top
    return make
