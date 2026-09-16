"""Reading and moving trace context.

Everything here works whether or not telemetry is enabled — with no provider
installed the SDK returns invalid spans, and these helpers degrade to
returning ``None`` and empty dicts rather than raising.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract, inject


def get_trace_id() -> str | None:
    """The current trace ID as 32 hex characters.

    Returns:
        The trace ID, or ``None`` outside a valid trace context.
    """
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def inject_context() -> dict[str, str]:
    """Serialise the current context into W3C headers.

    Use when handing work to something that carries its own headers — a
    Temporal workflow start, a queue message, an outbound request a library
    does not instrument for you.

    Returns:
        A dict with ``traceparent`` (and ``tracestate`` where relevant),
        empty if there is no active trace.
    """
    headers: dict[str, str] = {}
    inject(headers)
    return headers


class HeaderCarrier(Mapping[str, str]):
    """Adapts a bytes-or-str header mapping to the propagator's getter.

    Temporal hands headers back as bytes; most queues do the same. This
    normalises without copying the whole mapping.
    """

    def __init__(self, headers: Mapping[str, Any]) -> None:
        self._headers = headers

    def __getitem__(self, key: str) -> str:
        value = self._headers.get(key)
        if value is None:
            raise KeyError(key)
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def __iter__(self) -> Any:
        return iter(self._headers)

    def __len__(self) -> int:
        return len(self._headers)


def extract_context(headers: Mapping[str, Any]) -> Any:
    """Rebuild a context from inbound headers.

    Args:
        headers: Whatever the transport delivered; values may be bytes.

    Returns:
        A context suitable for ``start_as_current_span(context=...)``.
    """
    return extract(HeaderCarrier(headers))
