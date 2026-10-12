"""Structured logging with secret sanitization.

Two layers of protection:
1. Any key whose name looks sensitive (password, token, secret, api_key, login...)
   has its value replaced, whatever the value is.
2. Any known secret value (from Settings) is scrubbed from every string in the
   event, so a secret that slips into a message or exception text is still hidden.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any

import structlog

REDACTED = "***"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|login|webhook|credential)",
    re.IGNORECASE,
)


class SecretScrubber:
    """structlog processor that hides sensitive keys and known secret values."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Longest first so a secret containing another secret is fully hidden.
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def __call__(
        self, _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        for key in event_dict:  # only values change, never the keys
            event_dict[key] = self._clean(key, event_dict[key])
        return event_dict

    def _clean(self, key: str, value: Any) -> Any:
        if _SENSITIVE_KEY.search(key):
            return REDACTED
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, dict):
            return {k: self._clean(str(k), v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self._clean("", v) for v in value)
        return value

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text


def configure_logging(
    level: str = "INFO", json: bool = False, secrets: Iterable[str] = ()
) -> None:
    """Configure structlog once at startup. Call with Settings.secret_values()."""
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level.upper())
    renderer: Any = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            SecretScrubber(secrets),  # must run after exceptions are rendered to text
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
