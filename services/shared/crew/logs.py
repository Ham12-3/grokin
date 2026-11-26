"""Logging setup shared by the API and the worker."""

import logging

import structlog

from crew.vault.inject import redact_log_event


def configure(level: str = "INFO") -> None:
    """Console logs. Secret values in use by a run are scrubbed before anything is written."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.format_exc_info,
            redact_log_event,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=False,
    )
