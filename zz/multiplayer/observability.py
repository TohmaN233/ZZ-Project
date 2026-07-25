from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


_ALLOWED_FIELDS = frozenset({
    "connectionId",
    "errorCode",
    "matchId",
    "messageType",
    "playerId",
    "revision",
    "roomId",
})
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_MAX_EVENT_LENGTH = 64
_MAX_STRING_FIELD_LENGTH = 128


class StructuredEventSink:
    """Emit allowlisted multiplayer lifecycle metadata as one JSON log line."""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(logger, logging.Logger):
            raise TypeError("logger must be a logging.Logger")
        self._logger = logger
        self._now = now or (lambda: datetime.now(timezone.utc))

    def __call__(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        if not isinstance(event, str) or not event or len(event) > _MAX_EVENT_LENGTH:
            raise ValueError("event must contain 1-64 characters")
        unknown = sorted(set(fields) - _ALLOWED_FIELDS)
        if unknown:
            raise ValueError(f"structured multiplayer log has forbidden fields: {', '.join(unknown)}")
        numeric_level = _LEVELS.get(level)
        if numeric_level is None:
            raise ValueError(f"unknown log level {level!r}")
        timestamp = self._now()
        if timestamp.tzinfo is None:
            raise ValueError("structured log clock must return a timezone-aware datetime")
        record: dict[str, Any] = {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "level": level,
            "event": event,
        }
        for key in sorted(fields):
            value = fields[key]
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise TypeError(f"structured log field {key} must be a string, integer or None")
            if isinstance(value, str) and len(value) > _MAX_STRING_FIELD_LENGTH:
                raise ValueError(f"structured log field {key} exceeds 128 characters")
            record[key] = value
        self._logger.log(
            numeric_level,
            json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )


def null_event_sink(_event: str, *, level: str = "INFO", **_fields: Any) -> None:
    if level not in _LEVELS:
        raise ValueError(f"unknown log level {level!r}")
