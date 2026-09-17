"""Metric helpers.

Thin by design. The interesting metrics on this platform are generated from
spans by Tempo's metrics generator, not hand-written — so a project usually
needs nothing here at all.
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import Meter


def get_meter(name: str) -> Meter:
    """A meter for creating instruments.

    Returns a working no-op meter when telemetry is disabled, so call sites
    need no guard.

    Args:
        name: Usually the service name, or the module creating the metric.

    Returns:
        A meter. Instruments created from it are safe to use unconditionally.

    Example:
        >>> meter = get_meter("familiar-api")
        >>> counter = meter.create_counter("requests_total")
        >>> counter.add(1, {"method": "GET"})
    """
    return metrics.get_meter(name)
