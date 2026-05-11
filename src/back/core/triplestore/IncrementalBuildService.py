"""Incremental build service for LadybugDB triple store.

Manages the version-gate and server-side diff workflow so that only
changed triples are inserted/deleted instead of rebuilding the entire
graph on every sync.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Tuple

from back.core.logging import get_logger
from back.core.errors import ValidationError, InfrastructureError

logger = get_logger(__name__)


class IncrementalBuildService:
    """Orchestrates incremental sync: version gate, diff, and apply.

    Parameters
    ----------
    client:
        A ``DatabricksClient`` (or compatible) with ``execute_query``
        and ``create_or_replace_table_from_query`` methods.
    """

    _SNAPSHOT_PREFIX = "_ob_snapshot_"
    _DIFF_THRESHOLD_PCT = 80

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Source table version tracking
    # ------------------------------------------------------------------

    @staticmethod
    def extract_source_tables(assignment: Dict[str, Any]) -> List[str]:
        """Return distinct fully-qualified source table names from mappings.

        Parses ``sql_query`` fields in entity and relationship mappings
        to extract ``catalog.schema.table`` references.
        """
        tables: set[str] = set()
        pattern = re.compile(
            r"(?:FROM|JOIN)\s+(`?[\w]+`?\.`?[\w]+`?\.`?[\w]+`?)",
            re.IGNORECASE,
        )
        for dsm in assignment.get(
            "entities", assignment.get("data_source_mappings", [])
        ):
            sql = dsm.get("sql_query", "")
            if sql:
                for m in pattern.finditer(sql):
                    tables.add(m.group(1).replace("`", ""))
        for rel in assignment.get(
            "relationships", assignment.get("relationship_mappings", [])
        ):
            sql = rel.get("sql_query", "")
            if sql:
                for m in pattern.finditer(sql):
                    tables.add(m.group(1).replace("`", ""))
        return sorted(tables)

    def check_source_versions(
        self,
        source_tables: List[str],
        stored_versions: Dict[str, int],
    ) -> Tuple[bool, Dict[str, int]]:
        """Compare current source table versions with stored versions.

        Returns ``(changed, new_versions)`` where *changed* is ``True``
        when at least one table has a different version (or is new).
        """
        new_versions: Dict[str, int] = {}
        changed = False

        for table in source_tables:
            try:
                rows = self._client.execute_query(f"DESCRIBE HISTORY {table} LIMIT 1")
                version = int(rows[0].get("version", -1)) if rows else -1
            except Exception as e:
                logger.warning(
                    "Could not get history for %s (table may not be Delta): %s",
                    table,
                    e,
                )
                version = -1

            new_versions[table] = version
            if version != stored_versions.get(table, -1):
                changed = True

        if not source_tables:
            changed = True

        return changed, new_versions

    # ------------------------------------------------------------------
    # Snapshot table management
    # ------------------------------------------------------------------

    @staticmethod
    def snapshot_table_name(
        domain_name: str, delta_cfg: Dict[str, str], version: str = "1"
    ) -> str:
        """Derive the fully-qualified snapshot table name (versioned)."""
        catalog = delta_cfg.get("catalog", "")
        schema = delta_cfg.get("schema", "")
        safe_name = re.sub(r"[^a-z0-9_]", "_", domain_name.lower())
        safe_version = re.sub(r"[^a-z0-9_]", "_", (version or "1").lower())
        prefix = IncrementalBuildService._SNAPSHOT_PREFIX
        return f"{catalog}.{schema}.{prefix}{safe_name}_v{safe_version}"

    def snapshot_exists(self, snapshot_table: str) -> bool:
        """Check whether the snapshot Delta table exists."""
        try:
            rows = self._client.execute_query(f"SELECT 1 FROM {snapshot_table} LIMIT 0")
            return True
        except Exception:
            return False

    def create_snapshot(self, view_table: str, snapshot_table: str) -> None:
        """Create the snapshot table from the current VIEW contents."""
        parts = snapshot_table.split(".")
        if len(parts) != 3:
            raise ValidationError(
                f"Snapshot table must be fully qualified: {snapshot_table}"
            )
        cat, sch, tbl = parts
        ok, msg = self._client.create_or_replace_table_from_query(
            cat,
            sch,
            tbl,
            f"SELECT subject, predicate, object FROM {view_table}",
        )
        if not ok:
            raise InfrastructureError(f"Failed to create snapshot: {msg}")
        logger.info("Created snapshot table %s", snapshot_table)

    def refresh_snapshot(self, view_table: str, snapshot_table: str) -> None:
        """Replace the snapshot table with current VIEW contents."""
        self.create_snapshot(view_table, snapshot_table)

    def drop_snapshot(self, snapshot_table: str) -> None:
        """Drop the snapshot table if it exists."""
        try:
            self._client.execute_query(f"DROP TABLE IF EXISTS {snapshot_table}")
            logger.info("Dropped snapshot table %s", snapshot_table)
        except Exception as e:
            logger.warning("Could not drop snapshot %s: %s", snapshot_table, e)

    # ------------------------------------------------------------------
    # Server-side diff
    # ------------------------------------------------------------------

    @staticmethod
    def _added_sql(view_table: str, snapshot_table: str) -> str:
        return (
            f"SELECT subject, predicate, object FROM {view_table} "
            f"EXCEPT "
            f"SELECT subject, predicate, object FROM {snapshot_table}"
        )

    @staticmethod
    def _removed_sql(view_table: str, snapshot_table: str) -> str:
        return (
            f"SELECT subject, predicate, object FROM {snapshot_table} "
            f"EXCEPT "
            f"SELECT subject, predicate, object FROM {view_table}"
        )

    def compute_diff(
        self,
        view_table: str,
        snapshot_table: str,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Compute triple-level diff between the VIEW and snapshot.

        Returns ``(to_add, to_remove)`` where each is a list of
        ``{"subject": ..., "predicate": ..., "object": ...}`` dicts.

        .. note::
           Materializes both diff sides in memory. The Digital Twin build
           pipeline now prefers :meth:`count_diff` + :meth:`iter_added` /
           :meth:`iter_removed` so the FastAPI process never holds the full
           diff for large graphs.
        """
        to_add = self._client.execute_query(
            self._added_sql(view_table, snapshot_table)
        )
        to_remove = self._client.execute_query(
            self._removed_sql(view_table, snapshot_table)
        )
        logger.info(
            "Incremental diff: %d additions, %d removals",
            len(to_add),
            len(to_remove),
        )
        return to_add or [], to_remove or []

    def count_diff(
        self,
        view_table: str,
        snapshot_table: str,
    ) -> Tuple[int, int]:
        """Return ``(add_count, remove_count)`` without materializing diff rows.

        Both COUNTs run server-side in Databricks SQL; the app sees one int
        per side instead of the full triple lists. Used by the build pipeline
        to size the fallback-to-full heuristic before deciding whether to
        stream the diff into the graph store.
        """
        add_rows = self._client.execute_query(
            f"SELECT COUNT(*) AS cnt FROM ("
            f"{self._added_sql(view_table, snapshot_table)}"
            f") AS d"
        )
        rm_rows = self._client.execute_query(
            f"SELECT COUNT(*) AS cnt FROM ("
            f"{self._removed_sql(view_table, snapshot_table)}"
            f") AS d"
        )
        add_n = int(add_rows[0].get("cnt", 0)) if add_rows else 0
        rm_n = int(rm_rows[0].get("cnt", 0)) if rm_rows else 0
        return add_n, rm_n

    def iter_added(
        self,
        view_table: str,
        snapshot_table: str,
        batch_size: int = 5000,
    ) -> Iterator[Dict[str, str]]:
        """Stream the *additions* side of the diff (rows in VIEW \\ snapshot)."""
        if not hasattr(self._client, "iter_rows"):
            raise InfrastructureError(
                "Source client does not support row streaming (iter_rows)."
            )
        return self._client.iter_rows(
            self._added_sql(view_table, snapshot_table),
            batch_size=batch_size,
        )

    def iter_removed(
        self,
        view_table: str,
        snapshot_table: str,
        batch_size: int = 5000,
    ) -> Iterator[Dict[str, str]]:
        """Stream the *removals* side of the diff (rows in snapshot \\ VIEW)."""
        if not hasattr(self._client, "iter_rows"):
            raise InfrastructureError(
                "Source client does not support row streaming (iter_rows)."
            )
        return self._client.iter_rows(
            self._removed_sql(view_table, snapshot_table),
            batch_size=batch_size,
        )

    def should_fallback_to_full(
        self,
        to_add: int,
        to_remove: int,
        current_total: int,
    ) -> bool:
        """Return True if the diff is large enough to justify a full rebuild."""
        if current_total <= 0:
            return True
        change_pct = ((to_add + to_remove) / current_total) * 100
        threshold = IncrementalBuildService._DIFF_THRESHOLD_PCT
        if change_pct >= threshold:
            logger.info(
                "Diff is %.1f%% of total (%d changes on %d triples) "
                "— falling back to full rebuild",
                change_pct,
                to_add + to_remove,
                current_total,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # View-level triple count (for fallback threshold)
    # ------------------------------------------------------------------

    def count_view_triples(self, view_table: str) -> int:
        """Return the number of triples in the VIEW."""
        try:
            rows = self._client.execute_query(
                f"SELECT COUNT(*) AS cnt FROM {view_table}"
            )
            return int(rows[0].get("cnt", 0)) if rows else 0
        except Exception:
            return 0
