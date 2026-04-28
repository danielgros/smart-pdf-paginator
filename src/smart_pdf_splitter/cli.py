"""Command-line entry point: `smart-pdf-split`."""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from .api import split_pdf
from .config import INCH, SplitConfig, Strategy, resolve_page_size
from .logging_config import configure_logging, get_logger

log = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="smart-pdf-split",
        description=(
            "Split a single very-tall PDF page into a multi-page US Letter PDF "
            "using semantic-aware boundaries."
        ),
    )
    p.add_argument("input", help="Path to input PDF (single tall page)")
    p.add_argument("output", help="Path to output multi-page PDF")
    p.add_argument(
        "--page-size",
        default="letter",
        help="Output page size: letter (default), legal, a4",
    )
    p.add_argument("--margin-top", type=float, default=0.5,
                   help="Top margin in inches (default 0.5)")
    p.add_argument("--margin-bottom", type=float, default=0.5,
                   help="Bottom margin in inches (default 0.5)")
    p.add_argument("--margin-left", type=float, default=0.5,
                   help="Left margin in inches (default 0.5)")
    p.add_argument("--margin-right", type=float, default=0.5,
                   help="Right margin in inches (default 0.5)")
    p.add_argument(
        "--strategy",
        choices=[s.value for s in Strategy],
        default=Strategy.HYBRID.value,
        help="Cut strategy (default hybrid)",
    )
    p.add_argument("--debug", action="store_true",
                   help="Emit debug artifacts (annotated overlay, plan summary)")
    p.add_argument("--debug-dir", default=None,
                   help="Directory for debug artifacts (default: <output>.debug)")
    p.add_argument("-v", "--verbose", action="count", default=0,
                   help="Increase verbosity (-v, -vv)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    if args.debug and level > logging.INFO:
        level = logging.INFO
    configure_logging(level)

    debug_dir = args.debug_dir
    if args.debug and not debug_dir:
        debug_dir = args.output + ".debug"

    cfg = SplitConfig(
        page_size=resolve_page_size(args.page_size),
        margin_top=args.margin_top * INCH,
        margin_bottom=args.margin_bottom * INCH,
        margin_left=args.margin_left * INCH,
        margin_right=args.margin_right * INCH,
        strategy=Strategy(args.strategy),
        debug=args.debug,
        debug_dir=debug_dir,
    )

    try:
        n = split_pdf(args.input, args.output, cfg)
    except Exception as e:
        log.error("Splitting failed: %s", e, exc_info=(level <= logging.DEBUG))
        return 2

    print(f"Wrote {n} pages to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
