"""Plan the cuts: convert candidates + layout into an ordered list of Slices."""
from __future__ import annotations

from typing import List, Tuple

from .boundary_detection import find_safe_geometric_cut
from .config import SplitConfig, Strategy
from .logging_config import get_logger
from .models import (
    BoundaryCandidate,
    BoundaryReason,
    LayoutModel,
    Slice,
    SplitPlan,
)

log = get_logger(__name__)


def _block_intervals(layout: LayoutModel) -> List[Tuple[float, float]]:
    return [(b.y0, b.y1) for b in layout.blocks]


def _cuts_through_block(y: float, intervals: List[Tuple[float, float]]) -> bool:
    for a, b in intervals:
        if a + 0.5 < y < b - 0.5:
            return True
    return False


def _compute_geometry(layout: LayoutModel, cfg: SplitConfig) -> Tuple[float, float]:
    """Return (scale, slice_capacity).

    scale = output points per source point (preserving aspect via width fit).
    slice_capacity = how many source-pt of vertical content fit on one output page.
    """
    content_w = cfg.content_width()
    content_h = cfg.content_height()
    if content_w <= 0 or content_h <= 0:
        raise ValueError("Margins leave no content area on the output page.")
    scale = content_w / layout.page_width
    slice_capacity = content_h / scale
    return scale, slice_capacity


def plan_splits(
    layout: LayoutModel,
    candidates: List[BoundaryCandidate],
    cfg: SplitConfig,
) -> SplitPlan:
    """Greedy-with-lookahead planner.

    For each output page we look at candidate boundaries within
    [current_y, current_y + slice_capacity] and pick the one that minimizes:

        cost = semantic_weight * semantic_penalty
             + underfill_weight * underfill_penalty
             + cut_through_weight * (1 if cuts_through_block else 0)

    underfill_penalty = max(0, (slice_capacity - used) / slice_capacity)^2

    If no candidate falls inside the window (e.g. one block is taller than a page),
    we fall back to a safe geometric cut just before slice_capacity.
    """
    scale, capacity = _compute_geometry(layout, cfg)
    log.info(
        "Output content area: %.1f x %.1f pt; scale=%.4f; slice capacity=%.1f src-pt",
        cfg.content_width(),
        cfg.content_height(),
        scale,
        capacity,
    )

    intervals = _block_intervals(layout)
    y_start, y_end = 0.0, layout.page_height
    # If huge empty top/bottom margins exist, trim them — but keep something so the first
    # output page doesn't start mid-content visually. We trim only if there is a clear
    # empty band > 0.5 inch.
    cmin, cmax = layout.content_y_range()
    if cmin > 36.0:
        y_start = max(0.0, cmin - 6.0)
    if y_end - cmax > 36.0:
        y_end = cmax + 6.0
    log.info("Effective content Y-range: [%.1f, %.1f]", y_start, y_end)

    # Filter candidates to active range.
    active = [c for c in candidates if y_start - 1 <= c.y <= y_end + 1]
    # Mark cut-through.
    for c in active:
        c.cuts_through_block = _cuts_through_block(c.y, intervals)

    slices: List[Slice] = []
    cur = y_start
    prev_reason = BoundaryReason.PAGE_TOP
    safety = 0
    semantic_enabled = cfg.strategy in (Strategy.SEMANTIC, Strategy.HYBRID)

    while cur < y_end - 0.5:
        safety += 1
        if safety > 1000:
            raise RuntimeError("Planner safety limit hit; aborting (likely a bug).")

        target_max = cur + capacity
        if target_max >= y_end:
            # Final page — cut at end.
            slices.append(
                Slice(
                    y0=cur,
                    y1=y_end,
                    reason_top=prev_reason,
                    reason_bottom=BoundaryReason.PAGE_BOTTOM,
                )
            )
            break

        # Window of acceptable cuts: at least min_fill_ratio of capacity, at most full.
        min_y = cur + capacity * cfg.min_fill_ratio
        window = [
            c for c in active if c.y > cur + 0.5 and c.y <= target_max
        ]

        chosen: BoundaryCandidate
        if semantic_enabled and window:
            best = None
            best_cost = float("inf")
            for c in window:
                used = c.y - cur
                underfill = max(0.0, (capacity - used) / capacity)
                # Heavily penalize anything below min fill unless it's the only option.
                under_pen = underfill ** 2
                if c.y < min_y:
                    under_pen += 0.5  # discourage tiny pages
                cost = (
                    cfg.semantic_weight * c.semantic_penalty
                    + cfg.underfill_weight * under_pen
                    + (cfg.cut_through_weight if c.cuts_through_block else 0.0)
                )
                if cost < best_cost:
                    best_cost = cost
                    best = c
            chosen = best  # type: ignore[assignment]
            log.debug(
                "Page %d: picked y=%.1f reason=%s pen=%.3f cost=%.3f (window=%d)",
                len(slices) + 1,
                chosen.y,
                chosen.reason.value,
                chosen.semantic_penalty,
                best_cost,
                len(window),
            )
        else:
            # Visual-only or no semantic candidates: safe geometric cut.
            y, reason = find_safe_geometric_cut(layout, min_y, target_max)
            chosen = BoundaryCandidate(y=y, reason=reason, semantic_penalty=1.0)
            chosen.cuts_through_block = _cuts_through_block(y, intervals)
            log.debug(
                "Page %d: geometric cut at y=%.1f", len(slices) + 1, chosen.y
            )

        # Guarantee progress.
        if chosen.y <= cur + 1.0:
            chosen = BoundaryCandidate(
                y=min(target_max, y_end),
                reason=BoundaryReason.GEOMETRIC_FALLBACK,
                semantic_penalty=1.0,
            )

        slices.append(
            Slice(
                y0=cur,
                y1=chosen.y,
                reason_top=prev_reason,
                reason_bottom=chosen.reason,
            )
        )
        cur = chosen.y
        prev_reason = chosen.reason

    log.info("Planned %d output pages.", len(slices))
    return SplitPlan(
        slices=slices,
        source_width=layout.page_width,
        source_height=layout.page_height,
        slice_capacity=capacity,
        scale=scale,
    )
