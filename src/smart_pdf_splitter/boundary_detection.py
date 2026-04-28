"""Detect candidate split boundaries from a LayoutModel."""
from __future__ import annotations

from typing import List, Tuple

from .config import SplitConfig
from .logging_config import get_logger
from .models import (
    Block,
    BlockKind,
    BoundaryCandidate,
    BoundaryReason,
    LayoutModel,
)

log = get_logger(__name__)


def _classify_headings(layout: LayoutModel, cfg: SplitConfig) -> None:
    """Promote text blocks whose first line looks like a heading to BlockKind.HEADING.

    Heuristics: large font OR (bold AND short single line) AND extra spacing above.
    """
    threshold = layout.median_font_size * cfg.heading_size_ratio
    for i, block in enumerate(layout.blocks):
        if block.kind != BlockKind.TEXT or not block.lines:
            continue
        first = block.lines[0]
        size_ok = first.max_size >= threshold
        bold_short = first.is_bold and len(first.text.strip()) <= 80 and len(block.lines) <= 2
        # Extra space above relative to previous block?
        space_above = 0.0
        if i > 0:
            space_above = block.y0 - layout.blocks[i - 1].y1
        spaced = space_above > layout.median_line_height * 1.2

        if size_ok or (bold_short and spaced):
            block.kind = BlockKind.HEADING


def _detect_table_like(layout: LayoutModel) -> None:
    """Very lightweight table heuristic: block with many short lines of similar y-spacing
    AND multiple x-clusters per line — marked as TABLE.

    We keep this conservative; we don't want to *cut* tables, so labeling them helps.
    """
    for block in layout.blocks:
        if block.kind != BlockKind.TEXT or len(block.lines) < 3:
            continue
        # Count lines whose spans split into >=2 clear horizontal groups.
        multi_col_lines = 0
        for line in block.lines:
            xs = sorted((s.bbox[0], s.bbox[2]) for s in line.spans)
            if len(line.spans) >= 2:
                # Look for a horizontal gap > 30pt between consecutive spans.
                spans_sorted = sorted(line.spans, key=lambda s: s.bbox[0])
                for a, b in zip(spans_sorted, spans_sorted[1:]):
                    if b.bbox[0] - a.bbox[2] > 30.0:
                        multi_col_lines += 1
                        break
        if multi_col_lines >= max(2, len(block.lines) // 2):
            block.kind = BlockKind.TABLE


def detect_boundaries(
    layout: LayoutModel, cfg: SplitConfig
) -> List[BoundaryCandidate]:
    """Generate candidate split Y coordinates with semantic penalties.

    Coordinates are in the source page coordinate system (PDF points, origin top-left).
    Lower penalty = better cut.
    """
    _classify_headings(layout, cfg)
    _detect_table_like(layout)

    candidates: List[BoundaryCandidate] = []

    # Always allow cutting at the very top.
    candidates.append(
        BoundaryCandidate(y=0.0, reason=BoundaryReason.PAGE_TOP, semantic_penalty=0.0)
    )

    # Atomic blocks (image/table/figure): always emit BEFORE_ATOMIC at the top
    # and AFTER_ATOMIC at the bottom — these are the only valid cuts adjacent
    # to a diagram/chart/flowchart/table that fits on a page.
    for block in layout.blocks:
        if not block.is_atomic:
            continue
        candidates.append(
            BoundaryCandidate(
                y=block.y0 - 0.5,
                reason=BoundaryReason.BEFORE_ATOMIC,
                semantic_penalty=0.05,
            )
        )
        candidates.append(
            BoundaryCandidate(
                y=block.y1 + 0.5,
                reason=BoundaryReason.AFTER_ATOMIC,
                semantic_penalty=0.05,
            )
        )

    # Between consecutive blocks: gap candidates and "before heading" candidates.
    blocks = layout.blocks
    for i in range(len(blocks) - 1):
        cur = blocks[i]
        nxt = blocks[i + 1]
        gap = nxt.y0 - cur.y1
        gap_mid = cur.y1 + gap / 2.0

        if gap <= 0:
            # Overlapping blocks — skip; an overlap suggests multi-column text.
            continue

        large = gap >= layout.median_line_height * cfg.large_gap_ratio

        # 1. Before heading: cut just above the heading's bbox top.
        if nxt.kind == BlockKind.HEADING:
            penalty = 0.05  # excellent
            # Avoid splitting heading from immediately preceding heading.
            if cur.kind == BlockKind.HEADING:
                penalty += 0.4
            candidates.append(
                BoundaryCandidate(
                    y=max(cur.y1, nxt.y0 - 2.0),
                    reason=BoundaryReason.BEFORE_HEADING,
                    semantic_penalty=penalty,
                )
            )

        # 2. Large whitespace gap: cut in the middle of the gap.
        if large:
            candidates.append(
                BoundaryCandidate(
                    y=gap_mid,
                    reason=BoundaryReason.LARGE_GAP,
                    semantic_penalty=0.15,
                )
            )

        # 3. After-paragraph candidate: any inter-block gap is a paragraph-ish boundary.
        if gap > 0 and not large and nxt.kind != BlockKind.HEADING:
            # Penalty grows when next block is mid-table/image because we may break flow.
            base = 0.35
            if cur.kind in (BlockKind.TABLE, BlockKind.IMAGE):
                base += 0.4  # we just ended a table/image; OK to cut after.
                base = max(0.10, base - 0.5)  # actually a great place to cut
            if nxt.kind in (BlockKind.TABLE, BlockKind.IMAGE):
                base = min(0.20, base)  # before image/table is fine
            candidates.append(
                BoundaryCandidate(
                    y=gap_mid,
                    reason=BoundaryReason.AFTER_PARAGRAPH,
                    semantic_penalty=base,
                )
            )

    # Allow cutting at the very bottom.
    candidates.append(
        BoundaryCandidate(
            y=layout.page_height,
            reason=BoundaryReason.PAGE_BOTTOM,
            semantic_penalty=0.0,
        )
    )

    # Drop any candidate that falls strictly inside an atomic block (we are
    # never allowed to cut through diagrams/tables/figures unless they exceed
    # one page; that's enforced by the planner separately).
    atomic_intervals = [
        (b.y0, b.y1) for b in layout.blocks if b.is_atomic
    ]
    if atomic_intervals:
        def _inside_atomic(y: float) -> bool:
            for a0, a1 in atomic_intervals:
                if a0 + 0.5 < y < a1 - 0.5:
                    return True
            return False
        candidates = [c for c in candidates if not _inside_atomic(c.y)]

    # Deduplicate close candidates (within 1pt) keeping the best (lowest penalty).
    candidates.sort(key=lambda c: (c.y, c.semantic_penalty))
    deduped: List[BoundaryCandidate] = []
    for c in candidates:
        if deduped and abs(c.y - deduped[-1].y) < 1.0:
            if c.semantic_penalty < deduped[-1].semantic_penalty:
                deduped[-1] = c
            continue
        deduped.append(c)

    log.info("Generated %d boundary candidates.", len(deduped))
    return deduped


def find_safe_geometric_cut(
    layout: LayoutModel, y_min: float, y_max: float
) -> Tuple[float, BoundaryReason]:
    """Find a Y in (y_min, y_max] that does not slice a text line, preferring
    the largest available gap; falls back to y_max as a last resort.
    """
    # Collect all line bboxes in range.
    line_intervals: List[Tuple[float, float]] = []
    for b in layout.blocks:
        if b.kind == BlockKind.IMAGE:
            line_intervals.append((b.y0, b.y1))
            continue
        for ln in b.lines:
            if ln.y1 < y_min or ln.y0 > y_max:
                continue
            line_intervals.append((ln.y0, ln.y1))
    line_intervals.sort()

    # Find the largest gap inside (y_min, y_max].
    best_gap = -1.0
    best_y = y_max
    cursor = y_min
    for a, b in line_intervals:
        if a > cursor:
            gap = a - cursor
            mid = cursor + gap / 2.0
            if gap > best_gap and mid <= y_max:
                best_gap = gap
                best_y = mid
        cursor = max(cursor, b)
    # Trailing gap after last line.
    if y_max - cursor > best_gap:
        best_gap = y_max - cursor
        best_y = (cursor + y_max) / 2.0 if cursor < y_max else y_max

    return best_y, BoundaryReason.GEOMETRIC_FALLBACK
