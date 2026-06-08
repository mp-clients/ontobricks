# Kinetic Overlay Read-Back — Design (Slice 2)

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan
**Branch base:** `mp/master` (carries kinetic slice 1)
**Spec it builds on:** `docs/superpowers/specs/2026-06-08-kinetic-action-layer-design.md`

## Goal

Close the visible loop of the kinetic layer: expose **overlay-backed read-back
fields** on the per-domain GraphQL object types, so after an Action is applied,
`query { customer(id:"C1") { riskFlag } }` reflects the overlay value. This was
the one intentional gap deferred from slice 1 (the resolver
`make_overlay_field_resolver` exists + is unit-tested, but no schema field is
wired to it).

Make it **general and ActionType-declared**: any registered Action's written
properties become readable automatically — not a one-off `riskFlag` hack.

## Context (current state)

- `back/objects/actions/` (slice 1): `ActionType` ABC + `ActionRegistry`
  (`default_registry`), `OverlayStore(domain).current_value(cur, object_type,
  object_id, prop)`, `ActionService`, GraphQL `flagCustomerHighRisk` mutation.
- `GraphQLSchemaBuilder` builds per-domain schemas: `_create_python_classes`
  (plain classes with `__annotations__` + defaults) → `_add_relationship_annotations`
  → `_apply_strawberry_types` (freezes each class with `strawberry.type()`) →
  `_build_query` (+ `_build_mutation` when kinetic factories present). The schema
  is cached per `(domain, ontology_hash + "-m" if mutations)`.
- `ResolverFactory.make_overlay_field_resolver(store, connect, object_type, prop)`
  exists and is unit-tested by **direct call** — but its inner `def resolver(root):`
  has **no return annotation**, so it cannot be used in a real strawberry field
  (same failure class as the slice-1 mutation bug:
  `MissingArgumentsAnnotationsError` / `UnresolvedFieldTypeError`).
- The route already builds a `connect` (registry Lakebase pool `connection`) and
  passes `service_factory`/`ctx_factory` to `build_for_domain` when Lakebase is
  reachable.

## Decision

**Approach A — ActionType declares its overlay fields.** Each `ActionType`
declares the property names it writes on its `object_type`; the registry
aggregates; the schema builder attaches a resolver-backed JSON field per
`(object_type, property)`. Rejected: a separate central declaration (drifts from
the Actions that write the data); runtime `apply()` introspection (not static).

## Components

**1. `ActionType.overlay_fields: list[str] = []`** (`action_type.py`)
Default empty (no breakage to existing types). Property names the Action writes
on its `object_type`. `FlagCustomerHighRisk.overlay_fields = ["riskFlag"]`.

**2. `ActionRegistry.overlay_fields_by_type() -> dict[str, set[str]]`** (`registry.py`)
Aggregates across registered types: for each type `t`, for `p in t.overlay_fields`,
add `p` to `result[t.object_type]`. Returns `{}` when nothing declared.

**3. Fix `make_overlay_field_resolver`** (`ResolverFactory.py`)
Annotate the resolver so strawberry can build it:
```python
from strawberry.scalars import JSON
...
def resolver(root) -> Optional[JSON]:
    object_id = getattr(root, "id", None)
    if object_id is None:
        return None
    try:
        with connect() as conn, conn.cursor() as cur:
            return store.current_value(cur, object_type, str(object_id), prop)
    except Exception as exc:            # one field failing must not break the query
        logger.warning("overlay field %s.%s read failed: %s", object_type, prop, exc)
        return None
```
`JSON` because overlay values are arbitrary dicts (e.g. `{"severity","reason"}`).

**4. `GraphQLSchemaBuilder._add_overlay_fields(py_classes, overlay_map, domain, connect)`**
New step **after** `_add_relationship_annotations`, **before** `_apply_strawberry_types`.
For each `object_type` in `overlay_map` that exists in `py_classes`, for each prop
not already an attribute: set the class annotation to `Optional[JSON]` and set the
attribute to `strawberry.field(resolver=ResolverFactory.make_overlay_field_resolver(
OverlayStore(domain), connect, object_type, prop))`.

**5. Wiring** (`GraphQLSchemaBuilder.build_for_domain` + the GraphQL route)
Add `overlay_connect=None` to `build_for_domain` (threaded to `_build`). When
`overlay_connect` is not None AND `default_registry.overlay_fields_by_type()` is
non-empty, run `_add_overlay_fields(..., domain, overlay_connect)`. The route
passes `overlay_connect=connect` (the same `connect` it builds for the mutation
factories). Attachment therefore only happens on the mutation-capable schema,
which already has the distinct `"-m"` cache key — no new cache bug. `connect` is
the stable process-wide pool connection, so baking it into a cached resolver is safe.

## Data flow

```
query { customer(id: "C1") { riskFlag } }
  → Customer.riskFlag resolver (root.id = "C1")
  → with connect() as conn: OverlayStore("customers").current_value(cur, "Customer", "C1", "riskFlag")
  → {"severity": "high", "reason": "..."}  (or null if no active overlay / read error)
```
End-to-end: after `flagCustomerHighRisk` is proposed **and approved** (overlay
ACTIVE), `customer { riskFlag }` returns the value; before approval / after revert,
it returns null.

## Error handling

- Resolver `connect`/read failure → `null` + a `logger.warning` (never raises into
  the query; other fields keep resolving).
- `object` has no `id` → `null`.
- No overlay fields declared, or `overlay_connect` absent → builder skips the step
  entirely (query-only schema unchanged; existing callers unaffected).

## Testing

- **Unit:** `ActionRegistry.overlay_fields_by_type()` aggregation (incl. empty,
  multiple types, multiple props); `FlagCustomerHighRisk.overlay_fields == ["riskFlag"]`.
- **Resolver:** returns the store value for an object with `.id`; returns `None`
  for missing id and on a raising `connect` (error isolation).
- **Schema build *through strawberry* (regression):** build a domain-shaped schema
  with `_add_overlay_fields` applied and assert the SDL contains the `riskFlag`
  field of type `JSON` — guards against the un-annotated-resolver bug.
- **End-to-end field read:** execute `{ <obj>(id:"X"){ riskFlag } }` against a built
  schema with a fake `connect`/store, assert the overlay value comes back.

## Scope / non-goals

In scope: declared overlay read-back fields (JSON), wired into the per-domain
schema, with `flag_customer_high_risk` declaring `riskFlag`. Out of scope (later
slices): real Effect connectors (Delta/SAP); ontology-defined Action Types
(north-star B); typed (non-JSON) overlay field types; approve/reject/revert via
GraphQL mutations; exposing the audit log via GraphQL.

## File / change map

- `src/back/objects/actions/action_type.py` — add `overlay_fields: list[str] = []`.
- `src/back/objects/actions/types/flag_customer_high_risk.py` — set `overlay_fields = ["riskFlag"]`.
- `src/back/objects/actions/registry.py` — add `overlay_fields_by_type()`.
- `src/back/core/graphql/ResolverFactory.py` — annotate `make_overlay_field_resolver` (`-> Optional[JSON]`, error isolation).
- `src/back/core/graphql/GraphQLSchemaBuilder.py` — `_add_overlay_fields(...)`; thread `overlay_connect` through `build_for_domain` → `_build`; call before `_apply_strawberry_types`.
- `src/back/fastapi/graphql_routes.py` — pass `overlay_connect=connect` alongside the existing factories.
- `tests/units/actions/` + `tests/units/...graphql...` — the tests above.
