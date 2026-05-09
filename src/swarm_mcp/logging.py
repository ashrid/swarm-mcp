"""Logging helpers for MCP-safe stderr logging."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("swarm_mcp")
    if logger.handlers:
        logger.setLevel(level.upper())
        return logger

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[swarm-mcp] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logger
