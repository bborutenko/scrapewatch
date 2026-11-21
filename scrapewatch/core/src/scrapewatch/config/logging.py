"""Scrapewatch logging configuration.

Provides a unique logger with distinctive formatting to clearly identify
scrapewatch logs in mixed output streams.
"""

import logging
import sys
from typing import TextIO


def setup_logging(
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
    format_string: str | None = None,
) -> None:
    """Configure scrapewatch logging.
    
    Args:
        level: Log level (default: INFO)
        stream: Output stream (default: sys.stderr)
        format_string: Custom format string (default: scrapewatch format)
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    
    if stream is None:
        stream = sys.stderr
    
    if format_string is None:
        format_string = "[scrapewatch] %(levelname)s: %(message)s"
    
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(format_string))
    
    logger = get_logger()
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str = "scrapewatch") -> logging.Logger:
    """Get scrapewatch logger.
    
    Args:
        name: Logger name (default: "scrapewatch")
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
