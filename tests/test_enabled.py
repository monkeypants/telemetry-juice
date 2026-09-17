"""What the contract promises once something is collecting.

The disabled path proves a project can adopt this package without the
platform. These prove the other half: that with a provider installed, the
trace ID actually reaches the logs and survives a hop through headers.
"""

from __future__ import annotations

import json
import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from telemetry_juice import (
    ContractFormatter,
    TelemetryConfig,
    add_trace_id,
    extract_context,
    get_span_id,
    get_trace_id,
    inject_context,
)
from telemetry_juice.setup import _build_exporters, _build_resource


def _record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("app", logging.INFO, __file__, 1, msg, (), None)


class TestTraceIdReachesLogs:
    def test_trace_id_is_the_current_span_trace(self, tracer: trace.Tracer) -> None:
        with tracer.start_as_current_span("work") as span:
            expected = format(span.get_span_context().trace_id, "032x")
            assert get_trace_id() == expected

    def test_formatter_stamps_trace_id_inside_a_span(
        self, tracer: trace.Tracer
    ) -> None:
        with tracer.start_as_current_span("work"):
            payload = json.loads(ContractFormatter().format(_record()))
            assert payload["trace_id"] == get_trace_id()

    def test_formatter_stamps_span_id_inside_a_span(self, tracer: trace.Tracer) -> None:
        """The span ID narrows a log line to one operation within the trace."""
        with tracer.start_as_current_span("work") as span:
            payload = json.loads(ContractFormatter().format(_record()))
            assert payload["span_id"] == format(span.get_span_context().span_id, "016x")

    def test_structlog_processor_stamps_trace_id_inside_a_span(
        self, tracer: trace.Tracer
    ) -> None:
        with tracer.start_as_current_span("work"):
            event = add_trace_id(None, "info", {"event": "hello"})
            assert event["trace_id"] == get_trace_id()
            assert event["span_id"] == get_span_id()


class TestContextCrossesAHop:
    """A span started from injected headers belongs to the caller's trace."""

    def test_injected_headers_carry_traceparent(self, tracer: trace.Tracer) -> None:
        with tracer.start_as_current_span("caller"):
            headers = inject_context()
        assert "traceparent" in headers

    def test_round_trip_joins_the_callers_trace(
        self, tracer: trace.Tracer, spans: InMemorySpanExporter
    ) -> None:
        with tracer.start_as_current_span("caller"):
            headers = inject_context()

        with tracer.start_as_current_span("callee", context=extract_context(headers)):
            pass

        caller, callee = spans.get_finished_spans()
        assert callee.context.trace_id == caller.context.trace_id
        assert callee.parent is not None
        assert callee.parent.span_id == caller.context.span_id

    def test_round_trip_survives_bytes_headers(
        self, tracer: trace.Tracer, spans: InMemorySpanExporter
    ) -> None:
        """Queues commonly deliver header values as bytes."""
        with tracer.start_as_current_span("caller"):
            headers = {k: v.encode() for k, v in inject_context().items()}

        with tracer.start_as_current_span("callee", context=extract_context(headers)):
            pass

        caller, callee = spans.get_finished_spans()
        assert callee.context.trace_id == caller.context.trace_id


class TestExporters:
    """The transport follows the protocol, and TLS follows the scheme."""

    def test_grpc_is_the_default(self) -> None:
        span_exporter, _ = _build_exporters(
            TelemetryConfig("svc", endpoint="http://otel:4317")
        )
        assert "proto.grpc" in type(span_exporter).__module__

    def test_http_endpoint_scheme_is_plaintext(self) -> None:
        span_exporter, _ = _build_exporters(
            TelemetryConfig("svc", endpoint="http://otel:4317")
        )
        assert span_exporter._insecure is True

    def test_https_endpoint_scheme_is_tls(self) -> None:
        span_exporter, _ = _build_exporters(
            TelemetryConfig("svc", endpoint="https://otel:4317")
        )
        assert span_exporter._insecure is False

    def test_http_protobuf_appends_signal_paths(self) -> None:
        span_exporter, metric_exporter = _build_exporters(
            TelemetryConfig(
                "svc", endpoint="https://otel:4318/", protocol="http/protobuf"
            )
        )
        assert "proto.http" in type(span_exporter).__module__
        assert span_exporter._endpoint == "https://otel:4318/v1/traces"
        assert metric_exporter._endpoint == "https://otel:4318/v1/metrics"


class TestResource:
    """What every span and metric says about where it came from."""

    def test_identity_attributes(self) -> None:
        resource = _build_resource(
            TelemetryConfig(
                "familiar-api", namespace="demo-solution", environment="production"
            )
        )
        assert resource.attributes["service.name"] == "familiar-api"
        assert resource.attributes["service.namespace"] == "demo-solution"
        assert resource.attributes["deployment.environment.name"] == "production"

    def test_deprecated_environment_name_is_still_emitted(self) -> None:
        resource = _build_resource(TelemetryConfig("svc", environment="production"))
        assert resource.attributes["deployment.environment"] == "production"

    def test_resource_attributes_variable_is_merged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "team=platform,service.name=x")
        resource = _build_resource(TelemetryConfig("svc"))
        assert resource.attributes["team"] == "platform"
        assert resource.attributes["service.name"] == "svc"
