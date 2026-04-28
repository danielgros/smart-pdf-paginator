"""Structured logging configuration."""
from __future__ import annotations

import logging
import sys


_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a single stream handler. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(level)
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    fmt = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
