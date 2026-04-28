"""End-to-end test: split a synthetic tall PDF and verify the output."""
from __future__ import annotations

import os

import fitz

from smart_pdf_splitter.api import split_pdf
from smart_pdf_splitter.config import LETTER, SplitConfig


def test_split_pdf_produces_letter_pages(simple_tall_pdf, tmp_path):
    out = os.path.join(tmp_path, "out.pdf")
    n = split_pdf(simple_tall_pdf, out, SplitConfig())
    assert n >= 2
    assert os.path.exists(out)

    with fitz.open(out) as doc:
        assert doc.page_count == n
        for page in doc:
            assert abs(page.rect.width - LETTER.width) < 0.5
            assert abs(page.rect.height - LETTER.height) < 0.5


def test_split_pdf_with_debug(simple_tall_pdf, tmp_path):
    out = os.path.join(tmp_path, "out.pdf")
    debug_dir = os.path.join(tmp_path, "dbg")
    cfg = SplitConfig(debug=True, debug_dir=debug_dir)
    n = split_pdf(simple_tall_pdf, out, cfg)
    assert n >= 1
    assert os.path.exists(os.path.join(debug_dir, "plan.txt"))
    assert os.path.exists(os.path.join(debug_dir, "overlay.pdf"))
    assert os.path.exists(os.path.join(debug_dir, "overlay.png"))


def test_text_preserved_in_output(simple_tall_pdf, tmp_path):
    out = os.path.join(tmp_path, "out.pdf")
    split_pdf(simple_tall_pdf, out, SplitConfig())
    all_text = ""
    with fitz.open(out) as doc:
        for p in doc:
            all_text += p.get_text("text")
    # Text from the synthetic PDF should appear in output.
    assert "Introduction" in all_text
    assert "Conclusion" in all_text
