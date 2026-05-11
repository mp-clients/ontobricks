"""Factory for creating graph database backends from domain session configuration.

Supports ``"ladybug"`` (embedded LadybugDB) and ``"lakebase"`` (flat triple
tables on Lakebase Postgres).  The *engine_config* JSON is engine-specific
(admin: Settings → Graph DB).
"""

from typing import Any, Callable, Dict, Optional, Tuple

from back.core.databricks import is_databricks_app
from back.core.helpers import (
    effective_uc_version_path,
    get_databricks_host_and_token,
)
from back.core.logging import get_logger
from shared.config.constants import DEFAULT_GRAPH_NAME, DEFAULT_LADYBUG_PATH

logger = get_logger(__name__)


class GraphDBFactory:
    """Construct graph DB backend instances from domain session configuration."""

    LADYBUG_AVAILABLE = False
    LAKEBASE_AVAILABLE = False

    def create(
        self,
        domain: Any,
        settings: Optional[Any] = None,
        engine: Optional[str] = None,
        engine_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Create a graph DB backend.

        Args:
            domain: Domain session with info and databricks config.
            settings: Optional application settings.
            engine: ``"ladybug"`` (default) or ``"lakebase"``.
            engine_config: Engine-specific JSON configuration set by the
                           admin in Settings > Graph DB.

        Returns:
            GraphDBBackend instance or *None* if configuration is incomplete.
        """
        if engine is None:
            engine = "ladybug"
        if engine_config is None:
            engine_config = {}

        if engine == "ladybug":
            return self._create_ladybug(domain, settings, engine_config=engine_config)

        if engine == "lakebase":
            return self._create_lakebase(domain, settings, engine_config=engine_config)

        logger.warning("Unknown graph DB engine: %s", engine)
        return None

    @staticmethod
    def _build_auto_restore(
        domain: Any,
        settings: Optional[Any],
        db_name: str,
        db_path: str,
    ) -> Optional[Callable[[], Tuple[bool, str]]]:
        """Build a callback that restores a graph DB file from the registry.

        Returns *None* when the registry or Databricks credentials are
        not configured — in that case auto-restore is simply disabled.
        """
        uc_domain_path = effective_uc_version_path(domain)
        if not uc_domain_path:
            return None

        if settings is not None:
            host, token = get_databricks_host_and_token(domain, settings)
        else:
            db_cfg = getattr(domain, "databricks", None) or {}
            host = db_cfg.get("host", "")
            token = db_cfg.get("token", "")

        if not host and not is_databricks_app():
            return None
        if not token and not is_databricks_app():
            return None

        def _restore() -> Tuple[bool, str]:
            from back.core.databricks import VolumeFileService
            from back.core.graphdb.ladybugdb.GraphSyncService import GraphSyncService

            uc = VolumeFileService(host=host, token=token)
            svc = GraphSyncService(uc, db_name, local_base=db_path)
            return svc.sync_from_volume(uc_domain_path)

        return _restore

    def _create_ladybug(
        self,
        domain: Any,
        settings: Optional[Any] = None,
        *,
        engine_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Instantiate a LadybugDB store, choosing graph or flat model."""
        try:
            db_path = DEFAULT_LADYBUG_PATH
            base_name = (domain.info or {}).get("name", DEFAULT_GRAPH_NAME)
            version = getattr(domain, "current_version", "1") or "1"
            db_name = f"{base_name}_V{version}"
            ontology = getattr(domain, "ontology", None)
            if callable(ontology):
                ontology = None

            auto_restore = self._build_auto_restore(
                domain,
                settings,
                db_name,
                db_path,
            )

            if ontology:
                from back.core.graphdb.ladybugdb.LadybugGraphStore import (
                    LadybugGraphStore,
                )

                return LadybugGraphStore(
                    db_path=db_path,
                    db_name=db_name,
                    ontology=ontology,
                    auto_restore=auto_restore,
                )
            else:
                from back.core.graphdb.ladybugdb.LadybugFlatStore import (
                    LadybugFlatStore,
                )

                return LadybugFlatStore(
                    db_path=db_path,
                    db_name=db_name,
                    auto_restore=auto_restore,
                )
        except ImportError as e:
            logger.warning("LadybugDB requires real_ladybug: %s", e)
            return None
        except Exception as e:
            logger.exception("Failed to create LadybugDB store: %s", e)
            return None

    def _create_lakebase(
        self,
        domain: Any,
        settings: Optional[Any] = None,
        *,
        engine_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Instantiate :class:`LakebaseFlatStore` on the bound Lakebase instance."""
        try:
            from back.core.graphdb.lakebase import LAKEBASE_AVAILABLE
            from back.core.graphdb.lakebase.LakebaseBase import (
                DEFAULT_GRAPH_SCHEMA,
            )
            from back.core.graphdb.lakebase.LakebaseFlatStore import (
                LakebaseFlatStore,
                SYNC_MODE_APP,
                SYNC_MODE_MANAGED,
                resolve_lakebase_graph_schema,
            )
            from back.core.graphdb.lakebase.SyncedTableManager import (
                DEFAULT_TIMEOUT_S as _SYNC_DEFAULT_TIMEOUT_S,
            )
            from back.core.databricks import get_lakebase_auth
        except ImportError as e:
            logger.warning("Lakebase graph engine requires psycopg: %s", e)
            return None

        if not LAKEBASE_AVAILABLE:
            logger.warning("Lakebase graph backend unavailable (psycopg not installed)")
            return None

        cfg = engine_config or {}
        schema_raw = cfg.get("schema") or DEFAULT_GRAPH_SCHEMA
        database_override = str(cfg.get("database") or "").strip()
        sync_mode = str(cfg.get("sync_mode") or SYNC_MODE_APP).strip() or SYNC_MODE_APP
        if sync_mode not in (SYNC_MODE_APP, SYNC_MODE_MANAGED):
            logger.warning(
                "Unknown sync_mode %r in graph_engine_config — falling back to %s",
                sync_mode,
                SYNC_MODE_APP,
            )
            sync_mode = SYNC_MODE_APP
        sync_table_mode = str(cfg.get("sync_table_mode") or "snapshot").strip() or "snapshot"
        sync_timeout_s = int(cfg.get("sync_timeout_s") or _SYNC_DEFAULT_TIMEOUT_S)
        sync_uc_catalog = str(cfg.get("sync_uc_catalog") or "").strip()

        try:
            schema = resolve_lakebase_graph_schema(domain, settings, str(schema_raw))
        except ValueError as exc:
            logger.warning("Invalid lakebase graph schema: %s", exc)
            return None

        try:
            auth = get_lakebase_auth()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lakebase auth unavailable for graph engine: %s", exc)
            return None

        if not getattr(auth, "is_available", False):
            logger.warning(
                "Lakebase graph engine selected but PGHOST/PGUSER are not configured"
            )
            return None

        synced_manager = None
        if sync_mode == SYNC_MODE_MANAGED:
            synced_manager = self._build_synced_manager(
                auth, database_override
            )
            if synced_manager is None:
                logger.warning(
                    "managed_synced requested but SyncedTableManager could not be built — "
                    "falling back to app_managed for this store"
                )
                sync_mode = SYNC_MODE_APP

        try:
            return LakebaseFlatStore(
                auth,
                schema=schema,
                database_override=database_override,
                sync_mode=sync_mode,
                sync_table_mode=sync_table_mode,
                sync_timeout_s=sync_timeout_s,
                sync_uc_catalog=sync_uc_catalog,
                synced_manager=synced_manager,
            )
        except Exception as e:
            logger.exception("Failed to create Lakebase graph store: %s", e)
            return None

    @staticmethod
    def _build_synced_manager(auth: Any, database_override: str) -> Optional[Any]:
        """Resolve Lakebase project_id + logical DB name and build a SyncedTableManager.

        Returns *None* if either piece is missing -- callers should fall back
        to ``app_managed`` and surface a warning rather than aborting the
        store construction.
        """
        try:
            from back.core.graphdb.lakebase.SyncedTableManager import (
                SyncedTableManager,
            )

            instance_name = auth.instance_name  # raises ValidationError on miss
            logical_db = (database_override or auth.database or "").strip()
            if not instance_name or not logical_db:
                return None
            return SyncedTableManager(
                database_instance_name=instance_name,
                logical_database_name=logical_db,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not build SyncedTableManager (%s) — managed_synced disabled "
                "for this store",
                exc,
            )
            return None

    @classmethod
    def get_graphdb(
        cls,
        domain: Any,
        settings: Optional[Any] = None,
        engine: Optional[str] = None,
        engine_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Convenience wrapper using the package singleton factory instance."""
        return _get_factory_singleton().create(
            domain,
            settings=settings,
            engine=engine,
            engine_config=engine_config,
        )


_factory_singleton: Optional[GraphDBFactory] = None


def _get_factory_singleton() -> GraphDBFactory:
    global _factory_singleton
    if _factory_singleton is None:
        _factory_singleton = GraphDBFactory()
    return _factory_singleton


try:
    from back.core.graphdb.ladybugdb.LadybugFlatStore import (
        LadybugFlatStore,
    )  # noqa: F401
    from back.core.graphdb.ladybugdb.LadybugGraphStore import (
        LadybugGraphStore,
    )  # noqa: F401

    GraphDBFactory.LADYBUG_AVAILABLE = True
except ImportError:
    logger.debug("LadybugDB backends not available (optional dependency)")

try:
    from back.core.graphdb.lakebase import LAKEBASE_AVAILABLE as _LB_AVAIL  # noqa: F401

    GraphDBFactory.LAKEBASE_AVAILABLE = bool(_LB_AVAIL)
except ImportError:
    logger.debug("Lakebase graph backends not available (optional dependency)")
