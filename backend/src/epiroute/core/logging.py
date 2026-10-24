"""Structured logging configuration.

Logs are emitted as single-line JSON in every environment except an
interactive development shell, where a human-readable format is used instead.
A JSON format keeps ingestion diagnostics greppable without pulling in a
logging framework.

Secrets must never be logged. :func:`configure_logging` installs a filter that
redacts anything resembling an API key from formatted messages as a
defence-in-depth measure; the primary protection is simply not passing secrets
to the logger.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# Keys whose values are redacted if they ever reach a log record's `extra`.
_SENSITIVE_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "x-api-key", "password", "token", "secret"}
)

# Matches `X-API-Key: value`, `api_key=value` and bearer tokens in free text.
_SECRET_PATTERN = re.compile(
    r"(?i)\b(x-api-key|api[-_]?key|authorization|bearer|password|secret|token)\b\s*[:=]\s*\S+"
)

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def _redact(text: str) -> str:
    """Replace anything that looks like a credential assignment with a marker."""
    return _SECRET_PATTERN.sub(lambda m: f"{m.group(1)}=***", text)


class JsonFormatter(logging.Formatter):
    """Format records as one JSON object per line.

    Extra keyword arguments passed as ``logger.info("msg", extra={...})`` are
    merged into the object, which is how ingestion runs attach their run id,
    source URL and record counts.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as a JSON line with any ``extra`` fields merged."""
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = "***" if key.lower() in _SENSITIVE_KEYS else value
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Compact single-line format for interactive development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)-28s %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` for a terminal, redacting credential-like text."""
        return _redact(super().format(record))


def configure_logging(level: str = "INFO", *, json_output: bool | None = None) -> None:
    """Install EpiRoute's log handler on the root logger.

    Safe to call more than once: the existing EpiRoute handler is replaced
    rather than duplicated, which matters under uvicorn's reloader.

    Args:
        level: Minimum level name, e.g. ``"INFO"``.
        json_output: Force JSON on or off. When ``None``, JSON is used unless
            stderr is an interactive terminal.
    """
    if json_output is None:
        json_output = not sys.stderr.isatty()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_output else HumanFormatter())
    handler.set_name("epiroute")

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != "epiroute"]
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own access-log handler; keep it but stop the
    # duplicate propagation to our root handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = False

    # SQLAlchemy's engine logger is extremely verbose at INFO.
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")
