"""Library auto-instrumentation. Each function needs its matching extra."""

from __future__ import annotations

from typing import Any


def instrument_redis() -> None:
    """Instrument every redis-py client created after this call."""
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    RedisInstrumentor().instrument()


def instrument_httpx() -> None:
    """Instrument httpx, propagating trace context on outbound requests."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def instrument_sqlalchemy(engine: Any = None, **kwargs: Any) -> None:
    """Instrument SQLAlchemy.

    Args:
        engine: A specific engine to instrument. Omit to instrument every
            engine created afterwards.
        **kwargs: Passed through, e.g. ``enable_commenter=True`` to embed
            trace context in SQL comments so slow queries in the database's
            own logs can be traced back.
    """
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine, **kwargs)
    else:
        SQLAlchemyInstrumentor().instrument(**kwargs)


def instrument_django() -> None:
    """Instrument Django's request handling.

    Must run before the first request — ``AppConfig.ready()`` is the usual
    place, or a ``settings.py`` import if you are less fussy.
    """
    from opentelemetry.instrumentation.django import DjangoInstrumentor

    DjangoInstrumentor().instrument()


def instrument_psycopg(**kwargs: Any) -> None:
    """Instrument psycopg, so database calls become spans under the request.

    Args:
        **kwargs: Passed through, e.g. ``enable_commenter=True`` to embed
            trace context in SQL comments so slow queries in postgres's own
            logs can be traced back to the request that caused them.
    """
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

    PsycopgInstrumentor().instrument(**kwargs)
