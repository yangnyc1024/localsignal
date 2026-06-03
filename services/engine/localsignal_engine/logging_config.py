"""Centralised logging setup for the localsignal engine.

Call configure_logging() once at process startup (e.g. in scheduler.py
or any run_*.py entry point).  All other modules just do:

    import logging
    logger = logging.getLogger(__name__)
"""
import logging
import os
import sys


def configure_logging(level: str | None = None) -> None:
    """Configure root logger with a structured text format.

    Level precedence: argument > LOG_LEVEL env var > INFO.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        stream=sys.stdout,
        level=resolved,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        force=True,
    )
    # Quieten noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
