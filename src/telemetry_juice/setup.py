"""Provider setup — the one call a service makes at startup."""

from __future__ import annotations

from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource

from .config import TelemetryConfig
from .trace_context import PinnedIdGenerator

_config: TelemetryConfig | None = None


def configure(config: TelemetryConfig) -> TelemetryConfig:
    """Install global tracer and meter providers.

    Call once, as early in startup as possible and before any instrumentation
    helper. Safe to call when telemetry is disabled — it records the config
    and returns without touching the global providers, leaving OpenTelemetry's
    own no-op implementations in place.

    Args:
        config: Resolved settings, usually from
            :meth:`TelemetryConfig.from_env`.

    Returns:
        The config, so callers can branch on ``.enabled`` without
        re-reading the environment.

    Example:
        >>> from telemetry_juice import TelemetryConfig, configure
        >>> cfg = configure(TelemetryConfig.from_env("familiar-api"))
        >>> cfg.enabled
        False
    """
    global _config
    _config = config

    if not config.enabled:
        return config

    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = _build_resource(config)
    span_exporter, metric_exporter = _build_exporters(config)

    # PinnedIdGenerator so that work with an identity of its own - a batch
    # run, a workflow - can emit a trace under that id. Random otherwise;
    # see monkeypants_telemetry.pinned_trace_id.
    tracer_provider = TracerProvider(
        resource=resource, id_generator=PinnedIdGenerator()
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=config.metric_interval_ms,
                )
            ],
        )
    )
    return config


def _build_exporters(config: TelemetryConfig) -> tuple[Any, Any]:
    """The span and metric exporters for the configured protocol.

    Imported lazily so that a disabled process never pays for the exporter
    machinery, and so an import error in the transport stack cannot break a
    laptop run.
    """
    if config.protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HTTPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPSpanExporter,
        )

        # The HTTP exporters use an explicit endpoint verbatim; only the
        # environment variable gets the signal path appended for you.
        base = (config.endpoint or "").rstrip("/")
        return (
            HTTPSpanExporter(endpoint=f"{base}/v1/traces"),
            HTTPMetricExporter(endpoint=f"{base}/v1/metrics"),
        )

    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )

    return (
        OTLPSpanExporter(endpoint=config.endpoint),
        OTLPMetricExporter(endpoint=config.endpoint),
    )


def _build_resource(config: TelemetryConfig) -> Resource:
    """Assemble the resource attributes the contract requires."""
    attributes: dict[str, str] = {"service.name": config.service_name}
    if config.namespace:
        attributes["service.namespace"] = config.namespace
    if config.environment:
        attributes["deployment.environment"] = config.environment
    return Resource.create(attributes)


def current_config() -> TelemetryConfig | None:
    """The config passed to the last :func:`configure` call, if any."""
    return _config
