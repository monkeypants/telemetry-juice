"""The client half of the platform telemetry contract.

A project that installs this package and calls :func:`configure` at startup
has met the contract. It does not learn where its telemetry goes, whether a
platform exists, or that any other project is running on the same box.

.. code-block:: python

    from telemetry_juice import TelemetryConfig, configure
    from telemetry_juice.integrations.asgi import instrument_fastapi

    configure(TelemetryConfig.from_env("familiar-api"))
    instrument_fastapi(app, excluded_urls="/health,/ready")

With ``OTEL_EXPORTER_OTLP_ENDPOINT`` unset — a laptop, a test run, a box
where the platform is down — every call above is a no-op and the service
behaves identically. That is deliberate, and it is what makes the dependency
one-directional.

See ``docs/contract.rst`` in the platform repo for the obligations this
discharges and the two it cannot (log shape and container labels).
"""

from .config import TelemetryConfig
from .logging import ContractFormatter, add_trace_id
from .metrics import get_meter
from .setup import configure, current_config
from .trace_context import (
    PinnedIdGenerator,
    extract_context,
    get_span_id,
    get_trace_id,
    inject_context,
    pinned_trace_id,
)

__all__ = [
    "ContractFormatter",
    "PinnedIdGenerator",
    "TelemetryConfig",
    "add_trace_id",
    "configure",
    "current_config",
    "extract_context",
    "get_meter",
    "get_span_id",
    "get_trace_id",
    "inject_context",
    "pinned_trace_id",
]

__version__ = "0.1.0"
