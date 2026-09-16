"""The log half of the contract.

Projects do not ship logs. They write structured JSON to stdout carrying
``level``, ``msg`` and — when inside a trace — ``trace_id``; the consumer's
vector sidecar does the rest. These helpers make that shape easy to produce
from either structlog or the standard library, so nothing has to hand-roll it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .trace_context import get_trace_id


def add_trace_id(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor that stamps ``trace_id`` onto every event.

    Place it late in the chain, before the renderer. Outside a trace it adds
    nothing rather than adding a null, which keeps Grafana's derived-field
    regex from matching a useless value.

    Args:
        logger: Unused; part of the structlog processor signature.
        method_name: Unused; part of the structlog processor signature.
        event_dict: The event being built.

    Returns:
        The event dict, with ``trace_id`` added when one is available.

    Example:
        >>> add_trace_id(None, "info", {"event": "hello"})
        {'event': 'hello'}
    """
    trace_id = get_trace_id()
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


class ContractFormatter(logging.Formatter):
    """stdlib formatter emitting the contract's JSON shape.

    For projects not using structlog — a Django app, anything
    with an existing ``logging.config`` — this is the whole integration:

    .. code-block:: python

        LOGGING = {
            "version": 1,
            "formatters": {"contract": {"()": ContractFormatter}},
            "handlers": {
                "stdout": {"class": "logging.StreamHandler",
                           "formatter": "contract"},
            },
            "root": {"handlers": ["stdout"], "level": "INFO"},
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }

        trace_id = get_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed as `extra=` rides along, so callers can add
        # structure without a second logging library.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}
