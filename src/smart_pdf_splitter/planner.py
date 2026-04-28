"""Plan the cuts: convert candidates + layout into an ordered list of Slices.

Simplified algorithm. The only events that *force* a new page are:

* a **main section heading** (``BlockKind.MAIN_HEADING``) — start a new page
  beginning at the heading;
* an **atomic block** (image / table / figure) that would otherwise straddle
  the bottom of a page — start a new page at the block's top so it is kept
  whole. Atomic blocks taller than a single page are unavoidable and are
  sliced via the safe geometric path.

Everything else just fills pages naturally up to the available capacity. We
never cut through a text line: the safe geometric cut snaps to the largest
gap inside the available window.
"""
from __future__ import annotations

from typing import List, Tuple

from .boundary_detection import find_safe_geometric_cut
from .config import SplitConfig
from .logging_config import get_logger
from .models import (
    BlockKind,
    BoundaryCandidate,
    BoundaryReason,
    LayoutModel,
    Slice,
    SplitPlan,
)

log = get_logger(__name__)


def _compute_geometry(layout: LayoutModel, cfg: SplitConfig) -> Tuple[float, float]:
    """Return ``(scale, slice_capacity)`` in source-page points."""
    content_w = cfg.content_width()
    content_h = cfg.content_height()
    if content_w <= 0 or content_h <= 0:
        raise ValueError("Margins leave no content area on the output page.")
    scale = content_w / layout.page_width
    slice_capacity = content_h / scale
    return scale, slice_capacity


def plan_splits(
    layout: LayoutModel,
    candidates: List[BoundaryCandidate],  # kept for API compatibility
    cfg: SplitConfig,
) -> SplitPlan:
    """Produce a :class:`SplitPlan` from a layout.

    The ``candidates`` list is unused by the simplified algorithm but kept in
    the signature so existing callers (and the debug overlay) need not change.
    """
    del candidates  # unused

    scale, capacity = _compute_geometry(layout, cfg)
    log.info(
        "Output content area: %.1f x %.1f pt; scale=%.4f; slice capacity=%.1f src-pt",
        cfg.content_width(),
        cfg.content_height(),
        scale,
        capacity,
    )

    main_headings: List[float] = sorted(
        b.y0 for b in layout.blocks if b.kind == BlockKind.MAIN_HEADING
    )
    atomic: List[Tuple[float, float]] = [
        (b.y0, b.y1) for b in layout.blocks if b.is_atomic
    ]

    # Trim leading/trailing empty bands.
    y_start, y_end = 0.0, layout.page_height
    cmin, cmax = layout.content_y_range()
    if cmin > 36.0:
        y_start = max(0.0, cmin - 6.0)
    if y_end - cmax > 36.0:
        y_end = cmax + 6.0
    log.info("Effective content Y-range: [%.1f, %.1f]", y_start, y_end)

    slices: List[Slice] = []
    cur = y_start
    prev_reason = BoundaryReason.PAGE_TOP
    safety = 0

    while cur < y_end - 0.5:
        safety += 1
        if safety > 1000:
            raise RuntimeError("Planner safety limit hit; aborting (likely a bug).")

        target_max = cur + capacity
        chosen_y: float | None = None
        chosen_reason: BoundaryReason | None = None

        # ---- Main-heading rule -------------------------------------------
        # If a main heading is anywhere inside (cur, cur+capacity], it must
        # start a new page. Cut just above the first such heading. Headings
        # that are essentially already at the top of this page (within a few
        # lines of `cur`) are left in place — they're already "starting a new
        # page" by virtue of being at the top.
        skip_top = max(layout.median_line_height * 4.0, 50.0)
        for hy in main_headings:
            if hy <= cur + skip_top:
                continue
            if hy > target_max:
                break
            target_max = hy
            chosen_y = hy
            chosen_reason = BoundaryReason.BEFORE_MAIN_HEADING
            break

        # ---- Atomic-block protection -------------------------------------
        # If an atomic block of height <= capacity straddles target_max, clip
        # the target to its top so the block lands whole on the next page.
        for a0, a1 in atomic:
            if a1 - a0 > capacity:
                continue            # too tall: must be sliced
            if a1 <= cur + 0.5 or a0 >= target_max - 0.5:
                continue            # outside this window
            if a0 >= cur + 0.5 and a1 <= target_max + 0.5:
                continue            # fully contained: fine
            if a0 < cur + 0.5:
                continue            # we are already inside it
            if a0 < target_max:
                target_max = a0
                chosen_y = a0
                chosen_reason = BoundaryReason.BEFORE_ATOMIC

        if target_max >= y_end - 0.5:
            slices.append(
                Slice(
                    y0=cur,
                    y1=y_end,
                    reason_top=prev_reason,
                    reason_bottom=BoundaryReason.PAGE_BOTTOM,
                )
            )
            break

        # ---- Geometric fill ----------------------------------------------
        if chosen_y is None:
            chosen_y, chosen_reason = find_safe_geometric_cut(
                layout, cur + 1.0, target_max
            )

        # Guarantee progress.
        if chosen_y <= cur + 1.0:
            chosen_y = min(target_max, y_end)
            chosen_reason = BoundaryReason.GEOMETRIC_FALLBACK

        slices.append(
            Slice(
                y0=cur,
                y1=chosen_y,
                reason_top=prev_reason,
                reason_bottom=chosen_reason,
            )
        )
        cur = chosen_y
        prev_reason = chosen_reason

    log.info("Planned %d output pages.", len(slices))
    return SplitPlan(
        slices=slices,
        source_width=layout.page_width,
        source_height=layout.page_height,
        slice_capacity=capacity,
        scale=scale,
    )
