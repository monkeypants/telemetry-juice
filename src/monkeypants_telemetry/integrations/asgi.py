"""FastAPI / Starlette instrumentation. Requires the ``fastapi`` extra."""

from __future__ import annotations

from typing import Any


def instrument_fastapi(app: Any, **kwargs: Any) -> None:
    """Auto-instrument a FastAPI app.

    Creates a server span per request with method, route and status. Call
    after :func:`~monkeypants_telemetry.setup.configure`; harmless when
    telemetry is disabled, since the spans go to the no-op provider.

    Args:
        app: The FastAPI application.
        **kwargs: Passed through, e.g. ``excluded_urls="/health,/ready"``
            to keep healthcheck spans out of the shared trace store.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, **kwargs)
