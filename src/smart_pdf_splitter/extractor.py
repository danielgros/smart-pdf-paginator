"""Extract a vertical LayoutModel from a tall single-page PDF using PyMuPDF."""
from __future__ import annotations

import statistics
from typing import List, Tuple

import fitz  # PyMuPDF

from .logging_config import get_logger
from .models import Block, BlockKind, LayoutModel, Line, Span

log = get_logger(__name__)


def _normalize_rotation(page: "fitz.Page") -> None:
    """If the page has a rotation, set it to 0 so coordinates align with display."""
    if page.rotation:
        log.info("Source page rotation=%d; normalizing to 0.", page.rotation)
        page.set_rotation(0)


def extract_layout(doc: "fitz.Document") -> LayoutModel:
    """Build a LayoutModel from the first (and only) page of `doc`."""
    if doc.page_count < 1:
        raise ValueError("Input PDF has no pages.")
    if doc.page_count > 1:
        log.warning(
            "Input has %d pages; only the first will be split.", doc.page_count
        )
    page = doc[0]
    _normalize_rotation(page)

    rect = page.rect
    page_w, page_h = rect.width, rect.height
    log.info("Source page size: %.1f x %.1f pt", page_w, page_h)

    raw = page.get_text("dict")
    blocks: List[Block] = []
    line_heights: List[float] = []
    font_sizes: List[float] = []

    for rb in raw.get("blocks", []):
        btype = rb.get("type", 0)
        bbox = tuple(rb["bbox"])  # type: ignore[assignment]
        if btype == 1:
            # Image block.
            blocks.append(Block(kind=BlockKind.IMAGE, bbox=bbox, lines=[]))
            continue

        # Text block.
        lines: List[Line] = []
        for rl in rb.get("lines", []):
            spans: List[Span] = []
            for rs in rl.get("spans", []):
                text = rs.get("text", "")
                if not text:
                    continue
                spans.append(
                    Span(
                        text=text,
                        size=float(rs.get("size", 0.0)),
                        flags=int(rs.get("flags", 0)),
                        bbox=tuple(rs["bbox"]),
                    )
                )
                font_sizes.append(float(rs.get("size", 0.0)))
            if not spans:
                continue
            lbbox = tuple(rl["bbox"])
            line = Line(bbox=lbbox, spans=spans)
            lines.append(line)
            line_heights.append(line.height)

        if not lines:
            continue
        blocks.append(Block(kind=BlockKind.TEXT, bbox=bbox, lines=lines))

    # Detect images that PyMuPDF reported only via get_images() but not as blocks.
    # (Rare for normal PDFs, skipped for simplicity.)

    blocks.sort(key=lambda b: (b.y0, b.bbox[0]))

    median_lh = statistics.median(line_heights) if line_heights else 12.0
    median_fs = statistics.median(font_sizes) if font_sizes else 10.0

    log.info(
        "Extracted %d blocks (%d text, %d image); median line h=%.1fpt, font=%.1fpt",
        len(blocks),
        sum(1 for b in blocks if b.kind == BlockKind.TEXT),
        sum(1 for b in blocks if b.kind == BlockKind.IMAGE),
        median_lh,
        median_fs,
    )

    return LayoutModel(
        page_width=page_w,
        page_height=page_h,
        blocks=blocks,
        median_line_height=median_lh,
        median_font_size=median_fs,
    )
