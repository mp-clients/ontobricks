"""Lakebase connection provider for kinetic-action integration tests.

``test_connect`` mirrors the mechanism used by ``LakebaseRegistryStore._connect``:
it draws from the same process-wide ``_LakebasePool`` keyed by
``(auth, schema, database)``.  The schema defaults to the same
``ontobricks_registry`` schema the registry store uses (configurable via the
``LAKEBASE_ACTIONS_SCHEMA`` env var to allow a separate test schema).

This file is imported only when ``LAKEBASE_TEST_CONNECT=1`` is set; all tests
in this package are skipped otherwise.
"""

from __future__ import annotations

import os


def _build_test_connect():
    """Return a ``connect`` callable backed by the shared Lakebase pool.

    Raises ``NotImplementedError`` (with a clear message) if the Lakebase
    auth or psycopg is unavailable — the integration tests are skipped
    before this is reached when ``LAKEBASE_TEST_CONNECT`` is unset.
    """
    try:
        from back.core.databricks import get_lakebase_auth
        from back.objects.registry.store.lakebase.store import _get_pool
    except ImportError as exc:
        raise NotImplementedError(
            "Lakebase dependencies not available for integration tests. "
            "Install with: uv sync --extra lakebase"
        ) from exc

    schema = os.environ.get("LAKEBASE_ACTIONS_SCHEMA", "ontobricks_registry")
    database = os.environ.get("LAKEBASE_ACTIONS_DATABASE", "")

    auth = get_lakebase_auth()
    pool = _get_pool(auth, schema, database)

    def connect():
        return pool.connection()

    return connect


# Lazy singleton — only constructed when the module is actually imported
# (which only happens when the test runs, i.e. after the env-var gate).
test_connect = _build_test_connect()
