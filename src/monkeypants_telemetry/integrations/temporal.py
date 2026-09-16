"""Temporal tracing. Requires the ``temporal`` extra.

Temporal is the one place trace context does not propagate on its own: a
workflow runs later, elsewhere, and its only link to the caller is the header
map. This interceptor carries the context across that gap so a request span
and the workflow it started land in the same trace.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from ..trace_context import extract_context

_TRACER_NAME = "monkeypants.temporal"


class _WorkflowInbound(WorkflowInboundInterceptor):
    """Opens a server span per workflow execution, continuing the caller's trace."""

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        tracer = trace.get_tracer(_TRACER_NAME)
        ctx = extract_context(input.headers or {})
        info = workflow.info()

        with tracer.start_as_current_span(
            f"workflow:{info.workflow_type}",
            context=ctx,
            kind=SpanKind.SERVER,
            attributes={
                "temporal.workflow.type": info.workflow_type,
                "temporal.workflow.id": info.workflow_id,
                "temporal.workflow.run_id": info.run_id,
                "temporal.task_queue": info.task_queue,
            },
        ):
            return await self.next.execute_workflow(input)


class _ActivityInbound(ActivityInboundInterceptor):
    """Opens a child span per activity, inheriting the workflow's context."""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        tracer = trace.get_tracer(_TRACER_NAME)
        info = activity.info()

        # The workflow fields are optional on ActivityInfo — a local activity
        # has no owning workflow to report. Omit them rather than recording
        # the string "None", which would be indistinguishable from a real id
        # in TraceQL.
        attributes: dict[str, str | int] = {
            "temporal.activity.type": info.activity_type,
            "temporal.activity.id": info.activity_id,
            "temporal.attempt": info.attempt,
        }
        if info.workflow_id is not None:
            attributes["temporal.workflow.id"] = info.workflow_id
        if info.workflow_run_id is not None:
            attributes["temporal.workflow.run_id"] = info.workflow_run_id

        with tracer.start_as_current_span(
            f"activity:{info.activity_type}",
            kind=SpanKind.INTERNAL,
            attributes=attributes,
        ):
            return await self.next.execute_activity(input)


class TracingInterceptor(Interceptor):
    """Worker interceptor producing spans for workflows and activities.

    Pair it with
    :func:`~monkeypants_telemetry.trace_context.inject_context` on the
    starting side — the interceptor can only continue a trace whose context
    actually arrived in the headers.

    Example:
        >>> from monkeypants_telemetry.integrations.temporal import (
        ...     TracingInterceptor,
        ... )
        >>> # worker = Worker(client, task_queue="q",
        >>> #                 interceptors=[TracingInterceptor()], ...)
        >>> TracingInterceptor().__class__.__name__
        'TracingInterceptor'
    """

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        return _ActivityInbound(next)

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        return _WorkflowInbound
