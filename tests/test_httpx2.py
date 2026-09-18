"""What the httpx2 transport promises.

OpenTelemetry's httpx instrumentation patches ``httpx``, and a project on
the fork gets nothing from it: no client spans, and no trace context on the
way out, so whatever it calls starts a trace of its own. These tests hold
both halves, because the second is the one that fails silently — two valid
traces that never say they are about the same thing.
"""

from __future__ import annotations

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from telemetry_juice.integrations.httpx2 import (
    TracingTransport,
    instrument_httpx2,
)


def answering(
    status: int = 200, seen: list[httpx2.Request] | None = None
) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(status, json={})

    return httpx2.MockTransport(handler)


def client(
    status: int = 200, seen: list[httpx2.Request] | None = None
) -> httpx2.Client:
    return httpx2.Client(transport=TracingTransport(answering(status, seen)))


class TestTheCallIsASpan:
    def test_the_span_is_named_for_the_method(
        self, spans: InMemorySpanExporter
    ) -> None:
        client().get("http://forge.test:3000/repos/o/r/pulls/1")

        (span,) = spans.get_finished_spans()
        assert span.name == "GET"
        assert span.attributes is not None
        assert span.attributes["http.request.method"] == "GET"
        assert span.attributes["server.address"] == "forge.test"
        assert span.attributes["server.port"] == 3000
        assert str(span.attributes["url.full"]).endswith("/repos/o/r/pulls/1")

    def test_the_status_is_recorded(self, spans: InMemorySpanExporter) -> None:
        client().get("http://forge.test/x")

        (span,) = spans.get_finished_spans()
        assert (span.attributes or {})["http.response.status_code"] == 200
        assert span.status.status_code is not StatusCode.ERROR

    def test_a_refusal_fails_the_span(self, spans: InMemorySpanExporter) -> None:
        """A rate limit is the interesting call, not the boring one."""
        client(status=429).get("http://forge.test/x")

        (span,) = spans.get_finished_spans()
        assert span.status.status_code is StatusCode.ERROR
        assert (span.attributes or {})["error.type"] == "429"

    def test_a_transport_failure_fails_the_span(
        self, spans: InMemorySpanExporter
    ) -> None:
        def explode(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("no route to host")

        broken = httpx2.Client(
            transport=TracingTransport(httpx2.MockTransport(explode))
        )

        with pytest.raises(httpx2.ConnectError):
            broken.get("http://forge.test/x")

        (span,) = spans.get_finished_spans()
        assert span.status.status_code is StatusCode.ERROR
        assert (span.attributes or {})["error.type"] == "ConnectError"


class TestTheContextTravels:
    """The half that fails silently. Without it the service being called
    starts a trace of its own and nothing anywhere says they are related."""

    def test_the_request_carries_the_traceparent(
        self, tracer: trace.Tracer, spans: InMemorySpanExporter
    ) -> None:
        seen: list[httpx2.Request] = []

        with tracer.start_as_current_span("caller") as caller:
            client(seen=seen).get("http://forge.test/x")
            expected = format(caller.get_span_context().trace_id, "032x")

        (request,) = seen
        assert expected in request.headers["traceparent"]

    def test_the_traceparent_names_this_call_and_not_its_caller(
        self, tracer: trace.Tracer, spans: InMemorySpanExporter
    ) -> None:
        """The callee hangs under the client span, not beside it: the span
        the header names is the request's own."""
        seen: list[httpx2.Request] = []

        with tracer.start_as_current_span("caller"):
            client(seen=seen).get("http://forge.test/x")

        (request,) = seen
        (span,) = [s for s in spans.get_finished_spans() if s.name == "GET"]
        assert format(span.context.span_id, "016x") in (request.headers["traceparent"])


class TestInstrumentingEveryClient:
    def test_a_client_built_afterwards_is_traced(
        self, spans: InMemorySpanExporter
    ) -> None:
        instrument_httpx2()
        httpx2.Client(transport=answering()).get("http://forge.test/x")

        assert [s.name for s in spans.get_finished_spans()] == ["GET"]

    def test_instrumenting_twice_does_not_double_the_spans(
        self, spans: InMemorySpanExporter
    ) -> None:
        """Two calls to configure telemetry would otherwise mean two spans
        per request, and a duration counted twice."""
        instrument_httpx2()
        instrument_httpx2()
        httpx2.Client(transport=answering()).get("http://forge.test/x")

        assert len(spans.get_finished_spans()) == 1
