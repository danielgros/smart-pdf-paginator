"""Debug visualization: render annotated PNGs of the source page."""
from __future__ import annotations

import os
from typing import List

import fitz

from .config import SplitConfig
from .logging_config import get_logger
from .models import (
    BlockKind,
    BoundaryCandidate,
    LayoutModel,
    SplitPlan,
)

log = get_logger(__name__)


_BLOCK_COLORS = {
    BlockKind.TEXT: (0.20, 0.45, 0.85),
    BlockKind.HEADING: (0.85, 0.20, 0.20),
    BlockKind.IMAGE: (0.20, 0.65, 0.30),
    BlockKind.TABLE: (0.70, 0.45, 0.10),
    BlockKind.OTHER: (0.40, 0.40, 0.40),
}


def write_debug_artifacts(
    src_doc: "fitz.Document",
    layout: LayoutModel,
    candidates: List[BoundaryCandidate],
    plan: SplitPlan,
    cfg: SplitConfig,
) -> None:
    if not cfg.debug_dir:
        return
    os.makedirs(cfg.debug_dir, exist_ok=True)

    # 1. Annotated overlay PDF of the source page (one page, but tall).
    overlay = fitz.open()
    src_page = src_doc[0]
    page = overlay.new_page(width=layout.page_width, height=layout.page_height)
    page.show_pdf_page(page.rect, src_doc, 0)

    # Block rectangles.
    for b in layout.blocks:
        color = _BLOCK_COLORS.get(b.kind, (0.5, 0.5, 0.5))
        rect = fitz.Rect(*b.bbox)
        page.draw_rect(rect, color=color, width=0.6, overlay=True)
        page.insert_text(
            (rect.x0 + 1, max(8.0, rect.y0 - 2)),
            b.kind.value,
            fontsize=6,
            color=color,
        )

    # Candidate boundaries (light dashed lines).
    for c in candidates:
        page.draw_line(
            (0, c.y),
            (layout.page_width, c.y),
            color=(0.7, 0.7, 0.0),
            width=0.3,
            overlay=True,
        )

    # Final cut lines (bold red).
    for sl in plan.slices[1:]:
        page.draw_line(
            (0, sl.y0),
            (layout.page_width, sl.y0),
            color=(1.0, 0.0, 0.0),
            width=1.5,
            overlay=True,
        )

    overlay_pdf = os.path.join(cfg.debug_dir, "overlay.pdf")
    overlay.save(overlay_pdf, deflate=True)

    # 2. Render that overlay to PNG (may be huge — that's fine).
    pix = page.get_pixmap(dpi=cfg.debug_dpi)
    overlay_png = os.path.join(cfg.debug_dir, "overlay.png")
    pix.save(overlay_png)
    overlay.close()

    # 3. Plain text summary.
    summary = os.path.join(cfg.debug_dir, "plan.txt")
    with open(summary, "w", encoding="utf-8") as f:
        f.write(f"Source page: {layout.page_width:.1f} x {layout.page_height:.1f} pt\n")
        f.write(f"Median line height: {layout.median_line_height:.2f} pt\n")
        f.write(f"Median font size: {layout.median_font_size:.2f} pt\n")
        f.write(f"Blocks: {len(layout.blocks)}\n")
        kinds = {}
        for b in layout.blocks:
            kinds[b.kind.value] = kinds.get(b.kind.value, 0) + 1
        f.write(f"  by kind: {kinds}\n")
        f.write(f"Candidates: {len(candidates)}\n")
        f.write(f"Output pages: {len(plan.slices)}\n")
        f.write(f"Scale: {plan.scale:.4f}\n")
        f.write(f"Slice capacity (src-pt): {plan.slice_capacity:.1f}\n\n")
        for i, sl in enumerate(plan.slices, 1):
            f.write(
                f"  Page {i}: y=[{sl.y0:.1f}, {sl.y1:.1f}] "
                f"h={sl.height:.1f} top={sl.reason_top.value} "
                f"bottom={sl.reason_bottom.value}\n"
            )

    log.info("Wrote debug artifacts to %s", cfg.debug_dir)
