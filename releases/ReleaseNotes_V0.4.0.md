# OntoBricks — Release Notes V0.4.0

**Release window:** May, 2026
**Test status:** all changes shipped with the suite green (≥ 2003 passing, 80 skipped).

---

## Highlights

- **Lakebase GraphDB engine (full)**: Postgres-backed triple store via Databricks Lakebase Autoscaling completely replaces LadybugDB as the primary graph backend. Synchronization can be done in two (load) modes 
  — `app_managed` (direct streaming into Postgres) 
  — `managed_synced` (Lakeflow-managed Unity Catalog synced-table pipeline). 
  Both modes share the same 3-object Postgres layout (`*_sync` + `*__app` companion + union view).
- **Managed Sync pipeline end-to-end**: `SyncedTableManager` handles UC synced-table registration, Lakeflow pipeline polling, ghost control-plane state recovery, union-view creation, and all downstream Digital Twin build steps — with live progress visible in the app log and Build page.
- **Registry OBX Export / Import**: Export one or several registry domains to a single `.obx` (JSON) file with per-domain version-mode selection; import with per-domain Skip / Overwrite / Rename conflict resolution. Format-version gating ensures future backward compatibility.
- **Ontology Pitfalls Detector**: D2KLab's OPD (Apache-2.0) integrated as a new Ontology sidebar panel. Detects 19 structural, logical, and semantic pitfalls across four categories, powered by an async TaskManager job. ML-heavy checks can be enabled optionally via `[pitfalls]` extra.
- **HL7 FHIR R5 / R4B / R4 industry import**: FHIR added as a fourth importable ontology alongside FIBO, CDISC, and IOF. OWL restriction-based property extraction, six domain buckets (Foundation required + Clinical/Diagnostics/Medications/Workflow/Financial), user-selectable version.
- **Ontology labels throughout**: Labels (with name fallback) now propagate to the KG detail panel, graph-chat agent responses, MCP tool outputs, ontology viewer link labels, and entity-type / predicate columns.
- **Security**: Closed urllib3 GHSA-mf9v / GHSA-qccp (#27, #28) by bumping to 2.7.0; GitPython bumped to 3.1.50 for GHSA-x2qx (CVE-2026-42215 follow-on); Mako ≥ 1.3.12, python-multipart ≥ 0.0.27 retained from v0.3.x.
- **CI simplification**: Sphinx HTML build removed from CI; generated artifacts gitignored; `scripts/build_docs.sh` retained for local on-demand builds.

---

## Lakebase GraphDB Engine

- New pluggable graph backend (`graph_engine = "lakebase"`) alongside LadybugDB. Selected in **Settings → Graph DB**.
- Process-wide Postgres connection pool with JWT-aware Lakebase auth (`lakebase/pool.py`).
- `LakebaseFlatStore` implements DDL (triple table + `datatype`/`lang` RDF columns), CRUD, `VACUUM ANALYZE` optimize, bounded-memory `bulk_insert_iter`, keyed-pagination `iter_triples`, `_sql_relation` override for physical vs logical table name handling.
- Factory-only dispatch (`GraphDBFactory._create_lakebase`): Ladybug and Lakebase are mutually exclusive; engine config validated on save.
- `LAKEBASE_AVAILABLE` capability flag; `TripleStoreFactory` includes Lakebase in availability detection.
- Reference DDL: `src/back/core/graphdb/lakebase/schema.sql`; autodoc page: `docs/sphinx/api/app.core.graphdb.lakebase.rst`.

### App-managed companion layout

- `app_managed` builds now use the same 3-object Postgres layout as `managed_synced`:
  - `*_sync` — bulk warehouse data (streamed by the build pipeline)
  - `*__app` — companion (reasoning / materialise writes)
  - union view — single read surface
- `LakebaseFlatStore.bulk_load_into_sync()` for the build pipeline; `_writable_table_id()` always returns companion (`*__app`).
- `drop_table()` cleans up all 3 objects; `optimize_table()` vacuums both `*_sync` and `*__app`.

### Settings — Graph DB tab

- **Cascading Lakebase pickers**: Project → Branch → Database → Schema (with manual pencil override). UC catalog picker triggers a UC schema picker for Managed Sync configuration.
- **Health probe** (`GET /settings/graph-engine/lakebase-health`): uses `pg_catalog` queries (privilege-independent) and the same `resolve_lakebase_graph_schema` logic as the build pipeline.
- **Loading spinner** while Graph DB tab data fetches.
- **Live UC synced-table name preview** (Settings → Managed Sync panel) showing all 4 Postgres / UC object names before the first build.
- **Lakebase Objects panel**: lists all user-visible schemas, tables, and views in the configured database; Drop button (owner-only, Bootstrap confirm modal) for objects the service principal owns.
- Local Graph Files panel hidden when Lakebase is selected (shows only for LadybugDB).
- `GET /settings/graph-engine` and `GET /settings/graph-engine-config` now allowed for all app users (POST remains admin-only).
- Graph engine choice persisted in `global_config.config` under `graph_engine` / `graph_engine_config` and mirrored into the domain registry entry.

### Schema resolution

- `resolve_lakebase_graph_schema`: explicit `graph_engine_config.schema` wins; falls back to Registry Volume schema; then `DEFAULT_GRAPH_SCHEMA` (`ontobricks_graph`).
- `resolve_lakebase_graph_database`: explicit `graph_engine_config.database` wins; falls back to `RegistryCfg.lakebase_database`; then auth default.
- UC sync FQN (`synced_uc_name`) always uses the registry UC schema (`RegistryCfg.schema`) so the Lakeflow synced object lands in the same Unity Catalog namespace as all other registry artefacts.

---

## Managed Sync / Lakeflow Pipeline

- `SyncedTableManager`: handles UC synced-table registration, trigger (full refresh), Lakeflow pipeline polling (`wait_for_completion` via `get_update(update_id)` + idle-wait fallback), `on_state_change` callback for live task context updates.
- `_normalize_state` strips `SYNCED_TABLE_` prefix from SDK enum names so terminal/in-progress sets match correctly.
- Ghost control-plane state recovery: when a previous synced-table was deleted outside the API, `_is_ghost_control_plane_state` detects the conflict; `ensure()` tries `DELETE` then re-CREATE, with `_b/c/d` fallback names if the primary slot is permanently reserved.
- `ensure_synced_union_view()` runs after Lakeflow materializes `*_sync`; schema-qualifies the `_sync` reference when Postgres and UC schemas differ; drops existing table with same name before creating view.
- `auto-repair`: if the union view is absent (crashed previous build), `repair_synced_view_if_possible` recreates it from the existing `*_sync`/`*__app` objects.
- Synced table payload uses `database_instance_name` (project) + `database_branch` + `logical_database_name` (required by the Lakebase Synced Tables API for Autoscaling projects).
- `LakebaseAuth.branch_name` property parses the branch segment from the PGHOST endpoint resource path.
- Build pipeline: stores `lakebase_synced_uc` / `lakebase_pipeline_id` in task context; frontend polls `/dtwin/sync/pipeline-status` every 6 s; 30-second terminal-OK grace window before build is declared complete.
- `SELECT DISTINCT` fix in R2RML-to-Spark SQL templates to prevent duplicate triples causing Lakeflow PK violations.
- UC schema auto-created (`CREATE SCHEMA IF NOT EXISTS`) before synced-table registration, with `conn.commit()` after DDL.

---

## Digital Twin Build — UI & UX

- Build page Graph DB card: compact in-card build note showing `database.schema.table`; existence badges for `dtLakebaseTableExists` and `dtLakebaseSyncedUcExists`; Lakeflow line shows `catalog.schema.<physical_table>_sync`.
- Build log card: engine-specific title, Lakebase Pipeline UC FQN, `archive` step hidden for Lakebase builds.
- "Backing up graph to registry" archive step removed entirely for Lakebase deploys (no Volume backup needed).
- Post-build session cache (`_populate_session_cache`): Lakebase path sets `graph_has_data = final_count > 0`, `graph_engine`, `registry_archive_applicable = False`; LadybugDB path unchanged.
- Per-section `_ts` cache timestamp prevents cross-section staleness (previously a shared clock caused "Loaded" badge + "not built" text contradiction).
- Triplestore stats cache schema version (`_TS_STATS_CACHE_SCHEMA_VERSION = 2`) invalidates old formatted strings on upgrade.
- Legacy `local_lbug_exists` / `local_lbug_path` field names retired; renamed to `graph_has_data` / `graph_display` throughout backend, build pipeline, and frontend.

---

## Cockpit (Domain Validation)

- Graph DB card parity with the Build page: Database / Schema / Table / UC sync row layout; `psDtLakebaseTableExists` and `psDtLakebaseSyncedUcExists` existence badges.
- `HomeService.dtwin_detail` enriched with all lakebase fields (`lakebase_table_exists`, `lakebase_database`, `lakebase_schema`, `lakebase_table`, `lakebase_synced_uc`, `lakebase_sync_mode`).
- `triple_count` prefers `dt_existence` over `ts_status` for accuracy.

---

## Registry OBX Export / Import

- New `src/back/objects/registry/obx_format.py`: `CURRENT_OBX_FORMAT_VERSION = 1`, upgrader-chain pattern, `build_envelope()`, `load()` with format-version validation and `min_ontobricks_version` gate.
- Export modes per domain: `all`, `active`, `latest`, `selected` (per-version checkboxes).
- Import: preview step shows per-domain conflict flags + suggested rename; apply step resolves each domain with `skip` / `overwrite` / `rename`. 50 MB upload cap.
- UI: Export modal (per-domain checkboxes + version mode selector) and Import modal (2-step: file picker → preview → decisions) on Registry → Browse page.

---

## Ontology Pitfalls Detector

- `src/back/core/external/pitfalls/` subpackage (vendored D2KLab OPD, Apache-2.0): `OntologyPatternToolkit` with 19 `run_p*` methods across P1–P4 categories; `PitfallsService` entry point serializes the rdflib Graph to temp TTL and returns grouped results.
- Optional `[pitfalls]` extra in `pyproject.toml`: sentence-transformers, scikit-learn, NLTK, SciPy. ML imports inside `try/except` so taxonomy constants remain accessible without ML deps.
- Three API routes: `GET /ontology/pitfalls/taxonomy`, `POST /ontology/pitfalls/analyze` (async via TaskManager), `GET /ontology/pitfalls/results/{task_id}`.
- New Ontology sidebar panel ("Pitfalls"): pattern selector with ⚡ (graph-only) and 💻 (ML-required) speed icons, Bootstrap tooltip per check, progress bar, accordion results by category.
- `scripts/start.sh` and `requirements.txt` updated to include `--extra pitfalls` alongside `--extra lakebase`.
- Licenses documented: sentence-transformers (Apache-2.0), scikit-learn (BSD-3-Clause), NLTK (Apache-2.0), SciPy (BSD-3-Clause), D2KLab vendored code (Apache-2.0).

---

## HL7 FHIR Industry Ontology

- `src/back/core/industry/fhir/FhirImportService.py`: `FHIR_DOMAINS` catalog (6 domain groups), `_fetch_fhir_ttl(version)`, `_build_allowed_resources()` (always includes `_FHIR_COMPLEX_TYPES`), OWL restriction-based property extraction via `_extract_properties_from_restrictions`.
- Multi-version support: R4, R4B, R5 (default). `GET /ontology/fhir-versions`; version threaded through fetch, transform, and import.
- Base hierarchy stubs: `Base → Resource → DomainResource`, `Base → Element → DataType / BackboneElement / BackboneType` always injected to avoid dangling parent references.
- Self-referencing `fhir:Resource` bug fixed (parent initialised to `""`, not `"Resource"`); non-FHIR-namespace `rdfs:subClassOf` URIs (w5:, rim:, dc:) skipped during parent resolution.
- Import UI: FHIR tab added alongside FIBO/CDISC/IOF; version dropdown (R4/R4B/R5); Foundation required guard uses `showConfirmDialog` (not native `confirm()`).
- All four import handlers (FIBO, CDISC, FHIR, IOF) now use `showConfirmDialog` for Databricks Apps compatibility.

---

## Cohort Discovery

- `CohortBuilder._resolve_predicate`: BFS predicate alias map — resolves predicates in ontology namespace (`#` form) to data namespace (`/` form), then falls back to alias map by local name for cross-namespace predicates (e.g. `ontobricks.com/ontology#hasclaim` in a domain with a different base URI). Fixes silent zero-neighbour results for direct inserts and W3C OWL round-trips.
- `_outgoing_edge_index` normalises every triple predicate with `_resolve_predicate` before indexing.
- Cohort UI: `_dataPropsForClass(classUri)` filters attribute dropdown to the hop-target entity's own data properties (was showing all properties).
- Trace diagnostics: `in_frontier === 0` guard prevents wrong "no neighbours" blame when the frontier is empty.
- Synthetic test data (`data/customer/generate_data.py`): shared electricity contract pool (40 slots, 35% pool share rate) ensures multi-customer contract nodes exist for cohort edge formation; `%s` → `?` parameter placeholder fix for Databricks SQL connector.
- NL agent "Describe (prompt)" tab removed from Cohorts to simplify the workflow.

---

## Knowledge Graph & Inference

- SWRL inference SQL: `build_inference_sql` now uses BFS traversal (`find_connected_vars` + `order_connected_props`) for chained property atoms, matching `build_violation_sql`. Fixes `'' AS object` in multi-hop rules → 0 triples reaching Lakebase.
- After `materialize_graph` success (count > 0), `SigmaGraph.refreshCurrentExpansion()` auto-reloads the visible graph; if no filter active, inline hint points to the KG tab. Zero-triples result badge changed from green OK to yellow Warning for non-HTTP(S) URI schemes.
- Entity-type dropdown loop fixed: removed `data-sg-change="populateFilterEntityTypes"` that re-triggered the fetch on selection.
- `TripleStoreBackend.find_seed_subjects` now treats `field="any"` as union of label-match and URI-match, matching the LadybugDB Cypher implementation.
- KG right pane: incoming / outgoing predicate labels resolved via `findOntologyProperty` (label → name → raw fallback).
- KG page bottom cut off fixed: `.sidebar-content:has(#sigmagraph-section.active)` strips container padding; section uses `height: 100%`.

---

## Ontology Designer UX

- **Label preservation on save**: `saveSharedEntity` / `saveSharedRelationship` copy `existing.uri` into the updated object before overwriting, preventing `prune_mappings_to_ontology_uris` from treating the mapping as orphaned.
- **Mapping designer crash fixed**: `mapping-import.js` top-level `getElementById(...).addEventListener(...)` calls changed to optional chaining (`?.`) to prevent null-dereference crashes in Databricks Apps.
- **Inheritance + relationship link resolution**: `resolveNodeId()` helper in `mapping-design.js` tries exact match, case-insensitive match, and URI local-part extraction, fixing missing links after OWL imports with unnormalized parent/domain/range values.
- **Active tab persistence**: `_entityPanelActiveTab` / `_relPanelActiveTab` remember the last active tab (Details / Attributes / Actions / Constraints / etc.) across entity/relationship selections in the designer right pane.
- **Ontology viewer labels**: link objects carry `label: prop.label || prop.name`; link text uses the label.
- **`findOntologyProperty` no longer requires label** (label-only guard removed); callers decide the fallback.

---

## Settings & Deployment

- **Three-schema Lakebase permission bootstrap**: `scripts/deploy.config.sh` adds `LAKEBASE_GRAPH_PROJECT/BRANCH/DATABASE` (separate graph instance) and `LAKEBASE_SYNC_SCHEMA` (managed_synced schema). `scripts/deploy.sh` calls `bootstrap-lakebase-perms.sh` for each of the three schemas (registry, graph, sync).
- **`scripts/setup-lakebase.sh`** (new): creates a Lakebase project via `POST /api/2.0/database/instances` (Synced Tables-compatible API), waits for AVAILABLE, creates the Postgres database, and prints the `db-…` segment for `deploy.config.sh`. Mandatory for new projects — UI "New project" button uses a different API incompatible with Synced Tables.
- `docs/deployment.md`: added Step 0 (new-workspace setup), Step 5.1b, `setup-lakebase.sh` reference in checklists.
- `docs/lakebase-graphdb.md` (new): architecture overview, prerequisites, provisioning guide, all config keys, write modes comparison, Postgres schema layout, scripts reference, permissions bootstrap order, Digital Twin build steps, troubleshooting section.
- UC catalog/schema dropdown warehouse-ID fallback: uses `settings.sql_warehouse_id` (env-injected from `sql-warehouse` binding) when global config has not been saved yet.
- `scripts/setup.sh` and `scripts/start.sh` migrated from `uv pip install -e ".[lakebase]"` to `uv sync --extra lakebase,pitfalls`.

---

## CI & Developer Experience

- **Sphinx removed from CI**: `docs:` job removed from `.github/workflows/ci.yml`; `docs/sphinx/_build/` gitignored and 283 stale artifacts removed from the index. Sources and `scripts/build_docs.sh` retained for local on-demand builds.
- `tests/test_settings_lakebase_tier.py` deleted (private methods removed in earlier refactor).
- `tests/test_build_pipeline_streaming.py`: migrated `patch(string)` class/module path collisions to `patch.object` for Python 3.9 compatibility.

---

## Security

- **urllib3 2.7.0**: closes GHSA-mf9v-mfxr-j63j (decompression bomb) and GHSA-qccp-gfcp-xxvc (header forwarding on redirect). Wheel fetched from pythonhosted.org via `UV_FIND_LINKS` until proxy indexes it; lock entries reference canonical URLs.
- **GitPython 3.1.50**: closes GHSA-x2qx / CVE-2026-42215 follow-on (newline injection in `config_writer()` section param bypasses 3.1.49 patch).
- **Mako ≥ 1.3.12** (retained): CVE-2026-44307 / GHSA-2h4p TemplateLookup path traversal on Windows.
- **python-multipart ≥ 0.0.27** (retained): CVE-2026-42561, unbounded multipart part-header DoS.
- `scripts/dl-vuln-fix-wheels.sh` (temporary proxy workaround) removed once proxy indexes both packages.

---

## Code Review Fixes

- `tests/test_build_pipeline_streaming.py`: deleted dead `TestStartBackgroundArchive` class (called removed method, was causing a hard failure).
- `src/api/routers/internal/domain.py:90`: fixed `{"success": False}` for the no-Databricks-client case (unconfigured connection is not an error).
- `src/api/routers/internal/settings.py`: import from package (`from back.objects.domain import SettingsService`) not internal module.
- `src/api/routers/internal/dtwin.py`: `HomeService` and `Domain` promoted to top-level imports; `str | None` union syntax replaced with `Optional[str]` for Python 3.9 compatibility.

---

## Upgrade Notes

- **Lakebase project provisioning**: if you created your Lakebase project via the Databricks UI "New project" button, it is not compatible with the Synced Tables API. Re-provision using `scripts/setup-lakebase.sh` — see `docs/lakebase-graphdb.md §Prerequisites`.
- **Three-schema permission bootstrap**: run `make bootstrap-lakebase` after every deploy. If you use `managed_synced` mode, set `LAKEBASE_SYNC_SCHEMA` in `deploy.config.sh` and the deploy script will grant the third schema automatically.
- **Graph DB schema field is now authoritative**: if you have `graph_engine_config.schema` set in Settings → Graph DB, it takes precedence over the Registry Volume schema. Verify your Postgres schema matches what is shown in the Settings → Graph DB health card.
- **`local_lbug_exists` / `local_lbug_path` renamed**: any custom monitoring or integration consuming the `/dtwin/sync/info` response must switch to `graph_has_data` and `graph_display`.
- **`[pitfalls]` optional extra**: Pitfalls detection requires `uv sync --extra pitfalls` (or `pip install ".[pitfalls]"`). The panel will show a warning banner if ML deps are absent and only graph-only checks will run.
- **FHIR import (new)**: available immediately; Foundation domain group is always included; select version (R4/R4B/R5) in the import UI before clicking Import.
- **OBX export/import**: new Export / Import buttons appear on Registry → Browse. No migration required for existing domains.
