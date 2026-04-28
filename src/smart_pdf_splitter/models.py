"""Core data models for layout, boundaries, and split plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class BlockKind(str, Enum):
    TEXT = "text"
    HEADING = "heading"            # subsection heading (no forced page break)
    MAIN_HEADING = "main_heading"  # main section heading (forces new page)
    IMAGE = "image"
    TABLE = "table"   # heuristically detected (column-clustered text rows)
    FIGURE = "figure"  # heuristically detected (vector drawings: charts/diagrams/flowcharts)
    OTHER = "other"

    @property
    def is_atomic(self) -> bool:
        """Atomic blocks must NEVER be split across pages unless they exceed
        a full page on their own. Tables, images and figures (vector
        diagrams/charts/flowcharts) are atomic.
        """
        return self in (BlockKind.IMAGE, BlockKind.TABLE, BlockKind.FIGURE)

    @property
    def is_main_heading(self) -> bool:
        """Main section headings always start a new output page."""
        return self is BlockKind.MAIN_HEADING


@dataclass
class Span:
    text: str
    size: float
    flags: int  # PyMuPDF span flags (bit 4 = bold, bit 1 = italic, etc.)
    bbox: Tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class Line:
    bbox: Tuple[float, float, float, float]
    spans: List[Span] = field(default_factory=list)

    @property
    def y0(self) -> float: return self.bbox[1]
    @property
    def y1(self) -> float: return self.bbox[3]
    @property
    def height(self) -> float: return self.bbox[3] - self.bbox[1]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def max_size(self) -> float:
        return max((s.size for s in self.spans), default=0.0)

    @property
    def is_bold(self) -> bool:
        # PyMuPDF: span flag bit 4 (==16) typically indicates bold.
        return any(bool(s.flags & 16) for s in self.spans)


@dataclass
class Block:
    kind: BlockKind
    bbox: Tuple[float, float, float, float]
    lines: List[Line] = field(default_factory=list)

    @property
    def y0(self) -> float: return self.bbox[1]
    @property
    def y1(self) -> float: return self.bbox[3]
    @property
    def height(self) -> float: return self.bbox[3] - self.bbox[1]

    @property
    def is_atomic(self) -> bool:
        return self.kind.is_atomic


@dataclass
class LayoutModel:
    """Vertical layout of the (single) source page."""
    page_width: float
    page_height: float
    blocks: List[Block]  # sorted by y0
    median_line_height: float
    median_font_size: float

    def content_y_range(self) -> Tuple[float, float]:
        if not self.blocks:
            return (0.0, self.page_height)
        return (min(b.y0 for b in self.blocks),
                max(b.y1 for b in self.blocks))


class BoundaryReason(str, Enum):
    """Why a cut was placed at a given Y coordinate.

    The simplified planner produces only these reasons. Anything else (gaps
    between paragraphs, subsection headings, etc.) flows through normal
    geometric fill and is reported as ``GEOMETRIC_FALLBACK``.
    """
    PAGE_TOP = "page_top"
    PAGE_BOTTOM = "page_bottom"
    BEFORE_MAIN_HEADING = "before_main_heading"  # forced: main heading starts new page
    BEFORE_ATOMIC = "before_atomic"              # forced: atomic block kept whole
    AFTER_ATOMIC = "after_atomic"                # cut just below an atomic block
    GEOMETRIC_FALLBACK = "geometric_fallback"    # safe fill cut between text lines


@dataclass
class BoundaryCandidate:
    """A candidate Y coordinate (in source page space) where we may cut."""
    y: float
    reason: BoundaryReason


@dataclass
class Slice:
    """A vertical slice of the source page mapped onto one output page."""
    y0: float
    y1: float
    reason_top: BoundaryReason
    reason_bottom: BoundaryReason

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class SplitPlan:
    slices: List[Slice]
    source_width: float
    source_height: float
    # Source-space height a single output page can show.
    slice_capacity: float
    scale: float  # output_pt_per_source_pt
