"""Reading and moving trace context.

Everything here works whether or not telemetry is enabled — with no provider
installed the SDK returns invalid spans, and these helpers degrade to
returning ``None`` and empty dicts rather than raising.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import SpanContext


def get_trace_id() -> str | None:
    """The current trace ID as 32 hex characters.

    Returns:
        The trace ID, or ``None`` outside a valid trace context.
    """
    ctx = _current_span_context()
    return format(ctx.trace_id, "032x") if ctx else None


def _current_span_context() -> SpanContext | None:
    ctx = trace.get_current_span().get_span_context()
    return ctx if ctx.is_valid else None


def get_span_id() -> str | None:
    """The current span ID as 16 hex characters.

    Returns:
        The span ID, or ``None`` outside a valid trace context.
    """
    ctx = _current_span_context()
    return format(ctx.span_id, "016x") if ctx else None


def inject_context() -> dict[str, str]:
    """Serialise the current context into W3C headers.

    Use when handing work to something that carries its own headers — a
    queue message, or an outbound request a library does not instrument for
    you. Temporal is covered by its interceptor and needs no call here.

    Returns:
        A dict with ``traceparent`` (and ``tracestate`` where relevant),
        empty if there is no active trace.
    """
    headers: dict[str, str] = {}
    inject(headers)
    return headers


class HeaderCarrier(Mapping[str, str]):
    """Adapts a bytes-or-str header mapping to the propagator's getter.

    Most queues hand header values back as bytes. This normalises without
    copying the whole mapping.
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


# --- pinning a trace to an id the domain already owns ---------------------

_pinned: ContextVar[int | None] = ContextVar(
    "monkeypants_telemetry_pinned_trace_id", default=None
)


def _as_trace_id(value: str | int) -> int:
    """Coerce a UUID, 32 hex characters or an int into a trace id.

    Raises:
        ValueError: If it is not 128 bits, or is the all-zero id that
            OpenTelemetry reserves to mean "invalid".
    """
    if isinstance(value, int):
        trace_id = value
    else:
        text = value.strip().replace("-", "")
        if len(text) != 32:
            raise ValueError(f"need 32 hex characters or a UUID, got {value!r}")
        trace_id = int(text, 16)
    if not 0 < trace_id < 1 << 128:
        raise ValueError(f"not a valid trace id: {value!r}")
    return trace_id


@contextmanager
def pinned_trace_id(value: str | uuid.UUID | int) -> Iterator[None]:
    """Make root spans started in this block use ``value`` as their trace id.

    For work whose identity is already established elsewhere — a batch run,
    a workflow, a job — so that logs written during the work can carry that
    identifier and still join the trace, even when the trace is emitted
    afterwards and the work never had a span while it ran.

    Only *root* spans are affected. A span started under a parent inherits
    the parent's trace id, which is what makes this safe to leave installed:
    with nothing pinned, and for every child span, ids are random as usual.

    The value should itself be random — a UUID is the intended case. The
    generator continues to report trace ids as random for the W3C
    ``random-trace-id`` flag, which a UUID satisfies and a counter would not.

    Args:
        value: A UUID, 32 hex characters, or a 128-bit int.

    Raises:
        ValueError: If the value is not a valid, non-zero 128-bit id.

    Example:
        >>> from opentelemetry import trace
        >>> run_id = "fef5abac-7308-4ba7-9cc0-c79b2d727203"
        >>> with pinned_trace_id(run_id):
        ...     span = trace.get_tracer("example").start_span("run")
        ...     span.end()
    """
    raw = str(value) if isinstance(value, uuid.UUID) else value
    token = _pinned.set(_as_trace_id(raw))
    try:
        yield
    finally:
        _pinned.reset(token)


class PinnedIdGenerator(RandomIdGenerator):
    """Random ids, except where :func:`pinned_trace_id` says otherwise.

    Installed by :func:`~monkeypants_telemetry.configure`. It costs one
    context-variable read per root span and changes nothing when unused,
    which is why it is unconditional rather than an option.
    """

    def generate_trace_id(self) -> int:
        pinned = _pinned.get()
        return super().generate_trace_id() if pinned is None else pinned
