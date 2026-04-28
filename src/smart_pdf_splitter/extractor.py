"""Extract a vertical LayoutModel from a tall single-page PDF using PyMuPDF."""
from __future__ import annotations

import statistics
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from .config import SplitConfig
from .logging_config import get_logger
from .models import Block, BlockKind, LayoutModel, Line, Span

log = get_logger(__name__)


def _normalize_rotation(page: "fitz.Page") -> None:
    """If the page has a rotation, set it to 0 so coordinates align with display."""
    if page.rotation:
        log.info("Source page rotation=%d; normalizing to 0.", page.rotation)
        page.set_rotation(0)


def extract_layout(
    doc: "fitz.Document", cfg: Optional[SplitConfig] = None
) -> LayoutModel:
    """Build a LayoutModel from the first (and only) page of `doc`."""
    cfg = cfg or SplitConfig()
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

    median_lh = statistics.median(line_heights) if line_heights else 12.0
    median_fs = statistics.median(font_sizes) if font_sizes else 10.0

    # Detect vector-drawing figures (charts/diagrams/flowcharts) and merge
    # them into the block list as atomic FIGURE blocks.
    if cfg.detect_figures:
        figures = _detect_vector_figures(page, blocks, median_lh, cfg)
        if figures:
            log.info("Detected %d vector-drawing figure(s).", len(figures))
            blocks.extend(figures)

    blocks.sort(key=lambda b: (b.y0, b.bbox[0]))

    # Detect tables that PyMuPDF emits as multiple separate blocks (one per
    # cell). Merge them into single atomic TABLE blocks so they're never split.
    blocks = _detect_multi_block_tables(blocks, median_lh)

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


def _rect_overlap_y(a: Tuple[float, float, float, float],
                    b: Tuple[float, float, float, float]) -> float:
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _detect_vector_figures(
    page: "fitz.Page",
    existing_blocks: List[Block],
    median_line_height: float,
    cfg: SplitConfig,
) -> List[Block]:
    """Cluster vector drawings into atomic FIGURE blocks.

    We use ``page.get_drawings()`` which returns vector paths (lines, curves,
    rectangles). Charts, diagrams and flowcharts are typically composed of
    many such paths. We:

      1. Drop tiny paths (likely rules / underlines / separators).
      2. Cluster remaining paths vertically by proximity.
      3. Drop clusters shorter than ``figure_min_height_pt``.
      4. Drop clusters that overlap heavily with text blocks (they're
         decorations of running text, not figures).
    """
    try:
        drawings = page.get_drawings()
    except Exception as e:  # pragma: no cover - defensive
        log.debug("get_drawings() failed: %s", e)
        return []
    if not drawings:
        return []

    # 1. Collect non-trivial drawing rects.
    rects: List[Tuple[float, float, float, float]] = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        # Drop near-zero-height/width strokes (rules, separators, underlines).
        if r.height < 3.0 or r.width < 3.0:
            continue
        rects.append((r.x0, r.y0, r.x1, r.y1))
    if not rects:
        return []

    # 2. Cluster vertically.
    rects.sort(key=lambda r: r[1])
    cluster_gap = max(median_line_height * cfg.figure_cluster_gap_ratio, 6.0)
    clusters: List[List[Tuple[float, float, float, float]]] = [[rects[0]]]
    for r in rects[1:]:
        last = clusters[-1]
        last_y1 = max(rr[3] for rr in last)
        last_y0 = min(rr[1] for rr in last)
        if r[1] - last_y1 <= cluster_gap and r[1] >= last_y0 - cluster_gap:
            last.append(r)
        else:
            clusters.append([r])

    figures: List[Block] = []
    for cl in clusters:
        x0 = min(r[0] for r in cl)
        y0 = min(r[1] for r in cl)
        x1 = max(r[2] for r in cl)
        y1 = max(r[3] for r in cl)
        bbox = (x0, y0, x1, y1)

        # 3. Reject clusters that are too small to be a figure.
        if (y1 - y0) < cfg.figure_min_height_pt:
            continue
        if (x1 - x0) < cfg.figure_min_height_pt:
            continue
        # Need at least 3 distinct paths to look like a diagram (not a single box).
        if len(cl) < 3:
            continue

        # 4. Reject clusters that overlap heavily with text blocks.
        height = y1 - y0
        text_overlap = 0.0
        for tb in existing_blocks:
            if tb.kind not in (BlockKind.TEXT, BlockKind.HEADING):
                continue
            text_overlap += _rect_overlap_y(bbox, tb.bbox)
        if height > 0 and text_overlap / height > 0.5:
            continue

        figures.append(Block(kind=BlockKind.FIGURE, bbox=bbox, lines=[]))

    return figures


# ---------------------------------------------------------------------------
# Multi-block table detection
# ---------------------------------------------------------------------------
def _detect_multi_block_tables(
    blocks: List[Block], median_line_height: float
) -> List[Block]:
    """Recognize tables formed by *multiple* separate text blocks aligned in
    rows and columns, and merge each into a single atomic ``TABLE`` block.

    PyMuPDF often emits one block per table cell. The previous heuristic only
    looked at columns *inside* a single block and therefore missed these
    tables entirely — letting the planner cut between rows.

    A *row* is a set of two or more text/heading blocks whose y-ranges
    overlap each other and whose x-ranges do **not** overlap (i.e. they sit
    side-by-side). A *table* is a vertical run of ≥2 such rows separated by
    small gaps. An optional one-line header sitting just above the first row
    is attached if its x-range fits within the table.
    """
    n = len(blocks)
    if n < 4:
        return blocks

    # 1. Cluster blocks into rows by vertical overlap.
    indices = sorted(range(n), key=lambda i: (blocks[i].y0, blocks[i].bbox[0]))
    row_of: List[int] = [-1] * n
    rows: List[List[int]] = []
    for i in indices:
        b = blocks[i]
        if b.kind in (BlockKind.IMAGE, BlockKind.FIGURE):
            continue
        placed = False
        # Try to attach to the most recent open row.
        for ri in range(len(rows) - 1, -1, -1):
            row = rows[ri]
            ry0 = min(blocks[k].y0 for k in row)
            ry1 = max(blocks[k].y1 for k in row)
            # Stop scanning once we're well past where this row ended.
            if b.y0 > ry1 + median_line_height * 0.5:
                break
            overlap = min(b.y1, ry1) - max(b.y0, ry0)
            min_h = min(b.height, ry1 - ry0)
            if min_h > 0 and overlap >= min(8.0, min_h * 0.5):
                row.append(i)
                row_of[i] = ri
                placed = True
                break
        if not placed:
            row_of[i] = len(rows)
            rows.append([i])

    # 2. Identify "table rows": >=2 column-groups, where blocks whose x-ranges
    # overlap each other are merged into the same column-group (handles e.g.
    # a sub-line "user@example.com" rendered inside a wider cell as a separate
    # block).
    def is_table_row(row: List[int]) -> bool:
        if len(row) < 2:
            return False
        sr = sorted(row, key=lambda k: blocks[k].bbox[0])
        cols: List[List[int]] = [[sr[0]]]
        for k in sr[1:]:
            last_col = cols[-1]
            last_x1 = max(blocks[m].bbox[2] for m in last_col)
            bx0 = blocks[k].bbox[0]
            if bx0 < last_x1 - 2.0:
                # Horizontally overlaps last column-group: same cell.
                last_col.append(k)
            else:
                cols.append([k])
        return len(cols) >= 2

    # 3. Find runs of consecutive table rows (small inter-row gap).
    rows_y = [
        (min(blocks[k].y0 for k in r), max(blocks[k].y1 for k in r))
        for r in rows
    ]
    table_ranges: List[Tuple[int, int]] = []  # half-open [i0, i1) row indices
    i = 0
    while i < len(rows):
        if not is_table_row(rows[i]):
            i += 1
            continue
        j = i + 1
        while j < len(rows) and is_table_row(rows[j]):
            inter_gap = rows_y[j][0] - rows_y[j - 1][1]
            if inter_gap > median_line_height * 2.5:
                break
            j += 1
        if j - i >= 2:
            table_ranges.append((i, j))
        i = j if j > i else i + 1

    if not table_ranges:
        return blocks

    # 4. Build merged result.
    merged: set[int] = set()
    new_blocks: List[Block] = []
    for (i0, i1) in table_ranges:
        member_indices: List[int] = []
        for r in range(i0, i1):
            member_indices.extend(rows[r])

        x0 = min(blocks[k].bbox[0] for k in member_indices)
        y0 = min(blocks[k].y0 for k in member_indices)
        x1 = max(blocks[k].bbox[2] for k in member_indices)
        y1 = max(blocks[k].y1 for k in member_indices)

        # Optional: attach a single short header block sitting directly above.
        first_row = rows[i0]
        first_y0 = min(blocks[k].y0 for k in first_row)
        union_x0 = min(blocks[k].bbox[0] for k in first_row)
        union_x1 = max(blocks[k].bbox[2] for k in first_row)
        # Find the closest text/heading block whose y1 < first_y0.
        best_header = None
        best_gap = float("inf")
        for k, blk in enumerate(blocks):
            if k in merged or k in member_indices:
                continue
            if blk.kind in (BlockKind.IMAGE, BlockKind.FIGURE, BlockKind.TABLE):
                continue
            if blk.y1 > first_y0 - 0.5:
                continue
            gap = first_y0 - blk.y1
            if gap < best_gap:
                best_gap = gap
                best_header = k
        if (
            best_header is not None
            and best_gap <= median_line_height * 2.0
            and blocks[best_header].bbox[0] >= union_x0 - 6.0
            and blocks[best_header].bbox[2] <= union_x1 + 6.0
            and blocks[best_header].height < median_line_height * 3.0
        ):
            member_indices.append(best_header)
            hb = blocks[best_header]
            x0 = min(x0, hb.bbox[0])
            y0 = min(y0, hb.y0)
            x1 = max(x1, hb.bbox[2])
            y1 = max(y1, hb.y1)

        merged.update(member_indices)
        # Collect lines from constituent text blocks (top-down) for traceability.
        lines: List[Line] = []
        for k in sorted(member_indices, key=lambda kk: blocks[kk].y0):
            lines.extend(blocks[k].lines)
        new_blocks.append(
            Block(kind=BlockKind.TABLE, bbox=(x0, y0, x1, y1), lines=lines)
        )

    for k, blk in enumerate(blocks):
        if k not in merged:
            new_blocks.append(blk)
    new_blocks.sort(key=lambda b: (b.y0, b.bbox[0]))

    log.info(
        "Detected %d multi-block table(s) (merged %d cell blocks).",
        len(table_ranges), len(merged),
    )
    return new_blocks
