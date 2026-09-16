"""The client half of the platform telemetry contract.

A project that installs this package and calls :func:`configure` at startup
has met the contract. It does not learn where its telemetry goes, whether a
platform exists, or that any other project is running on the same box.

.. code-block:: python

    from monkeypants_telemetry import TelemetryConfig, configure
    from monkeypants_telemetry.integrations.asgi import instrument_fastapi

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
    extract_context,
    get_trace_id,
    inject_context,
)

__all__ = [
    "ContractFormatter",
    "TelemetryConfig",
    "add_trace_id",
    "configure",
    "current_config",
    "extract_context",
    "get_meter",
    "get_trace_id",
    "inject_context",
]

__version__ = "0.1.0"
