"""What the contract actually promises.

These tests exist to defend one property: a project can adopt this package
without adopting the platform. If they pass, a service runs identically on a
laptop with nothing configured and on the shed box with LGTM behind it.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid

import pytest
from opentelemetry import trace

from telemetry_juice import (
    ContractFormatter,
    PinnedIdGenerator,
    TelemetryConfig,
    add_trace_id,
    configure,
    get_meter,
    get_trace_id,
    inject_context,
    pinned_trace_id,
)


class TestDisabledByDefault:
    """No endpoint means no telemetry, and no failure either."""

    def test_config_without_endpoint_is_disabled(self) -> None:
        config = TelemetryConfig(service_name="svc")
        assert config.enabled is False

    def test_configure_is_a_noop_when_disabled(self) -> None:
        config = configure(TelemetryConfig(service_name="svc"))
        assert config.enabled is False

    def test_instruments_still_work_when_disabled(self) -> None:
        """The point: call sites need no `if telemetry_enabled` guard."""
        configure(TelemetryConfig(service_name="svc"))
        counter = get_meter("svc").create_counter("requests_total")
        counter.add(1, {"method": "GET"})  # must not raise

    def test_trace_id_is_none_outside_a_trace(self) -> None:
        assert get_trace_id() is None

    def test_inject_context_yields_empty_headers_when_disabled(self) -> None:
        assert inject_context() == {}


class TestConfigFromEnv:
    """The four variables the consumer sidecar template already sets.

    `SOLUTION` and `ENVIRONMENT`, not `PROJECT` and `INSTANCE`: the latter
    answered two of the three identity questions and left the third to be
    inferred. See contract §3.
    """

    def test_reads_the_standard_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OTEL_SERVICE_NAME", "familiar-api")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4317")
        monkeypatch.setenv("SOLUTION", "demo-solution")
        monkeypatch.setenv("ENVIRONMENT", "production")

        config = TelemetryConfig.from_env()

        assert config.service_name == "familiar-api"
        assert config.namespace == "demo-solution"
        assert config.environment == "production"
        assert config.enabled is True

    def test_the_old_names_are_not_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`INSTANCE` used to become `deployment.environment`.

        It is not a synonym for `ENVIRONMENT` and must not quietly keep
        working: a project that sets only the old names should get no
        resource attributes rather than the wrong ones.
        """
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4317")
        monkeypatch.setenv("PROJECT", "demo-solution")
        monkeypatch.setenv("INSTANCE", "alpha")

        config = TelemetryConfig.from_env("familiar-api")

        assert config.namespace is None
        assert config.environment is None

    def test_explicit_service_name_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
        assert TelemetryConfig.from_env("explicit").service_name == "explicit"

    def test_empty_endpoint_is_treated_as_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Compose writes an empty string for an unset variable; that is off."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        assert TelemetryConfig.from_env("svc").enabled is False

    def test_protocol_defaults_to_grpc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)
        assert TelemetryConfig.from_env("svc").protocol == "grpc"

    def test_http_protocol_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
        assert TelemetryConfig.from_env("svc").protocol == "http/protobuf"

    def test_unknown_protocol_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``http/json`` is in the spec but has no Python exporter."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/json")
        with pytest.raises(ValueError, match="unsupported"):
            TelemetryConfig.from_env("svc")

    def test_missing_service_name_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anonymous telemetry is worse than none — it pollutes the shared index."""
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        with pytest.raises(ValueError, match="no service name"):
            TelemetryConfig.from_env()


class TestLogShape:
    """Vector's parser and Grafana's derived field both depend on this shape."""

    def test_formatter_emits_the_contract_fields(self) -> None:
        record = logging.LogRecord(
            name="app.thing",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="disk %s%% full",
            args=(91,),
            exc_info=None,
        )

        payload = json.loads(ContractFormatter().format(record))

        assert payload["level"] == "warning"
        assert payload["msg"] == "disk 91% full"
        assert payload["logger"] == "app.thing"
        assert "timestamp" in payload

    def test_timestamp_orders_lines_within_a_second(self) -> None:
        """Whole-second stamps leave a burst of lines with no order."""
        record = logging.LogRecord("app", logging.INFO, __file__, 1, "x", (), None)
        record.created = 1_700_000_000.123

        payload = json.loads(ContractFormatter().format(record))

        assert payload["timestamp"] == "2023-11-14T22:13:20.123+00:00"

    def test_extra_fields_survive(self) -> None:
        record = logging.LogRecord(
            name="app",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="done",
            args=(),
            exc_info=None,
        )
        record.__dict__["order_id"] = "abc123"

        payload = json.loads(ContractFormatter().format(record))

        assert payload["order_id"] == "abc123"

    def test_no_trace_id_key_outside_a_trace(self) -> None:
        """A null trace_id would match Grafana's regex and link nowhere."""
        record = logging.LogRecord(
            name="app",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert "trace_id" not in json.loads(ContractFormatter().format(record))

    def test_structlog_processor_adds_nothing_outside_a_trace(self) -> None:
        assert add_trace_id(None, "info", {"event": "hello"}) == {"event": "hello"}


class TestIntegrationsAreOptional:
    """A Django project must not need temporalio installed to use this."""

    def test_package_root_imports_no_framework(self) -> None:
        """Run in a subprocess: sys.modules in-process is already polluted by
        collection, so only a clean interpreter can answer this honestly."""
        probe = (
            "import sys; import telemetry_juice; "
            "leaked = [m for m in ('temporalio', 'fastapi', 'django') "
            "if m in sys.modules]; "
            "print(','.join(leaked))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "", (
            f"importing the package root pulled in {result.stdout.strip()}; "
            "integrations must stay lazy"
        )


class TestEveryAdvertisedIntegrationExists:
    """An extra a project can install must name a function it can call.

    A declared extra is a promise: installing ``telemetry-juice[psycopg]``
    should give you ``instrument_psycopg``. Tests that import what they know
    exists cannot catch a broken promise, so this one reads what the package
    advertises and checks the code answers.
    """

    #: Extras that promise a client auto-instrumentation entry point. The
    #: others are different shapes on purpose — ``fastapi`` lives in
    #: ``integrations.asgi``, ``temporal`` exports an interceptor class, and
    #: ``structlog`` adds no code at all because ``add_trace_id`` is a plain
    #: processor that needs no library.
    CLIENT_EXTRAS = ("redis", "httpx", "sqlalchemy", "psycopg")

    #: Extras whose entry point is a module of its own, and the attribute
    #: that module must carry. ``httpx2`` is a fork the ``httpx``
    #: instrumentation does not cover, so this package implements it.
    MODULE_EXTRAS = {
        "fastapi": ("asgi", "instrument_fastapi"),
        "httpx2": ("httpx2", "instrument_httpx2"),
        "temporal": ("temporal", "TracingInterceptor"),
    }

    def _declared_extras(self) -> set[str]:
        import pathlib
        import tomllib

        root = pathlib.Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text())
        return set(data["project"]["optional-dependencies"])

    def test_client_extras_are_all_declared(self) -> None:
        """The list this test checks against is really in the manifest."""
        missing = sorted(set(self.CLIENT_EXTRAS) - self._declared_extras())
        assert not missing, (
            f"{missing} are checked here but not declared as extras; "
            "this test is guarding something that does not exist"
        )

    @pytest.mark.parametrize("extra", sorted(MODULE_EXTRAS))
    def test_each_module_extra_is_declared_and_answers(self, extra: str) -> None:
        import importlib

        assert extra in self._declared_extras(), extra
        module_name, attribute = self.MODULE_EXTRAS[extra]
        module = importlib.import_module(f"telemetry_juice.integrations.{module_name}")
        assert hasattr(module, attribute), (
            f"the {extra!r} extra promises integrations.{module_name}.{attribute}"
        )

    @pytest.mark.parametrize("extra", CLIENT_EXTRAS)
    def test_each_client_extra_has_its_function(self, extra: str) -> None:
        """Installing the extra must give you something to call.

        Checked by attribute rather than by calling: the import of the
        instrumentation library is inside each function, so this passes
        without any of the optional dependencies installed — which is the
        point, since no environment has all of them.
        """
        from telemetry_juice.integrations import clients

        name = f"instrument_{extra}"
        assert hasattr(clients, name), (
            f"pyproject.toml declares the {extra!r} extra and the README "
            f"promises it, but integrations.clients has no {name}(). A "
            "project that installs the extra has no way to use it."
        )


class TestPinningATraceToADomainId:
    """Work that already has an identity can emit a trace under it.

    The case this exists for: a batch runner whose runs are identified by
    UUID, logging while it works and emitting the trace only once the run
    has finished. Without this the logs and the trace cannot be joined,
    because the trace id did not exist while the logs were being written.
    """

    def test_a_uuid_becomes_the_trace_id(self) -> None:
        generator = PinnedIdGenerator()
        run_id = "fef5abac-7308-4ba7-9cc0-c79b2d727203"
        with pinned_trace_id(run_id):
            assert generator.generate_trace_id() == int(run_id.replace("-", ""), 16)

    def test_bare_hex_is_accepted_too(self) -> None:
        generator = PinnedIdGenerator()
        with pinned_trace_id("fef5abac73084ba79cc0c79b2d727203"):
            assert format(generator.generate_trace_id(), "032x") == (
                "fef5abac73084ba79cc0c79b2d727203"
            )

    def test_a_uuid_object_is_accepted(self) -> None:
        generator = PinnedIdGenerator()
        value = uuid.UUID("fef5abac-7308-4ba7-9cc0-c79b2d727203")
        with pinned_trace_id(value):
            assert generator.generate_trace_id() == int(value)

    def test_ids_are_random_again_outside_the_block(self) -> None:
        """The generator is installed always, so this is the common path."""
        generator = PinnedIdGenerator()
        with pinned_trace_id("fef5abac-7308-4ba7-9cc0-c79b2d727203"):
            pass
        assert len({generator.generate_trace_id() for _ in range(20)}) == 20

    def test_nesting_restores_the_outer_pin(self) -> None:
        generator = PinnedIdGenerator()
        outer = "11111111-1111-4111-8111-111111111111"
        inner = "22222222-2222-4222-8222-222222222222"
        with pinned_trace_id(outer):
            with pinned_trace_id(inner):
                assert generator.generate_trace_id() == int(inner.replace("-", ""), 16)
            assert generator.generate_trace_id() == int(outer.replace("-", ""), 16)

    def test_the_pin_is_released_even_when_the_body_raises(self) -> None:
        generator = PinnedIdGenerator()
        pinned = int("fef5abac73084ba79cc0c79b2d727203", 16)
        with (
            pytest.raises(RuntimeError),
            pinned_trace_id("fef5abac-7308-4ba7-9cc0-c79b2d727203"),
        ):
            raise RuntimeError("boom")
        assert generator.generate_trace_id() != pinned

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-uuid",
            "",
            "abc",
            "00000000-0000-0000-0000-000000000000",  # the invalid trace id
            0,
        ],
    )
    def test_a_value_that_is_not_a_trace_id_is_refused(self, bad: object) -> None:
        """Loudly, at the pin, rather than as an unreadable trace later."""
        with pytest.raises(ValueError), pinned_trace_id(bad):  # type: ignore[arg-type]
            pass

    def test_only_root_spans_are_pinned(self) -> None:
        """A child inherits its parent's trace id, pin or no pin.

        This is what makes the generator safe to install unconditionally:
        it can only ever affect a span that would have started a new trace.
        """
        from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

        provider = TracerProvider(id_generator=PinnedIdGenerator())
        tracer = provider.get_tracer("test")
        run_id = "fef5abac-7308-4ba7-9cc0-c79b2d727203"
        expected = int(run_id.replace("-", ""), 16)

        with pinned_trace_id(run_id):
            root = tracer.start_span("run")
            assert root.get_span_context().trace_id == expected
            with trace.use_span(root, end_on_exit=False):
                child = tracer.start_span("step")  # noqa: SIM117
            assert child.get_span_context().trace_id == expected
            assert isinstance(child, ReadableSpan)
            assert child.parent is not None
            assert child.parent.span_id == root.get_span_context().span_id

    def test_the_pinned_span_is_a_root_with_no_parent(self) -> None:
        """The whole point of doing this in the generator.

        Carrying the id on a synthetic parent context instead leaves the
        run span parented to a span that was never sent, and Tempo reports
        the trace as `<root span not yet received>` — nameless in search.
        """
        from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

        provider = TracerProvider(id_generator=PinnedIdGenerator())
        tracer = provider.get_tracer("test")
        with pinned_trace_id("fef5abac-7308-4ba7-9cc0-c79b2d727203"):
            span = tracer.start_span("run")
        assert isinstance(span, ReadableSpan)
        assert span.parent is None
