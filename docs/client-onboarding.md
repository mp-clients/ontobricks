# Onboarding a New Client

OntoBricks is deployed **per client** (multi-tenant): each client gets its own
Databricks workspace, apps, registry, and a `scripts/deploy.config.<client>.sh`.
This runbook takes a new client from nothing to a working deployment. It mirrors
the path used for the first client (`moneypool`).

> **Naming:** pick a short lowercase `<client>` slug (e.g. `moneypool`). It names
> the deploy config (`scripts/deploy.config.<client>.sh`) and the `CLIENT=` flag.

> **Per-client config is the unit of deployment.** Everything client-specific
> (workspace profile, app names, catalog/schema, warehouse, Lakebase coords) lives
> in `scripts/deploy.config.<client>.sh`. The bundle (`databricks.yml`) stays a
> pure structural declaration — never hard-code client values there.

## Prerequisites
- Databricks CLI ≥ 1.1.0, `uv`, and (for the Lakebase permission grant in step 9)
  `psql` available — run that step from an environment that has it (e.g. the devcontainer).
- The client's Databricks workspace URL, and that Databricks Apps + Lakebase are enabled there.

---

## 1. Authenticate to the client workspace
```bash
databricks auth login --host https://<client-workspace-url> -p <client>
databricks auth describe -p <client>            # confirm Host + User
```
Use the profile name `<client>` consistently (it goes in the deploy config as
`DATABRICKS_CONFIG_PROFILE`).

## 2. Provision a Lakebase Postgres instance
The registry backend is **Lakebase-only since v0.4.0** (no volume fallback), so every
client needs a Lakebase database the app can bind to.
```bash
databricks database create-database-instance <client>-ontology \
  --capacity CU_1 --node-count 1 -p <client> -o json
# poll until state == AVAILABLE:
databricks database get-database-instance <client>-ontology -p <client> -o json
```
Note the default Postgres database name (typically `databricks_postgres`).

## 3. Create the Unity Catalog registry schema + volume
Pick a catalog the client owns (e.g. `sandbox`, `compliance`). The volume holds
binary document uploads; the schema name is also where the Delta triplestore views land.
```bash
databricks schemas create <schema> <catalog> -p <client>
databricks volumes create <catalog> <schema> registry MANAGED -p <client>
```

## 4. Discover the SQL warehouse + decide names
```bash
databricks warehouses list -p <client>     # pick a warehouse → note its ID
databricks catalogs list   -p <client>     # confirm your source/registry catalogs
```
Decide: UI app name, MCP app name, registry catalog/schema/volume, warehouse ID.

## 5. Write `scripts/deploy.config.<client>.sh`
Copy the sandbox config as a starting point and edit the values:
```bash
cp scripts/deploy.config.sh scripts/deploy.config.<client>.sh
```
At minimum set (see `moneypool` for a worked example):
```bash
export DATABRICKS_CONFIG_PROFILE=<client>
export APP_NAME=<ui-app>            # e.g. ontology
export MCP_APP_NAME=<mcp-app>       # e.g. mcp-ontology
export DAB_TARGET=dev-lakebase      # Lakebase backend (required)
export WAREHOUSE_ID=<warehouse-id>
export APP_SQL_WAREHOUSE_FALLBACK=<warehouse-id>
export REGISTRY_CATALOG=<catalog>   REGISTRY_SCHEMA=<schema>   REGISTRY_VOLUME=registry
export APP_REGISTRY_CATALOG=<catalog> APP_REGISTRY_SCHEMA=<schema> APP_REGISTRY_VOLUME=registry
export APP_DATABRICKS_CATALOG=<catalog> APP_DATABRICKS_SCHEMA=<schema>
export APP_TRIPLESTORE_TABLE=<catalog>.<schema>.default_triplestore
# Lakebase (filled in fully after step 7's UI binding reveals the resource path):
export LAKEBASE_PROJECT=<instance-name>          # e.g. moneypool-ontology
export LAKEBASE_BRANCH=production
export LAKEBASE_DATABASE_RESOURCE_SEGMENT=databricks-postgres
export LAKEBASE_REGISTRY_SCHEMA=<pg-registry-schema>   # e.g. ontology_registry
export LAKEBASE_BOOTSTRAP_DATABASE=databricks_postgres
export APP_LAKEBASE_SCHEMA=<pg-registry-schema>
export APP_LAKEBASE_DATABASE=databricks_postgres
export APP_LAKEBASE_PROJECT=<instance-name>
```
The config is gitignored by default (like `scripts/deploy.config.sh`). Keep secrets
out — auth is via the CLI profile, not the file.

## 6. First deploy
```bash
make deploy CLIENT=<client>            # = scripts/deploy.sh -t dev-lakebase, client config
```
**First-deploy "app already exists" fix:** if the apps were created under a different
bundle/target first, DAB will try to *create* them and fail. Bind the existing apps
into the `dev-lakebase` state once, then re-run:
```bash
source scripts/deploy.config.<client>.sh
VARS=(--var=app_name=$APP_NAME --var=mcp_app_name=$MCP_APP_NAME --var=warehouse_id=$WAREHOUSE_ID \
  --var=registry_catalog=$REGISTRY_CATALOG --var=registry_schema=$REGISTRY_SCHEMA --var=registry_volume=$REGISTRY_VOLUME \
  --var=lakebase_project=$LAKEBASE_PROJECT --var=lakebase_branch=$LAKEBASE_BRANCH \
  --var=lakebase_database_resource_segment=$LAKEBASE_DATABASE_RESOURCE_SEGMENT --var=lakebase_registry_schema=$LAKEBASE_REGISTRY_SCHEMA)
databricks bundle deployment bind ontobricks_dev_app  $APP_NAME     -t dev-lakebase --auto-approve "${VARS[@]}"
databricks bundle deployment bind mcp_ontobricks_app  $MCP_APP_NAME -t dev-lakebase --auto-approve "${VARS[@]}"
make deploy CLIENT=<client>
```
The MCP app needs its source deployed too: `databricks bundle run mcp_ontobricks_app -t dev-lakebase "${VARS[@]}"`.

## 7. Bind the Lakebase Postgres resource to the apps (Databricks UI)
The CLI/DAB (v1.1.x) cannot bind a *Database Instance* to an app (its app
`postgres` resource only accepts the legacy `branch`/`database` path), so do it in
the **Apps UI**: open each app → **Edit → Resources → Add → Database** → select the
instance + `databricks_postgres` → permission **`CAN_CONNECT_AND_CREATE`** → Save.
This injects `PGHOST`/`PGUSER`/`PGDATABASE` at runtime.

Then read the resource path back and finalize the config (step 5's Lakebase block):
```bash
databricks apps get $APP_NAME -p <client> -o json | python3 -c \
 "import json,sys;[print(r['postgres']) for r in (json.load(sys.stdin).get('resources') or []) if 'postgres' in r]"
# -> projects/<project>/branches/<branch>/databases/<segment>  -> fill LAKEBASE_* and redeploy
make deploy CLIENT=<client>
```

> ⚠️ **Always deploy this client with the `dev-lakebase` target** (`make deploy CLIENT=<client>`).
> A plain `-t dev` / volume deploy would drop the UI-bound Postgres resource.

## 8. Initialize the registry
In the UI app: **Settings → Registry → Initialize**. With `CAN_CONNECT_AND_CREATE`
the app creates and owns its `<pg-registry-schema>` schema + tables.

## 9. (If needed) grant the app SP on the registry schema
Only needed if a schema was pre-created by someone else, or the MCP app must read
what the UI app created (the UI app owns schemas it creates itself). Requires `psql`:
```bash
make bootstrap-lakebase CLIENT=<client>
```

## 10. Post-deploy verification
```bash
databricks apps get $APP_NAME     -p <client> -o json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['name'],(d.get('app_status') or {}).get('state'))"
databricks apps get $MCP_APP_NAME -p <client> -o json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['name'],(d.get('app_status') or {}).get('state'))"
curl -s -o /dev/null -w "%{http_code}\n" https://<ui-app-url>/healthz   # expect 200
```
Confirm in **Compute → Apps → <app> → Resources** that the SQL warehouse, volume,
and Postgres resource are bound.

## 11. (Optional) enable the LLM auto-pipeline
For the 4-step Generate-Ontology / Auto-Map / Sync flow, grant the app's service
principal **read** on the client's source catalog (`USE_CATALOG`, `USE_SCHEMA`,
`SELECT`) and **`CREATE_TABLE`/`MODIFY`/`SELECT`** on the registry schema (for the
Delta triplestore). Databricks **foundation models** (`databricks-claude-*`,
`databricks-gpt-*`) need **no** `CAN_QUERY` grant — they're queryable by any
workspace principal. Select the model in the app's **Settings**.

---

## Quick reference — everyday commands (per client)
```bash
make deploy        CLIENT=<client>   # deploy + start (dev-lakebase)
make deploy-no-run CLIENT=<client>   # deploy artifacts only
make bundle-validate CLIENT=<client> # validate the bundle
make bundle-summary  CLIENT=<client> # preview what deploys
make bootstrap-lakebase CLIENT=<client>  # grant SP on the registry PG schema (needs psql)
```
Omit `CLIENT=` to act on the default sandbox config (`scripts/deploy.config.sh`).
