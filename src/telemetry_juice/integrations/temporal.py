"""Temporal tracing. Requires the ``temporal`` extra.

Temporal is the one place trace context does not propagate on its own: a
workflow runs later, elsewhere, and its only link to the caller is its
headers. Temporal ships an interceptor that carries the context across that
gap and keeps workflow spans replay-safe, so this module re-exports it rather
than maintaining a copy.

Register it on the client, so both the starting side and every worker built
from that client use it:

.. code-block:: python

    client = await Client.connect(
        "localhost:7233", interceptors=[TracingInterceptor()]
    )
    worker = Worker(client, task_queue="q", workflows=[...], activities=[...])

Example:
    >>> from telemetry_juice.integrations.temporal import TracingInterceptor
    >>> TracingInterceptor().header_key
    '_tracer-data'
"""

from __future__ import annotations

from temporalio.contrib.opentelemetry import TracingInterceptor

__all__ = ["TracingInterceptor"]
