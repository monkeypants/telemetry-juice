# telemetry-juice

It seems like I keep doing this, so I wanted to standardise. Lots of things
need telemetry juice.

Provides `telemetry-juice`: OpenTelemetry setup for services that should
not have to know whether anything is collecting.

With no `OTEL_EXPORTER_OTLP_ENDPOINT` set, every call here is a no-op and the
service behaves identically. Not degraded: identical. Counters count into a
no-op meter, spans open against a no-op tracer, and no call site needs a
guard. `tests/test_contract.py` defends that property.

## Install

Not published to an index. Consumers take a submodule and depend on it by
path:

```sh
git submodule add git@github.com:monkeypants/telemetry-juice.git \
    vendor/telemetry-juice
```

```toml
dependencies = ["telemetry-juice[django,psycopg]"]

[tool.uv.sources]
telemetry-juice = { path = "vendor/telemetry-juice" }
```

A git dependency on a private repository needs a credential wherever the build
runs. A submodule does not: the clone happens where the credential already is,
and only files travel. When there is an index, drop the source block and give
the dependency a version.

Base install pulls the OTel API and SDK only. Integrations are extras, so a
Django project never installs `temporalio`.

| Extra | Gives you |
|---|---|
| `fastapi` | `integrations.asgi.instrument_fastapi` |
| `django` | `integrations.clients.instrument_django` |
| `redis`, `httpx`, `sqlalchemy`, `psycopg` | the matching `integrations.clients.*` |
| `temporal` | `integrations.temporal.TracingInterceptor` (Temporal's own; register it on the client) |
| `http` | OTLP over HTTP, with `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` |
| `structlog` | nothing; `add_trace_id` is a plain processor |

## Use

```python
from telemetry_juice import TelemetryConfig, configure
from telemetry_juice.integrations.asgi import instrument_fastapi

configure(TelemetryConfig.from_env("familiar-api"))
instrument_fastapi(app, excluded_urls="/health,/ready")
```

`from_env` reads `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
`SOLUTION` and `ENVIRONMENT`, plus `OTEL_EXPORTER_OTLP_PROTOCOL` (`grpc` by
default, or `http/protobuf`).

## Logs

This does not ship logs. It provides the shape a log pipeline expects: a
`level`, a `msg`, and a `trace_id` only while a trace is open.

```python
# structlog
structlog.configure(processors=[..., add_trace_id, JSONRenderer()])

# stdlib / Django
LOGGING = {"formatters": {"contract": {"()": ContractFormatter}}, ...}
```

## Develop

```sh
make install-hooks   # once per clone
make check           # guards, ruff, mypy --strict, pytest, doctests
```

Branch and pull request; the pre-push hook refuses master. No commit may
attribute authorship to a tool.
