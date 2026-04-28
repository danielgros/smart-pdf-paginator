"""Render a SplitPlan into an output multi-page PDF."""
from __future__ import annotations

import fitz

from .config import SplitConfig
from .logging_config import get_logger
from .models import SplitPlan

log = get_logger(__name__)


def render_pdf(
    src_doc: "fitz.Document",
    plan: SplitPlan,
    cfg: SplitConfig,
    output_path: str,
) -> None:
    """Render each slice from the source page onto a new Letter page.

    Each slice (in source coordinates) is placed into the content rect of an output
    page using `show_pdf_page` with a `clip` rect, preserving vector text/images.
    """
    out = fitz.open()
    pw, ph = cfg.page_size.width, cfg.page_size.height
    ml, mt = cfg.margin_left, cfg.margin_top
    cw, ch = cfg.content_width(), cfg.content_height()
    scale = plan.scale

    for i, sl in enumerate(plan.slices):
        page = out.new_page(width=pw, height=ph)
        slice_h_src = sl.height
        slice_h_out = slice_h_src * scale
        # Clip rect in source coordinates — full width, slice height.
        clip = fitz.Rect(0, sl.y0, plan.source_width, sl.y1)
        # Target rect on the output page: top-aligned within content area.
        target = fitz.Rect(ml, mt, ml + cw, mt + slice_h_out)
        try:
            page.show_pdf_page(target, src_doc, 0, clip=clip)
        except Exception as e:  # pragma: no cover - PyMuPDF defensive
            log.error("Failed to render slice %d (y=[%.1f,%.1f]): %s",
                      i + 1, sl.y0, sl.y1, e)
            raise
        log.debug(
            "Rendered page %d/%d: src y=[%.1f,%.1f] -> %.1f pt tall (fill=%.0f%%)",
            i + 1,
            len(plan.slices),
            sl.y0,
            sl.y1,
            slice_h_out,
            100.0 * slice_h_out / ch,
        )

    out.save(output_path, deflate=True, garbage=3)
    out.close()
    log.info("Wrote %d-page PDF to %s", len(plan.slices), output_path)
