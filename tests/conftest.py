"""Shared fixtures: synthetic tall PDFs built with reportlab."""
from __future__ import annotations

import os
from typing import List, Tuple

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
