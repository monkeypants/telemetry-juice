"""httpx2 instrumentation. Requires the ``httpx2`` extra.

``httpx2`` is a fork, and OpenTelemetry's httpx instrumentation patches
``httpx``: a project using the fork gets no client spans and, worse, no
trace context on the way out, so whatever it called starts a trace of its
own. The first consumer to hit this had its model calls invisible — the
slowest and most expensive thing it did — and found out by reading a trace
that stopped at the activity.

This is deliberately small: a transport that wraps another transport. That
is the seam httpx2 already has, so nothing here depends on the fork's
internals beyond the two attributes :func:`instrument_httpx2` reaches for.

.. code-block:: python

    from telemetry_juice.integrations.httpx2 import instrument_httpx2

    instrument_httpx2()  # every client built afterwards

or, where a client is built in one place and patching is more than is
wanted:

.. code-block:: python

    client = httpx2.Client(transport=TracingTransport())
"""

from __future__ import annotations

from typing import Any

import httpx2
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from ..trace_context import inject_context

_TRACER_NAME = "telemetry_juice.httpx2"


class TracingTransport(httpx2.BaseTransport):
    """Wraps an httpx2 transport: a span per request, context on the way out.

    Args:
        transport: The transport to wrap. Omit to wrap a default
            ``httpx2.HTTPTransport``.
    """

    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport or httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        tracer = trace.get_tracer(_TRACER_NAME)
        url = request.url
        # The semantic conventions' name for a client span is the method
        # alone: a URL carrying an id per request would make every span its
        # own name, which is what turns a trace store into a list.
        with tracer.start_as_current_span(
            request.method,
            kind=SpanKind.CLIENT,
            attributes={
                "http.request.method": request.method,
                "url.full": str(url),
                "server.address": url.host,
            },
        ) as span:
            if url.port is not None:
                span.set_attribute("server.port", url.port)
            # So whatever answers can continue this trace rather than
            # beginning one. Empty when telemetry is disabled.
            request.headers.update(inject_context())
            try:
                response = self._transport.handle_request(request)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__qualname__)
                raise
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 400:
                # A 404 is a fact about the request rather than a fault in
                # the client, but a caller reading a trace wants the failed
                # calls to be the ones that stand out.
                span.set_attribute("error.type", str(response.status_code))
                span.set_status(Status(StatusCode.ERROR))
            return response

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> TracingTransport:
        self._transport.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        self._transport.__exit__(*args)


def instrument_httpx2() -> None:
    """Trace every ``httpx2.Client`` built after this call.

    Idempotent: calling it twice does not wrap twice, which matters because
    a process that configures telemetry in two places would otherwise get
    two spans per request.
    """
    client: Any = httpx2.Client
    if getattr(client, "_telemetry_juice_instrumented", False):
        return

    original = client.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        self._transport = TracingTransport(self._transport)
        self._mounts = {
            pattern: TracingTransport(mounted) if mounted is not None else None
            for pattern, mounted in self._mounts.items()
        }

    client.__init__ = __init__
    client._telemetry_juice_instrumented = True
