"""Where the telemetry settings come from, and what happens when they don't.

The single most important behaviour in this package: if no OTLP endpoint is
configured, everything is a no-op. A project must run identically on a laptop
with no platform, on a box where LGTM happens to be down, and on the shed box
in full. That property is what lets projects depend on the contract without
depending on the platform.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Protocol = Literal["grpc", "http/protobuf"]


@dataclass(frozen=True)
class TelemetryConfig:
    """Resolved telemetry settings.

    Attributes:
        service_name: This process's name, e.g. ``"familiar-api"``. Becomes
            ``service.name``, and the ``service`` log label should match it.
        endpoint: OTLP endpoint, with its scheme: ``http://`` is
            plaintext, ``https://`` is TLS, and ``OTEL_EXPORTER_OTLP_INSECURE``
            overrides either. ``None`` disables telemetry entirely.
        namespace: The solution this process belongs to, e.g.
            ``"demo-solution"``. Becomes ``service.namespace``. The consumer
            collector overrides this anyway, so it only matters when a
            process exports directly.
        environment: Where it is deployed, e.g. ``"production"``. Becomes
            ``deployment.environment``.
        protocol: OTLP transport, ``"grpc"`` or ``"http/protobuf"``. The
            latter needs the ``http`` extra; ``endpoint`` is then the base
            URL, and ``/v1/traces`` and ``/v1/metrics`` are appended.
        metric_interval_ms: How often metrics are flushed.
    """

    service_name: str
    endpoint: str | None = None
    namespace: str | None = None
    environment: str | None = None
    protocol: Protocol = "grpc"
    metric_interval_ms: int = 60_000

    @property
    def enabled(self) -> bool:
        """Whether telemetry will actually be exported."""
        return bool(self.endpoint)

    @classmethod
    def from_env(
        cls,
        service_name: str | None = None,
        **overrides: object,
    ) -> TelemetryConfig:
        """Build config from the standard OTel environment variables.

        Reads ``OTEL_SERVICE_NAME``, ``OTEL_EXPORTER_OTLP_ENDPOINT``,
        ``SOLUTION`` and ``ENVIRONMENT`` — the same four the consumer sidecar
        template sets, so a project that copies the template gets a working
        config without naming anything twice. ``OTEL_EXPORTER_OTLP_PROTOCOL``
        is read too, defaulting to ``grpc``.

        ``CLIENT`` is deliberately not read. It is a Loki label, set by the
        sidecar, and OpenTelemetry has no resource attribute that means it —
        inventing one here would put a fifth thing in the contract to serve
        a value that is constant within one deployment.

        Args:
            service_name: Overrides ``OTEL_SERVICE_NAME``. Required if that
                variable is unset.
            **overrides: Any field to force, bypassing the environment.

        Returns:
            A resolved config. Disabled if no endpoint was found.

        Raises:
            ValueError: If no service name is available from either source,
                or the protocol is not one this package can export.
        """
        name = service_name or os.getenv("OTEL_SERVICE_NAME")
        if not name:
            raise ValueError(
                "no service name: pass service_name= or set OTEL_SERVICE_NAME"
            )

        protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL") or "grpc"
        if protocol not in ("grpc", "http/protobuf"):
            raise ValueError(
                f"unsupported OTEL_EXPORTER_OTLP_PROTOCOL {protocol!r}: "
                "use 'grpc' or 'http/protobuf'"
            )

        resolved: dict[str, object] = {
            "service_name": name,
            "endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            "namespace": os.getenv("SOLUTION") or None,
            "environment": os.getenv("ENVIRONMENT") or None,
            "protocol": protocol,
        }
        resolved.update(overrides)
        return cls(**resolved)  # type: ignore[arg-type]
