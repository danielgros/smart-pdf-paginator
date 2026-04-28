"""High-level library API."""
from __future__ import annotations

import fitz

from .boundary_detection import detect_boundaries
from .config import SplitConfig
from .debug import write_debug_artifacts
from .extractor import extract_layout
from .logging_config import get_logger
from .planner import plan_splits
from .renderer import render_pdf

log = get_logger(__name__)


def split_pdf(input_path: str, output_path: str, config: SplitConfig) -> int:
    """Split a tall single-page PDF into a multi-page Letter PDF.

    Returns the number of output pages produced.
    """
    log.info("Opening %s", input_path)
    with fitz.open(input_path) as src:
        layout = extract_layout(src, config)
        candidates = detect_boundaries(layout, config)
        plan = plan_splits(layout, candidates, config)
        render_pdf(src, plan, config, output_path)
        if config.debug:
            write_debug_artifacts(src, layout, candidates, plan, config)
    return len(plan.slices)
