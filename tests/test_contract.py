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

import pytest

from monkeypants_telemetry import (
    ContractFormatter,
    TelemetryConfig,
    add_trace_id,
    configure,
    get_meter,
    get_trace_id,
    inject_context,
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
            "import sys; import monkeypants_telemetry; "
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

    ``pyproject.toml`` declaring a ``psycopg`` extra, and the README listing
    it in the table of what each extra gives you, is a promise. It was not
    kept: the extra and the documentation existed and
    ``instrument_psycopg`` did not, so the first project to install
    ``monkeypants-telemetry[psycopg]`` got exactly what it asked for and
    then an ImportError reaching for it.

    Nothing caught that, because every test here imports what it knows is
    there. This one goes the other way: it reads what the package advertises
    and checks the code answers.
    """

    #: Extras that promise a client auto-instrumentation entry point. The
    #: others are different shapes on purpose — ``fastapi`` lives in
    #: ``integrations.asgi``, ``temporal`` exports an interceptor class, and
    #: ``structlog`` adds no code at all because ``add_trace_id`` is a plain
    #: processor that needs no library.
    CLIENT_EXTRAS = ("redis", "httpx", "sqlalchemy", "psycopg")

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

    @pytest.mark.parametrize("extra", CLIENT_EXTRAS)
    def test_each_client_extra_has_its_function(self, extra: str) -> None:
        """Installing the extra must give you something to call.

        Checked by attribute rather than by calling: the import of the
        instrumentation library is inside each function, so this passes
        without any of the optional dependencies installed — which is the
        point, since no environment has all of them.
        """
        from monkeypants_telemetry.integrations import clients

        name = f"instrument_{extra}"
        assert hasattr(clients, name), (
            f"pyproject.toml declares the {extra!r} extra and the README "
            f"promises it, but integrations.clients has no {name}(). A "
            "project that installs the extra has no way to use it."
        )
