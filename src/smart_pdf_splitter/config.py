"""Configuration dataclasses for the splitter."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# All sizes in PDF points (1pt = 1/72 inch).
INCH = 72.0


@dataclass(frozen=True)
class PageSize:
    width: float
    height: float
    name: str = "custom"


LETTER = PageSize(width=8.5 * INCH, height=11.0 * INCH, name="letter")
LEGAL = PageSize(width=8.5 * INCH, height=14.0 * INCH, name="legal")
A4 = PageSize(width=595.276, height=841.890, name="a4")

_NAMED_SIZES = {"letter": LETTER, "legal": LEGAL, "a4": A4}


def resolve_page_size(name: str) -> PageSize:
    key = name.lower()
    if key not in _NAMED_SIZES:
        raise ValueError(f"Unknown page size: {name!r}. Known: {list(_NAMED_SIZES)}")
    return _NAMED_SIZES[key]


class Strategy(str, Enum):
    SEMANTIC = "semantic"
    VISUAL = "visual"
    HYBRID = "hybrid"


@dataclass
class SplitConfig:
    """User-facing configuration for splitting a tall PDF."""

    page_size: PageSize = LETTER

    # Margins on the OUTPUT pages, in points.
    margin_top: float = 0.5 * INCH
    margin_bottom: float = 0.5 * INCH
    margin_left: float = 0.5 * INCH
    margin_right: float = 0.5 * INCH

    strategy: Strategy = Strategy.HYBRID

    # Debug
    debug: bool = False
    debug_dir: Optional[str] = None

    # Tunables (sane defaults; rarely changed by users).
    # Minimum acceptable fill ratio of a page (0..1) before we prefer to extend.
    min_fill_ratio: float = 0.55
    # How strongly to penalize underfill vs. semantic quality.
    underfill_weight: float = 1.0
    semantic_weight: float = 1.5
    cut_through_weight: float = 25.0

    # Heading detection: span font-size must exceed median*this to be a heading candidate.
    heading_size_ratio: float = 1.15
    # A vertical gap is "large" if it exceeds this multiple of median line height.
    large_gap_ratio: float = 1.8

    # Render DPI for debug images.
    debug_dpi: int = 110

    def content_width(self) -> float:
        return self.page_size.width - self.margin_left - self.margin_right

    def content_height(self) -> float:
        return self.page_size.height - self.margin_top - self.margin_bottom
