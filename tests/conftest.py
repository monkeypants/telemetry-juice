"""Shared fixtures.

OpenTelemetry lets a process set its global tracer provider exactly once, so
the recording provider is installed for the whole session and each test only
clears what it captured.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Spans finished during the test, recorded in memory."""
    _exporter.clear()
    yield _exporter
    _exporter.clear()


@pytest.fixture
def tracer() -> trace.Tracer:
    return trace.get_tracer("tests")
