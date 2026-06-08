from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

_DDL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def ensure_schema(connect: Callable[[], Any]) -> None:
    """Create the kinetic tables if absent. Idempotent.

    ``connect`` returns a context manager yielding a Lakebase connection
    whose search_path is already the active registry schema.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_DDL)
