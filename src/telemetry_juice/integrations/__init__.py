"""Optional per-framework instrumentation.

Each module here imports a dependency that is not in the base install. They
are never imported by the package root — import the one you need, and let the
extras in ``pyproject.toml`` decide what gets installed:

.. code-block:: sh

    uv add "telemetry-juice[fastapi,temporal]"
"""
