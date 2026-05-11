"""Internal helper that drives a single Digital Twin build.

Extracted from :class:`back.objects.digitaltwin.DigitalTwin.run_build_task`
(formerly an 839-line method) to make each phase — prepare → gate → view →
diff → apply → snapshot → cache → archive — a named, focused method that
shares state via ``self`` instead of a closure.

This module is **private** to the ``digitaltwin`` package; it is not
re-exported from ``__init__.py`` and external callers must keep using
``DigitalTwin.run_build_task`` (which is now a thin delegator).

Behaviour is byte-for-byte identical with the original monolithic
implementation: the same log lines, progress percentages, error
messages, and side effects are emitted in the same order. The only
change is structural — Fowler "Replace Method with Method Object".
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from back.core.errors import OntoBricksError
from back.core.logging import get_logger
from back.objects.digitaltwin.models import DomainSnapshot
from shared.config.constants import DEFAULT_GRAPH_NAME

logger = get_logger(__name__)


class _BuildPipeline:
    """One run of the Digital Twin build/sync pipeline.

    Constructed once per build with the same arguments as the legacy
    :meth:`DigitalTwin.run_build_task`. Call :meth:`run` to execute the
    pipeline; it never raises (errors flow through ``tm.fail_task``).
    """

    def __init__(
        self,
        tm,
        task_id: str,
        domain,
        settings,
        domain_snap: DomainSnapshot,
        host: str,
        token: str,
        warehouse_id: str,
        view_table: str,
        graph_name: str,
        r2rml_content: str,
        base_uri: str,
        mapping_config,
        ontology_config,
        stored_source_versions: dict,
        delta_cfg: dict,
        force_full: bool,
        *,
        config_changed: bool = False,
        snapshot_version: str,
        build_kind: str = "session",
    ) -> None:
        self.tm = tm
        self.task_id = task_id
        self.domain = domain
        self.settings = settings
        self.domain_snap = domain_snap
        self.host = host
        self.token = token
        self.warehouse_id = warehouse_id
        self.view_table = view_table
        self.graph_name = graph_name
        self.r2rml_content = r2rml_content
        self.base_uri = base_uri
        self.mapping_config = mapping_config
        self.ontology_config = ontology_config
        self.stored_source_versions = stored_source_versions
        self.delta_cfg = delta_cfg
        self.force_full = force_full
        self.config_changed = config_changed
        self.snapshot_version = snapshot_version
        self.build_kind = build_kind

        self.is_api = build_kind == "api"
        self.start_time = time.time()
        self.phase_times: Dict[str, float] = {}
        self.parts = view_table.split(".")

        self.cfg_forced_full = force_full or (
            config_changed if not self.is_api else False
        )
        self.actual_mode = "full" if self.cfg_forced_full else "incremental"
        self.domain_name = (domain.info or {}).get("name", "<unknown>")

        # Lazy-initialised across phases.
        self.source_client = None
        self.store = None
        self.incr_svc = None
        self.snapshot_table: str = ""
        self.entity_mappings: list = []
        self.relationship_mappings: list = []
        self.spark_sql: str = ""
        self.new_source_versions: Dict[str, Any] = {}
        self.diff_added_count: int = 0
        self.diff_removed_count: int = 0
        self.total_triple_count: int = 0
        self.triple_count: int = 0
        self.archive_task_id: Optional[str] = None
        # Lakebase managed-synced mode flag, resolved once before _open_store
        # so the diff-skip and apply-branch decisions stay consistent across
        # phases.
        self._lakebase_engine_config: Dict[str, Any] = {}
        self._is_lakebase_synced: bool = False

    # ------------------------------------------------------------------
    # Phase utilities
    # ------------------------------------------------------------------

    def _log_phase(self, name: str, t0_phase: float) -> None:
        elapsed = time.time() - t0_phase
        self.phase_times[name] = elapsed
        logger.info(
            "[DT-BUILD %s] phase [%s]: %.2fs", self.task_id, name, elapsed
        )

    def _resolve_lakebase_mode(self) -> None:
        """Resolve graph engine + engine_config once, before ``_open_store``.

        The diff-skip path (in ``_compute_diff_or_fall_through``) and the
        synced apply path (in ``_apply_full_rebuild`` / ``_apply_incremental_changes``)
        both need to know whether we are in ``managed_synced`` mode *before*
        the store is constructed. Resolving once here keeps the answer
        consistent and avoids re-reading global config on every phase.
        """
        from back.core.triplestore.TripleStoreFactory import TripleStoreFactory

        try:
            engine = TripleStoreFactory._resolve_graph_engine(
                self.domain, self.settings
            )
            cfg = TripleStoreFactory._resolve_graph_engine_config(
                self.domain, self.settings
            ) or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "[DT-BUILD %s] could not resolve lakebase mode: %s",
                self.task_id,
                exc,
            )
            engine = "ladybug"
            cfg = {}
        self._lakebase_engine_config = cfg
        self._is_lakebase_synced = (
            engine == "lakebase" and cfg.get("sync_mode") == "managed_synced"
        )
        if self._is_lakebase_synced:
            logger.info(
                "[DT-BUILD %s] lakebase managed_synced mode active — "
                "bulk data movement runs on the data plane via Lakeflow",
                self.task_id,
            )

    def _lakebase_managed_synced(self) -> bool:
        """Return ``True`` when bulk data movement should be delegated to Lakeflow."""
        return self._is_lakebase_synced

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Drive the build through every phase, reporting progress to ``tm``."""
        self._log_start()
        try:
            t_phase = time.time()
            if not self._prepare_translation():
                return
            self._log_phase("prepare", t_phase)
            self.tm.update_progress(self.task_id, 10, "SQL generated")

            from back.core.triplestore import IncrementalBuildService

            self.incr_svc = IncrementalBuildService(self.source_client)
            self._resolve_lakebase_mode()
            self._compute_initial_snapshot_table()

            if not self._run_incremental_gate():
                return

            t_phase = time.time()
            if not self._create_view():
                return
            self._log_phase("create_view", t_phase)
            self._post_create_view_progress()

            self._compute_session_snapshot_table()
            self._compute_diff_or_fall_through()

            t_phase = time.time()
            self._announce_apply_step()

            if not self._open_store():
                return

            if self.actual_mode == "full":
                if not self._apply_full_rebuild():
                    return
            else:
                if not self._apply_incremental_changes():
                    return

            self._log_phase("apply_graph", t_phase)

            self._refresh_snapshot()
            self._persist_source_versions()

            if not self.is_api:
                self._populate_session_cache()
                self._start_background_archive()

            self._complete_task()

        except Exception as exc:  # noqa: BLE001 — orchestrator final guard
            self._fail_unexpected(exc)

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    def _log_start(self) -> None:
        logger.info(
            "[DT-BUILD %s] START kind=%s domain=%s view=%s graph=%s mode=%s "
            "force_full=%s config_changed=%s snapshot_version=%s "
            "warehouse=%s",
            self.task_id,
            self.build_kind,
            self.domain_name,
            self.view_table,
            self.graph_name,
            self.actual_mode,
            self.force_full,
            self.config_changed,
            self.snapshot_version,
            self.warehouse_id,
        )
        if self.cfg_forced_full and not self.force_full and self.config_changed:
            logger.warning(
                "[DT-BUILD %s] forcing full rebuild because mapping/ontology "
                "configuration changed since the last build",
                self.task_id,
            )

    def _prepare_translation(self) -> bool:
        """Parse R2RML, augment mappings, build the Spark SQL union query."""
        from back.core.databricks import DatabricksClient
        from back.core.w3c import sparql

        from back.objects.digitaltwin.DigitalTwin import DigitalTwin

        self.tm.start_task(self.task_id, "Preparing mappings...")
        self.source_client = DatabricksClient(
            host=self.host, token=self.token, warehouse_id=self.warehouse_id
        )

        entity_mappings, relationship_mappings = sparql.extract_r2rml_mappings(
            self.r2rml_content
        )
        logger.info(
            "[DT-BUILD %s] R2RML parsed: %d entity mapping(s), "
            "%d relationship mapping(s)",
            self.task_id,
            len(entity_mappings or []),
            len(relationship_mappings or []),
        )
        entity_mappings = DigitalTwin.augment_mappings_from_config(
            entity_mappings, self.mapping_config, self.base_uri, self.ontology_config
        )
        relationship_mappings = DigitalTwin.augment_relationships_from_config(
            relationship_mappings,
            self.mapping_config,
            self.base_uri,
            self.ontology_config,
        )
        logger.info(
            "[DT-BUILD %s] mappings augmented from config: %d entity, "
            "%d relationship (base_uri=%s)",
            self.task_id,
            len(entity_mappings or []),
            len(relationship_mappings or []),
            self.base_uri,
        )
        self.entity_mappings = entity_mappings
        self.relationship_mappings = relationship_mappings

        if not entity_mappings and not relationship_mappings:
            logger.warning(
                "[DT-BUILD %s] aborting: no valid mappings found "
                "(entities=%s, relationships=%s)",
                self.task_id,
                bool(entity_mappings),
                bool(relationship_mappings),
            )
            self.tm.fail_task(self.task_id, "No valid mappings found")
            return False

        all_data_sparql = (
            f"PREFIX : <{self.base_uri}>\n"
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n\n"
            "SELECT ?subject ?predicate ?object\n"
            "WHERE {\n"
            "    ?subject ?predicate ?object .\n"
            "}"
        )

        try:
            result = sparql.translate_sparql_to_spark(
                all_data_sparql,
                entity_mappings,
                None,
                relationship_mappings,
                dialect="spark",
            )
        except OntoBricksError as exc:
            logger.error(
                "[DT-BUILD %s] SPARQL→Spark translation failed: %s",
                self.task_id,
                exc.message,
            )
            self.tm.fail_task(self.task_id, exc.message)
            return False

        if self.is_api and not result.get("success"):
            logger.error(
                "[DT-BUILD %s] SPARQL→Spark translation returned failure: %s",
                self.task_id,
                result.get("message", "Translation failed"),
            )
            self.tm.fail_task(
                self.task_id, result.get("message", "Translation failed")
            )
            return False

        self.spark_sql = result["sql"]
        logger.info(
            "[DT-BUILD %s] SPARQL→Spark translation OK (sql_chars=%d)",
            self.task_id,
            len(self.spark_sql or ""),
        )
        return True

    def _compute_initial_snapshot_table(self) -> None:
        """For API builds we must compute the snapshot name early."""
        if self.is_api:
            self.snapshot_table = self.incr_svc.snapshot_table_name(
                (self.domain.info or {}).get("name", DEFAULT_GRAPH_NAME),
                self.delta_cfg,
                version=self.snapshot_version,
            )

    def _compute_session_snapshot_table(self) -> None:
        """Session builds compute the snapshot name after the VIEW is created."""
        if not self.is_api:
            self.snapshot_table = self.incr_svc.snapshot_table_name(
                (self.domain.info or {}).get("name", DEFAULT_GRAPH_NAME),
                self.delta_cfg,
                version=self.snapshot_version,
            )

    def _run_incremental_gate(self) -> bool:
        """Check source-table versions before the heavy work.

        Returns ``True`` if the build should proceed; ``False`` when the
        gate decided the build can be skipped or has already failed (in
        which case ``tm.complete_task``/``tm.fail_task`` was called).
        """
        if self.actual_mode != "incremental":
            logger.info(
                "[DT-BUILD %s] full rebuild requested — skipping source-version gate",
                self.task_id,
            )
            self.tm.skip_step(
                self.task_id, "Full rebuild requested — skipping change check"
            )
            return True

        gate_msg = (
            "Checking source tables..."
            if self.is_api
            else "Checking source tables for changes..."
        )
        self.tm.advance_step(self.task_id, gate_msg)
        source_tables = self.incr_svc.extract_source_tables(self.mapping_config)
        logger.info(
            "[DT-BUILD %s] incremental gate: checking %d source table(s): %s",
            self.task_id,
            len(source_tables),
            source_tables,
        )

        changed, new_source_versions = self.incr_svc.check_source_versions(
            source_tables, self.stored_source_versions
        )
        self.new_source_versions = new_source_versions
        changed_tables = [
            t
            for t, v in new_source_versions.items()
            if v != self.stored_source_versions.get(t, -1)
        ]
        if changed_tables:
            logger.info(
                "[DT-BUILD %s] %d/%d source table(s) changed since last "
                "build: %s",
                self.task_id,
                len(changed_tables),
                len(source_tables) or 1,
                changed_tables,
            )
        if not changed:
            duration = time.time() - self.start_time
            logger.info(
                "[DT-BUILD %s] incremental gate: no source changes "
                "detected — skipping build (elapsed=%.2fs)",
                self.task_id,
                duration,
            )
            self.tm.complete_task(
                self.task_id,
                result={
                    "triple_count": 0,
                    "view_table": self.view_table,
                    "graph_name": self.graph_name,
                    "build_mode": "skipped",
                    "skipped_reason": "No source table changes detected",
                    "duration_seconds": duration,
                },
                message="No source data changes — build skipped",
            )
            return False

        if not self.is_api:
            self.tm.update_progress(self.task_id, 15, "Source changes detected")
        return True

    def _create_view(self) -> bool:
        """Create or replace the Spark VIEW. Returns ``False`` on failure."""
        from back.objects.digitaltwin.DigitalTwin import DigitalTwin

        self.tm.advance_step(self.task_id, f"Creating VIEW {self.view_table}...")
        logger.info(
            "[DT-BUILD %s] creating VIEW %s on warehouse %s",
            self.task_id,
            self.view_table,
            self.warehouse_id,
        )
        try:
            catalog, schema, vname = self.parts
            view_ok, view_msg = self.source_client.create_or_replace_view(
                catalog, schema, vname, self.spark_sql
            )
            if not view_ok:
                if self.is_api:
                    logger.error(
                        "[DT-BUILD %s] failed to create VIEW %s: %s",
                        self.task_id,
                        self.view_table,
                        view_msg,
                    )
                    self.tm.fail_task(
                        self.task_id, f"Failed to create VIEW: {view_msg}"
                    )
                else:
                    detail = DigitalTwin.diagnose_view_error(
                        view_msg, self.entity_mappings, self.relationship_mappings
                    )
                    logger.error(
                        "[DT-BUILD %s] failed to create VIEW %s:\n%s",
                        self.task_id,
                        self.view_table,
                        detail,
                    )
                    self.tm.fail_task(
                        self.task_id, f"Failed to create VIEW: {detail}"
                    )
                return False
            logger.info(
                "[DT-BUILD %s] VIEW %s created", self.task_id, self.view_table
            )
            return True
        except Exception as exc:  # noqa: BLE001
            if self.is_api:
                logger.exception(
                    "[DT-BUILD %s] VIEW creation raised: %s", self.task_id, exc
                )
                self.tm.fail_task(self.task_id, str(exc))
                return False
            detail = DigitalTwin.diagnose_view_error(
                str(exc), self.entity_mappings, self.relationship_mappings
            )
            logger.exception(
                "[DT-BUILD %s] failed to create VIEW %s:\n%s",
                self.task_id,
                self.view_table,
                detail,
            )
            self.tm.fail_task(self.task_id, f"Failed to create VIEW: {detail}")
            return False

    def _post_create_view_progress(self) -> None:
        if self.is_api:
            self.tm.update_progress(self.task_id, 25, "VIEW created")
        else:
            self.tm.update_progress(
                self.task_id, 25, f"VIEW {self.view_table} created"
            )

    def _compute_diff_or_fall_through(self) -> None:
        """If snapshot exists, count diff; otherwise force full rebuild.

        Sizes the diff via cheap warehouse-side ``COUNT(*)`` so the
        fall-back-to-full heuristic runs without ever pulling diff rows into
        the FastAPI process. The actual triple rows are streamed later in
        :meth:`_apply_incremental_changes`.

        Skipped entirely when the store is in ``managed_synced`` mode: the
        Lakeflow snapshot pipeline always rewrites the synced PG table, so
        there is no benefit in computing a row-level diff first.
        """
        if self._lakebase_managed_synced():
            self.actual_mode = "full"
            self.tm.skip_step(
                self.task_id,
                "Lakebase managed-synced — full sync via Lakeflow",
            )
            return
        if self.actual_mode == "incremental" and self.incr_svc.snapshot_exists(
            self.snapshot_table
        ):
            self.tm.advance_step(self.task_id, "Computing incremental diff...")
            logger.info(
                "[DT-BUILD %s] computing incremental diff (view=%s, "
                "snapshot=%s)",
                self.task_id,
                self.view_table,
                self.snapshot_table,
            )
            try:
                self.diff_added_count, self.diff_removed_count = (
                    self.incr_svc.count_diff(
                        self.view_table, self.snapshot_table
                    )
                )
                self.total_triple_count = self.incr_svc.count_view_triples(
                    self.view_table
                )
                logger.info(
                    "[DT-BUILD %s] diff result: +%d / -%d on %d total triples",
                    self.task_id,
                    self.diff_added_count,
                    self.diff_removed_count,
                    self.total_triple_count,
                )

                if self.incr_svc.should_fallback_to_full(
                    self.diff_added_count,
                    self.diff_removed_count,
                    self.total_triple_count,
                ):
                    logger.warning(
                        "[DT-BUILD %s] diff too large — falling back to "
                        "full rebuild (+%d/-%d on %d total)",
                        self.task_id,
                        self.diff_added_count,
                        self.diff_removed_count,
                        self.total_triple_count,
                    )
                    self.actual_mode = "full"
                elif not self.is_api:
                    self.tm.update_progress(
                        self.task_id,
                        40,
                        f"Diff: +{self.diff_added_count} / -{self.diff_removed_count} triples",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "[DT-BUILD %s] incremental diff failed, falling back "
                    "to full rebuild: %s",
                    self.task_id,
                    exc,
                )
                self.actual_mode = "full"
        else:
            if self.actual_mode == "incremental":
                logger.info(
                    "[DT-BUILD %s] no snapshot table found (%s) — first "
                    "build will be full and will create the snapshot",
                    self.task_id,
                    self.snapshot_table,
                )
            self.actual_mode = "full"
            self.tm.skip_step(
                self.task_id,
                "No previous snapshot — full rebuild instead",
            )

    def _announce_apply_step(self) -> None:
        apply_msg = (
            "Applying changes to graph..."
            if self.is_api
            else "Applying changes to the knowledge graph..."
        )
        self.tm.advance_step(self.task_id, apply_msg)

    def _open_store(self) -> bool:
        """Initialise the Ladybug graph backend. Returns ``False`` on failure."""
        from back.core.triplestore import get_triplestore as _get_ts

        self.store = _get_ts(self.domain_snap, self.settings, backend="graph")
        if not self.store:
            logger.error(
                "[DT-BUILD %s] could not initialize LadybugDB backend "
                "(domain=%s)",
                self.task_id,
                self.domain_name,
            )
            self.tm.fail_task(self.task_id, "Could not initialize LadybugDB backend")
            return False
        return True

    def _apply_full_rebuild(self) -> bool:
        """Drop, recreate, and bulk-insert all triples.

        Reads triples from the warehouse VIEW in fixed-size batches via
        ``iter_rows`` and feeds them straight into the graph store's bulk
        ingest path, so the FastAPI process never holds the full graph in
        memory. Triple count is sourced from a cheap server-side ``COUNT(*)``
        before streaming so we can keep accurate progress reporting and the
        existing "empty graph" early-return semantics.

        In ``managed_synced`` mode the entire branch is replaced by
        :meth:`_apply_via_synced_pipeline` -- the Lakeflow snapshot pipeline
        rewrites the synced PG table and the app does not iterate triples.
        """
        if self._lakebase_managed_synced():
            return self._apply_via_synced_pipeline(full=True)
        t_fetch = time.time()
        logger.info(
            "[DT-BUILD %s] full rebuild: reading all triples from VIEW %s",
            self.task_id,
            self.view_table,
        )
        if not self.is_api:
            self.tm.update_progress(self.task_id, 40, "Reading all triples from VIEW...")

        try:
            triple_count = self.incr_svc.count_view_triples(self.view_table)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[DT-BUILD %s] failed to count triples in VIEW %s: %s",
                self.task_id,
                self.view_table,
                exc,
            )
            self.tm.fail_task(self.task_id, "Query execution on VIEW failed")
            return False
        self._log_phase("fetch_triples", t_fetch)

        self.triple_count = triple_count
        logger.info(
            "[DT-BUILD %s] VIEW reports %d triples to ingest",
            self.task_id,
            triple_count,
        )
        if triple_count == 0:
            logger.warning(
                "[DT-BUILD %s] VIEW %s returned 0 triples — check that "
                "your R2RML mappings match real data in the source "
                "tables (view will exist but graph will be empty)",
                self.task_id,
                self.view_table,
            )
            empty_msg = (
                "VIEW created but no triples generated (check your mappings)"
                if not self.is_api
                else "VIEW created but no triples generated"
            )
            self.tm.complete_task(
                self.task_id,
                result={
                    "triple_count": 0,
                    "view_table": self.view_table,
                    "graph_name": self.graph_name,
                    "build_mode": "full",
                    "duration_seconds": time.time() - self.start_time,
                },
                message=empty_msg,
            )
            return False

        t_insert = time.time()
        if not self.is_api:
            self.tm.update_progress(
                self.task_id, 50, f"Full rebuild: writing {triple_count} triples..."
            )
        logger.info(
            "[DT-BUILD %s] dropping & recreating graph table %s",
            self.task_id,
            self.graph_name,
        )
        self.store.drop_table(self.graph_name)
        self.store.create_table(self.graph_name)

        is_api_local = self.is_api
        tm_local = self.tm
        task_id_local = self.task_id
        total_local = triple_count

        def _on_progress_full(written: int, total: int) -> None:
            # The bulk iterator does not know the upfront target -- it passes
            # the running written count as ``total`` -- so we anchor the
            # denominator on ``total_local`` (server-side ``count_view_triples``
            # captured before streaming) so the UI reads "x / true_total"
            # instead of "x / x".
            denom = total_local or total or 1
            progress = 50 + int(written / denom * 40)
            if is_api_local:
                tm_local.update_progress(
                    task_id_local,
                    progress,
                    f"Written {written}/{denom} triples...",
                )
            else:
                tm_local.update_progress(
                    task_id_local,
                    min(progress, 90),
                    f"Written {written}/{denom} triples...",
                )

        logger.info(
            "[DT-BUILD %s] streaming %d triples into %s (batch_size=5000)",
            self.task_id,
            triple_count,
            self.graph_name,
        )
        select_sql = (
            f"SELECT subject, predicate, object FROM {self.view_table}"
        )
        self._stream_triples_into_store(
            select_sql,
            insert_batch_size=5000,
            on_progress=_on_progress_full,
        )
        logger.info(
            "[DT-BUILD %s] optimizing graph table %s",
            self.task_id,
            self.graph_name,
        )
        self.store.optimize_table(self.graph_name)
        self._log_phase("graph_insert", t_insert)
        self.total_triple_count = triple_count
        return True

    def _stream_triples_into_store(
        self,
        select_sql: str,
        *,
        insert_batch_size: int = 5000,
        on_progress: Optional[Any] = None,
    ) -> int:
        """Stream warehouse rows into the graph store via the bulk insert iterator.

        Uses ``store.bulk_insert_iter`` when the backend exposes it (Lakebase),
        falling back to materializing the iterator into a list and calling
        ``insert_triples`` for backends without a streaming write path
        (e.g. LadybugDB). The warehouse-side cursor stays open for the
        lifetime of the iterator so memory stays bounded by ``insert_batch_size``
        on the streaming path.
        """
        triple_iter = self.source_client.iter_rows(
            select_sql, batch_size=insert_batch_size
        )
        if hasattr(self.store, "bulk_insert_iter"):
            return self.store.bulk_insert_iter(
                self.graph_name,
                triple_iter,
                batch_size=insert_batch_size,
                on_progress=on_progress,
            )
        # Backend without streaming bulk path (LadybugDB) — materialize.
        triples = list(triple_iter)
        return self.store.insert_triples(
            self.graph_name,
            triples,
            batch_size=min(insert_batch_size, 500),
            on_progress=on_progress,
        )

    def _stream_triples_out_of_store(
        self,
        select_sql: str,
        *,
        delete_batch_size: int = 5000,
        on_progress: Optional[Any] = None,
    ) -> int:
        """Stream warehouse rows into ``store.bulk_delete_iter`` (or fallback)."""
        triple_iter = self.source_client.iter_rows(
            select_sql, batch_size=delete_batch_size
        )
        if hasattr(self.store, "bulk_delete_iter"):
            return self.store.bulk_delete_iter(
                self.graph_name,
                triple_iter,
                batch_size=delete_batch_size,
                on_progress=on_progress,
            )
        triples = list(triple_iter)
        return self.store.delete_triples(
            self.graph_name,
            triples,
            batch_size=min(delete_batch_size, 500),
            on_progress=on_progress,
        )

    def _apply_via_synced_pipeline(self, *, full: bool) -> bool:
        """Lakebase managed-synced apply path -- triples never enter the app.

        Steps:

        1. Build the synced UC FQN from ``engine_config.sync_uc_catalog`` (or
           :func:`resolve_sync_uc_fallback_catalog`).
        2. ``CREATE SCHEMA IF NOT EXISTS`` in Unity Catalog (warehouse DDL) for
           that FQN's ``catalog.schema`` — distinct from Postgres on Lakebase.
        3. ``SyncedTableManager.ensure`` — registers the synced table (Lakeflow
           may auto-fire the initial snapshot).
        4. ``ensure_synced_companion`` — Postgres companion table only (union view
           references the ``_sync`` table, which does not exist until step 5 completes).
        5. ``trigger_and_wait`` — wait until sync reaches an online state.
        6. ``ensure_synced_union_view`` — union view over ``_sync`` ∪ companion.
        7. On a full rebuild, ``TRUNCATE`` the companion for a clean reasoning slate.
        """
        from back.core.errors import InfrastructureError
        from back.core.graphdb.lakebase.LakebaseFlatStore import (
            resolve_sync_uc_fallback_catalog,
        )

        t0 = time.time()
        try:
            mgr = self.store.synced_manager()
            fallback_cat = resolve_sync_uc_fallback_catalog(
                self.domain, self.settings, self.delta_cfg
            )
            synced_uc = self.store.synced_uc_name(
                self.graph_name, fallback_catalog=fallback_cat
            )
            logger.info(
                "[DT-BUILD %s] Managed-sync registers UC synced table at %s "
                "(graph_engine_config.sync_uc_catalog=%r; fallback_catalog=%r; "
                "UC schema segment=%s (Registry Volume schema when configured, "
                "else graph_engine_config.schema)",
                self.task_id,
                synced_uc,
                (self.store.sync_uc_catalog or "").strip() or None,
                fallback_cat or None,
                self.store.graph_schema,
            )
        except InfrastructureError as exc:
            logger.error(
                "[DT-BUILD %s] managed_synced setup failed: %s",
                self.task_id,
                exc,
            )
            self.tm.fail_task(self.task_id, str(exc))
            return False

        if not self.is_api:
            self.tm.update_progress(
                self.task_id, 45, "Lakebase managed-synced — registering pipeline…"
            )
        try:
            from back.core.graphdb.lakebase._sync_uc_schema import (
                ensure_uc_schema_for_synced_table_fqn,
            )

            ensure_uc_schema_for_synced_table_fqn(
                self.source_client,
                synced_uc,
                task_log_prefix=f"[DT-BUILD {self.task_id}]",
            )
            mgr.ensure(
                synced_uc,
                source_table_full_name=self.view_table,
                primary_key_columns=["subject", "predicate", "object"],
                sync_mode=self.store.sync_table_mode,
            )
            self.store.ensure_synced_companion(self.graph_name)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[DT-BUILD %s] failed to register synced table %s: %s",
                self.task_id,
                synced_uc,
                exc,
            )
            self.tm.fail_task(
                self.task_id,
                f"Could not register Lakebase synced table: {exc}",
            )
            return False

        if not self.is_api:
            self.tm.update_progress(
                self.task_id,
                55,
                "Lakebase managed-synced — syncing graph from Delta…",
            )
        try:
            state = mgr.trigger_and_wait(
                synced_uc, timeout_s=self.store.sync_timeout_s
            )
            logger.info(
                "[DT-BUILD %s] synced table %s reached state=%s in %.1fs",
                self.task_id,
                synced_uc,
                state,
                time.time() - t0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[DT-BUILD %s] synced refresh failed for %s: %s",
                self.task_id,
                synced_uc,
                exc,
            )
            self.tm.fail_task(
                self.task_id, f"Lakebase sync did not complete: {exc}"
            )
            return False

        try:
            self.store.ensure_synced_union_view(self.graph_name)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[DT-BUILD %s] failed to create union view for %s: %s",
                self.task_id,
                synced_uc,
                exc,
            )
            self.tm.fail_task(
                self.task_id,
                f"Could not create Lakebase union view after sync: {exc}",
            )
            return False

        if full:
            try:
                self.store.truncate_companion(self.graph_name)
                logger.info(
                    "[DT-BUILD %s] truncated companion table for %s "
                    "(full rebuild — reasoning starts clean)",
                    self.task_id,
                    self.graph_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[DT-BUILD %s] could not truncate companion (non-fatal): %s",
                    self.task_id,
                    exc,
                )

        try:
            triple_count = self.incr_svc.count_view_triples(self.view_table)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[DT-BUILD %s] could not count VIEW triples post-sync: %s",
                self.task_id,
                exc,
            )
            triple_count = 0
        self.triple_count = triple_count
        self.total_triple_count = triple_count
        if not self.is_api:
            self.tm.update_progress(
                self.task_id, 90, f"Synced {triple_count} triples"
            )
        return True

    def _apply_incremental_changes(self) -> bool:
        """Stream the diff from the warehouse into the graph store.

        Counts come from :meth:`_compute_diff_or_fall_through` (server-side
        ``COUNT(*)``); the actual triple rows are pulled here via
        ``IncrementalBuildService.iter_added`` / ``iter_removed`` and pushed
        straight into ``store.bulk_*_iter`` so the FastAPI process never
        materialises the full diff.

        In ``managed_synced`` mode this branch is unreachable
        (:meth:`_compute_diff_or_fall_through` forces ``actual_mode = "full"``
        for synced stores), but we keep the early guard for safety.
        """
        if self._lakebase_managed_synced():
            return self._apply_via_synced_pipeline(full=False)
        triple_count = self.diff_added_count + self.diff_removed_count
        self.triple_count = triple_count
        logger.info(
            "[DT-BUILD %s] applying incremental changes to %s: "
            "+%d / -%d",
            self.task_id,
            self.graph_name,
            self.diff_added_count,
            self.diff_removed_count,
        )
        if triple_count == 0 and not self.is_api:
            duration = time.time() - self.start_time
            self.tm.complete_task(
                self.task_id,
                result={
                    "triple_count": self.total_triple_count,
                    "view_table": self.view_table,
                    "graph_name": self.graph_name,
                    "build_mode": "incremental",
                    "diff": {"added": 0, "removed": 0},
                    "duration_seconds": duration,
                },
                message=f"No changes to apply ({self.total_triple_count} triples unchanged)",
            )
            return False

        progress_base = 45
        is_api_local = self.is_api
        tm_local = self.tm
        task_id_local = self.task_id
        del_total = self.diff_removed_count
        add_total = self.diff_added_count

        if del_total > 0:
            def _on_del_progress(done: int, total: int) -> None:
                if is_api_local:
                    return
                denom = del_total or 1
                p = progress_base + int(done / denom * 20)
                tm_local.update_progress(
                    task_id_local,
                    min(p, progress_base + 20),
                    f"Removed {done}/{denom} triples...",
                )

            if not self.is_api:
                self.tm.update_progress(
                    self.task_id,
                    progress_base,
                    f"Removing {del_total} triples...",
                )
            removed_sql = (
                f"SELECT subject, predicate, object FROM {self.snapshot_table} "
                f"EXCEPT "
                f"SELECT subject, predicate, object FROM {self.view_table}"
            )
            self._stream_triples_out_of_store(
                removed_sql,
                delete_batch_size=5000,
                on_progress=None if self.is_api else _on_del_progress,
            )

        if add_total > 0:
            add_base = progress_base + 25

            def _on_add_progress(done: int, total: int) -> None:
                if is_api_local:
                    return
                denom = add_total or 1
                p = add_base + int(done / denom * 20)
                tm_local.update_progress(
                    task_id_local,
                    min(p, add_base + 20),
                    f"Inserted {done}/{denom} triples...",
                )

            if not self.is_api:
                self.tm.update_progress(
                    self.task_id, add_base, f"Inserting {add_total} triples..."
                )
            added_sql = (
                f"SELECT subject, predicate, object FROM {self.view_table} "
                f"EXCEPT "
                f"SELECT subject, predicate, object FROM {self.snapshot_table}"
            )
            self._stream_triples_into_store(
                added_sql,
                insert_batch_size=5000,
                on_progress=None if self.is_api else _on_add_progress,
            )

        if self.is_api:
            if triple_count > 0:
                self.store.optimize_table(self.graph_name)
        else:
            self.store.optimize_table(self.graph_name)
        return True

    def _refresh_snapshot(self) -> None:
        t_phase = time.time()
        if self._lakebase_managed_synced():
            # In managed_synced mode the Lakeflow snapshot pipeline owns the
            # PG truth and the legacy Delta snapshot is never compared
            # against; skip the CTAS entirely to avoid a redundant warehouse
            # write per build.
            self.tm.skip_step(
                self.task_id,
                "Snapshot table not needed in Lakebase managed-synced mode",
            )
            self._log_phase("snapshot", t_phase)
            return
        snap_step = (
            "Refreshing snapshot..." if self.is_api else "Refreshing snapshot table..."
        )
        self.tm.advance_step(self.task_id, snap_step)
        try:
            self.incr_svc.refresh_snapshot(self.view_table, self.snapshot_table)
            logger.info(
                "[DT-BUILD %s] snapshot table %s refreshed",
                self.task_id,
                self.snapshot_table,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[DT-BUILD %s] failed to refresh snapshot %s (non-fatal): %s",
                self.task_id,
                self.snapshot_table,
                exc,
            )
        self._log_phase("snapshot", t_phase)

    def _persist_source_versions(self) -> None:
        try:
            if self.new_source_versions:
                self.domain.source_versions = self.new_source_versions
                self.domain.save()
                logger.info(
                    "[DT-BUILD %s] persisted %d source-version stamp(s)",
                    self.task_id,
                    len(self.new_source_versions),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[DT-BUILD %s] could not persist source versions: %s",
                self.task_id,
                exc,
            )

    def _populate_session_cache(self) -> None:
        from back.core.graphdb import graph_volume_path
        from back.core.helpers import (
            effective_uc_version_path,
            resolve_ladybug_local_path,
        )
        from back.objects.digitaltwin.DigitalTwin import DigitalTwin

        try:
            final_count = self.total_triple_count or self.triple_count
            build_stamp = self.domain.triplestore.get("build_last_update")

            status_cache = {
                "success": True,
                "has_data": final_count > 0,
                "count": final_count,
                "view_table": self.view_table,
                "graph_name": self.graph_name,
            }
            if build_stamp and final_count > 0:
                status_cache["last_modified"] = build_stamp

            db_name = self.graph_name or DEFAULT_GRAPH_NAME
            local_path = resolve_ladybug_local_path(self.domain, db_name)
            uc_path = effective_uc_version_path(self.domain)
            registry_lbug_path = (
                graph_volume_path(uc_path, db_name) if uc_path else ""
            )

            dt = DigitalTwin(self.domain)
            prev_existence = dt.get_ts_cache("dt_existence") or {}

            existence_cache = {
                "view_exists": True,
                "snapshot_exists": True,
                "snapshot_table": self.snapshot_table,
                "view_table": self.view_table,
                "graph_name": self.graph_name,
                "local_lbug_exists": os.path.exists(local_path),
                "local_lbug_path": local_path,
                "registry_lbug_exists": prev_existence.get("registry_lbug_exists"),
                "registry_lbug_path": registry_lbug_path,
                "last_built": self.domain.last_build,
                "last_update": self.domain.last_update,
            }

            dt.set_ts_cache("status", status_cache)
            dt.set_ts_cache("dt_existence", existence_cache)
            logger.debug("Build cache populated: count=%d", final_count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not populate DT session cache: %s", exc)

    def _start_background_archive(self) -> None:
        from back.core.helpers import make_volume_file_service
        from back.objects.digitaltwin.DigitalTwin import DigitalTwin
        from back.objects.domain import Domain

        t_phase = time.time()
        try:
            graph_engine = DigitalTwin.resolve_graph_engine(self.domain, self.settings)
        except Exception:  # noqa: BLE001
            graph_engine = "ladybug"
        if graph_engine == "lakebase":
            self.tm.advance_step(self.task_id, "Skipping registry backup…")
            self.tm.skip_step(
                self.task_id,
                "Lakebase graph engine — Postgres is the system of record, "
                "no .lbug archive to push to the volume",
            )
            self._log_phase("archive", t_phase)
            return

        archive_task = self.tm.create_task(
            name="Registry Graph Backup",
            task_type="registry_archive",
            steps=[
                {
                    "name": "archive",
                    "description": "Compressing and uploading LadybugDB archive",
                }
            ],
        )
        self.archive_task_id = archive_task.id
        archive_task_id = self.archive_task_id
        domain_local = self.domain
        settings_local = self.settings
        tm_local = self.tm
        parent_task_id = self.task_id

        def _bg_archive() -> None:
            tm_local.start_task(
                archive_task_id,
                "Compressing and uploading graph archive…",
            )
            try:
                uc_svc = make_volume_file_service(domain_local, settings_local)
                warn = Domain(domain_local).sync_ladybug_to_volume(uc_svc)
                if warn:
                    logger.warning("Background graph archive warning: %s", warn)
                    tm_local.complete_task(
                        archive_task_id,
                        result={
                            "warning": warn,
                            "parent_task_id": parent_task_id,
                        },
                        message="Registry backup completed with warning",
                    )
                else:
                    logger.info("Background graph archive finished successfully")
                    tm_local.complete_task(
                        archive_task_id,
                        result={"parent_task_id": parent_task_id},
                        message="Registry backup completed",
                    )
                    try:
                        dt_obj = DigitalTwin(domain_local)
                        ex = dt_obj.get_ts_cache("dt_existence")
                        if ex:
                            ex["registry_lbug_exists"] = True
                            dt_obj.set_ts_cache("dt_existence", ex)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                tm_local.fail_task(archive_task_id, str(exc))
                logger.warning(
                    "Background graph archive failed (non-fatal): %s", exc
                )

        self.tm.advance_step(
            self.task_id,
            "Backing up the graph to the registry in the background…",
        )
        threading.Thread(
            target=_bg_archive,
            name=f"ob-ladybug-archive-{self.task_id}",
            daemon=True,
        ).start()
        self.tm.complete_current_step(
            self.task_id,
            "Build finished — registry backup continues in the background "
            f"(task {archive_task_id})",
        )
        self._log_phase("archive", t_phase)

    def _complete_task(self) -> None:
        duration = time.time() - self.start_time
        logger.info(
            "[DT-BUILD %s] DONE kind=%s domain=%s mode=%s triples=%d "
            "(+%d/-%d) duration=%.2fs phases={%s}",
            self.task_id,
            self.build_kind,
            self.domain_name,
            self.actual_mode,
            self.total_triple_count or self.triple_count,
            self.diff_added_count,
            self.diff_removed_count,
            duration,
            ", ".join(f"{k}={v:.2f}s" for k, v in self.phase_times.items())
            or "n/a",
        )

        result_data: Dict[str, Any] = {
            "triple_count": self.total_triple_count or self.triple_count,
            "view_table": self.view_table,
            "graph_name": self.graph_name,
            "build_mode": self.actual_mode,
            "snapshot_table": self.snapshot_table,
            "duration_seconds": duration,
        }
        if not self.is_api:
            result_data["phase_times"] = self.phase_times
            if self.archive_task_id:
                result_data["archive_background"] = True
                result_data["archive_task_id"] = self.archive_task_id
            else:
                result_data["archive_skipped"] = True
        if self.actual_mode == "incremental":
            result_data["diff"] = {
                "added": self.diff_added_count,
                "removed": self.diff_removed_count,
            }
            msg = (
                f"Incremental: +{self.diff_added_count} / -{self.diff_removed_count} triples in {duration:.1f}s"
                if not self.is_api
                else f"Incremental: +{self.diff_added_count} / -{self.diff_removed_count} in {duration:.1f}s"
            )
        else:
            msg = f"Full rebuild: {self.total_triple_count or self.triple_count} triples in {duration:.1f}s"

        if not self.is_api and self.archive_task_id:
            msg += " Registry backup continues in the background."

        self.tm.complete_task(self.task_id, result=result_data, message=msg)

    def _fail_unexpected(self, exc: Exception) -> None:
        duration = time.time() - self.start_time
        logger.exception(
            "[DT-BUILD %s] FAILED kind=%s domain=%s mode=%s after %.2fs: %s",
            self.task_id,
            self.build_kind,
            self.domain_name,
            self.actual_mode,
            duration,
            exc,
        )
        if self.is_api:
            self.tm.fail_task(self.task_id, str(exc))
        else:
            self.tm.fail_task(self.task_id, "Triple store sync failed")
