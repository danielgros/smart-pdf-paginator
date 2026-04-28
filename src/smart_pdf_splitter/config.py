"""Configuration dataclasses for the splitter."""
from __future__ import annotations

from dataclasses import dataclass
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
    """Deprecated. Retained as a no-op for backward compatibility."""
    SEMANTIC = "semantic"
    VISUAL = "visual"
    HYBRID = "hybrid"


@dataclass
class SplitConfig:
    """User-facing configuration for splitting a tall PDF.

    The splitter has two simple rules:

    1. **Atomic blocks** (images / tables / vector figures) must never be split
       across pages unless they exceed one page on their own.
    2. **Main section headings** always start a new output page. Subsection
       headings flow normally with the surrounding text.

    Everything else fills pages naturally up to the available capacity.
    """

    page_size: PageSize = LETTER

    # Margins on the OUTPUT pages, in points.
    margin_top: float = 0.5 * INCH
    margin_bottom: float = 0.5 * INCH
    margin_left: float = 0.5 * INCH
    margin_right: float = 0.5 * INCH

    # Deprecated; kept so existing CLI/library callers don't break.
    strategy: Strategy = Strategy.HYBRID

    # Debug
    debug: bool = False
    debug_dir: Optional[str] = None

    # Heading detection.
    # A line is a *heading* if its font size >= median * heading_size_ratio.
    heading_size_ratio: float = 1.15
    # A heading is a *main* heading (forces a new page) if its font size
    # >= median * main_heading_size_ratio. Tune to match your document.
    main_heading_size_ratio: float = 1.4

    # Atomic-block protection (figures/diagrams/charts/flowcharts/tables/images).
    detect_figures: bool = True
    figure_min_height_pt: float = 24.0
    figure_cluster_gap_ratio: float = 1.5

    # Render DPI for debug images.
    debug_dpi: int = 110

    def content_width(self) -> float:
        return self.page_size.width - self.margin_left - self.margin_right

    def content_height(self) -> float:
        return self.page_size.height - self.margin_top - self.margin_bottom
