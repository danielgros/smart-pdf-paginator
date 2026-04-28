"""Detect candidate split boundaries from a LayoutModel.

Simplified rules:

* Cuts may happen at the page top, the page bottom, just before a main
  section heading, or immediately around an atomic block (image / table /
  figure).
* Subsection headings, paragraph gaps, and large whitespace gaps are *not*
  emitted as candidates — the planner fills pages naturally up to capacity
  and uses :func:`find_safe_geometric_cut` to avoid slicing through text.
"""
from __future__ import annotations

from typing import List, Tuple

from .config import SplitConfig
from .logging_config import get_logger
from .models import (
    BlockKind,
    BoundaryCandidate,
    BoundaryReason,
    LayoutModel,
)

log = get_logger(__name__)


def _classify_headings(layout: LayoutModel, cfg: SplitConfig) -> None:
    """Tag text blocks as ``MAIN_HEADING`` or ``HEADING`` based on font size.

    Only the first line's max font size matters. Headings are expected to be
    short (≤ 2 lines, ≤ 120 chars). Anything else stays ``TEXT``.
    """
    sub_threshold = layout.median_font_size * cfg.heading_size_ratio
    main_threshold = layout.median_font_size * cfg.main_heading_size_ratio
    for block in layout.blocks:
        if block.kind != BlockKind.TEXT or not block.lines:
            continue
        first = block.lines[0]
        if len(block.lines) > 2:
            continue
        if len(first.text.strip()) > 120:
            continue
        size = first.max_size
        if size >= main_threshold:
            block.kind = BlockKind.MAIN_HEADING
        elif size >= sub_threshold:
            block.kind = BlockKind.HEADING


def detect_boundaries(
    layout: LayoutModel, cfg: SplitConfig
) -> List[BoundaryCandidate]:
    """Generate the (small) set of candidate cut Y coordinates.

    Coordinates are in source-page space (PDF points, origin top-left).
    """
    _classify_headings(layout, cfg)

    candidates: List[BoundaryCandidate] = [
        BoundaryCandidate(y=0.0, reason=BoundaryReason.PAGE_TOP),
    ]

    # Atomic block edges.
    for block in layout.blocks:
        if not block.is_atomic:
            continue
        candidates.append(
            BoundaryCandidate(
                y=block.y0 - 0.5, reason=BoundaryReason.BEFORE_ATOMIC,
            )
        )
        candidates.append(
            BoundaryCandidate(
                y=block.y1 + 0.5, reason=BoundaryReason.AFTER_ATOMIC,
            )
        )

    # Main heading tops — these are the only forced semantic breaks.
    for block in layout.blocks:
        if block.kind != BlockKind.MAIN_HEADING:
            continue
        candidates.append(
            BoundaryCandidate(
                y=max(0.0, block.y0 - 1.0),
                reason=BoundaryReason.BEFORE_MAIN_HEADING,
            )
        )

    candidates.append(
        BoundaryCandidate(
            y=layout.page_height, reason=BoundaryReason.PAGE_BOTTOM,
        )
    )

    # Drop anything strictly inside an atomic block.
    atomic_intervals = [(b.y0, b.y1) for b in layout.blocks if b.is_atomic]
    if atomic_intervals:
        def _inside_atomic(y: float) -> bool:
            for a0, a1 in atomic_intervals:
                if a0 + 0.5 < y < a1 - 0.5:
                    return True
            return False
        candidates = [c for c in candidates if not _inside_atomic(c.y)]

    # Sort & dedupe within 1pt (keep the more meaningful reason).
    priority = {
        BoundaryReason.BEFORE_MAIN_HEADING: 0,
        BoundaryReason.BEFORE_ATOMIC: 1,
        BoundaryReason.AFTER_ATOMIC: 1,
        BoundaryReason.PAGE_TOP: 2,
        BoundaryReason.PAGE_BOTTOM: 2,
        BoundaryReason.GEOMETRIC_FALLBACK: 3,
    }
    candidates.sort(key=lambda c: (c.y, priority.get(c.reason, 9)))
    deduped: List[BoundaryCandidate] = []
    for c in candidates:
        if deduped and abs(c.y - deduped[-1].y) < 1.0:
            continue
        deduped.append(c)

    log.info("Generated %d boundary candidates.", len(deduped))
    return deduped


def find_safe_geometric_cut(
    layout: LayoutModel, y_min: float, y_max: float
) -> Tuple[float, BoundaryReason]:
    """Find a Y in (y_min, y_max] that does not slice a text line, preferring
    a cut as close to ``y_max`` as possible so pages fill naturally.
    """
    line_intervals: List[Tuple[float, float]] = []
    for b in layout.blocks:
        if b.is_atomic:
            line_intervals.append((b.y0, b.y1))
            continue
        for ln in b.lines:
            if ln.y1 < y_min or ln.y0 > y_max:
                continue
            line_intervals.append((ln.y0, ln.y1))
    line_intervals.sort()

    # Build the list of safe gaps inside (y_min, y_max] and pick the one with
    # the highest end <= y_max (i.e. the latest gap). This maximizes page fill
    # while still snapping to whitespace between lines.
    best_y = y_max
    cursor = y_min
    for a, b in line_intervals:
        if a > cursor:
            gap_lo = max(cursor, y_min)
            gap_hi = min(a, y_max)
            if gap_hi > gap_lo:
                best_y = (gap_lo + gap_hi) / 2.0
        cursor = max(cursor, b)
    # Trailing gap after the last line in range.
    if cursor < y_max:
        best_y = (cursor + y_max) / 2.0

    return best_y, BoundaryReason.GEOMETRIC_FALLBACK
