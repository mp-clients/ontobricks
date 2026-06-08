# Kinetic Overlay Read-Back Implementation Plan (Slice 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Expose general, ActionType-declared overlay read-back fields on per-domain GraphQL object types, so `query { customer(id:"C1"){ riskFlag } }` returns the applied overlay value. Closes the slice-1 read-back gap.

**Architecture:** Each `ActionType` declares `overlay_fields` (props it writes on its `object_type`). `ActionRegistry` aggregates them. `GraphQLSchemaBuilder` attaches a `JSON` resolver field per `(object_type, prop)` — using the now-annotated `make_overlay_field_resolver` — *before* freezing each strawberry type, wired via a new `overlay_connect` on the mutation-capable schema (so it rides the existing `-m` cache key). `flag_customer_high_risk` declares `riskFlag`.

**Tech Stack:** Python 3.12, strawberry-graphql (`strawberry.scalars.JSON`), pytest, Lakebase (psycopg3). Base branch `feat/kinetic-slice-2` off `mp/master`. Spec: `docs/superpowers/specs/2026-06-08-kinetic-overlay-readback-design.md`.

**Test seam:** unit tests use the existing `tests/units/actions/fakes.py` (`FakeConn`/`FakeCursor`) and build schemas *through strawberry* (a direct resolver call does NOT catch annotation bugs — that was the slice-1 mutation bug).

---

### Task 1: `ActionType.overlay_fields` + declare on the action

**Files:**
- Modify: `src/back/objects/actions/action_type.py`
- Modify: `src/back/objects/actions/types/flag_customer_high_risk.py`
- Test: `tests/units/actions/test_overlay_fields_decl.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/units/actions/test_overlay_fields_decl.py
from back.objects.actions.action_type import ActionType
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk

def test_actiontype_default_overlay_fields_empty():
    # base default must be empty so existing action types are unaffected
    assert ActionType.overlay_fields == []

def test_flag_declares_riskflag():
    a = FlagCustomerHighRisk()
    assert a.object_type == "Customer"
    assert a.overlay_fields == ["riskFlag"]
```

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... 'overlay_fields'`)
Run: `uv run pytest tests/units/actions/test_overlay_fields_decl.py -v`

- [ ] **Step 3: Implement**
In `action_type.py`, add the class attribute alongside the other declared attrs (after `params_model: Type[BaseModel]`):
```python
    # Property names this Action writes on `object_type`, exposed as
    # overlay-backed read-back fields on the GraphQL type. Default empty.
    overlay_fields: List[str] = []
```
In `flag_customer_high_risk.py`, add to the `FlagCustomerHighRisk` class body (next to `object_type = "Customer"`):
```python
    overlay_fields = ["riskFlag"]
```

- [ ] **Step 4: Run → PASS** (2 passed)
Run: `uv run pytest tests/units/actions/test_overlay_fields_decl.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/back/objects/actions/action_type.py src/back/objects/actions/types/flag_customer_high_risk.py tests/units/actions/test_overlay_fields_decl.py
git commit -m "feat(actions): ActionType.overlay_fields; flag declares riskFlag"
```

---

### Task 2: `ActionRegistry.overlay_fields_by_type()`

**Files:**
- Modify: `src/back/objects/actions/registry.py`
- Test: `tests/units/actions/test_registry_overlay.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/units/actions/test_registry_overlay.py
from pydantic import BaseModel
from back.objects.actions.base import ApprovalPolicy, OverlayEdit
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry

class _P(BaseModel):
    pass

def _mk(_id, otype, fields):
    class T(ActionType):
        id = _id; object_type = otype; approval_policy = ApprovalPolicy.AUTO
        params_model = _P; overlay_fields = fields
        def validate(self, ctx, p): return []
        def apply(self, ctx, p): return []
        def effects(self, p): return []
    return T()

def test_empty_registry_returns_empty():
    assert ActionRegistry().overlay_fields_by_type() == {}

def test_aggregates_by_object_type():
    reg = ActionRegistry()
    reg.register(_mk("a", "Customer", ["riskFlag"]))
    reg.register(_mk("b", "Customer", ["watchlist"]))
    reg.register(_mk("c", "Account", ["frozen"]))
    reg.register(_mk("d", "Order", []))  # no fields → no entry
    out = reg.overlay_fields_by_type()
    assert out["Customer"] == {"riskFlag", "watchlist"}
    assert out["Account"] == {"frozen"}
    assert "Order" not in out
```

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... 'overlay_fields_by_type'`)
Run: `uv run pytest tests/units/actions/test_registry_overlay.py -v`

- [ ] **Step 3: Implement** — add to `ActionRegistry` (and update imports: `from typing import Dict, Set`):
```python
    def overlay_fields_by_type(self) -> Dict[str, Set[str]]:
        """Map object_type → set of overlay property names declared across all
        registered action types (object types with no declared fields are omitted)."""
        result: Dict[str, Set[str]] = {}
        for t in self._types.values():
            for prop in getattr(t, "overlay_fields", []) or []:
                result.setdefault(t.object_type, set()).add(prop)
        return result
```

- [ ] **Step 4: Run → PASS** (2 passed)
Run: `uv run pytest tests/units/actions/test_registry_overlay.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/back/objects/actions/registry.py tests/units/actions/test_registry_overlay.py
git commit -m "feat(actions): ActionRegistry.overlay_fields_by_type() aggregation"
```

---

### Task 3: Annotate `make_overlay_field_resolver` (+ error isolation)

**Files:**
- Modify: `src/back/core/graphql/ResolverFactory.py`
- Test: `tests/units/actions/test_overlay_resolver.py`

The current resolver `def resolver(root):` has NO return annotation, so it cannot be used in a real strawberry field. Annotate it `-> Optional[JSON]` and isolate read errors.

- [ ] **Step 1: Write the failing test**
```python
# tests/units/actions/test_overlay_resolver.py
import typing
from back.core.graphql.ResolverFactory import ResolverFactory

class _Cur:
    def __enter__(self): return self
    def __exit__(self, *a): return False
class _Conn:
    def cursor(self): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _Store:
    def __init__(self, val): self._val = val
    def current_value(self, cur, ot, oid, prop): return self._val

class _Obj:
    id = "C1"

def test_resolver_has_return_annotation():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"severity": "high"}), lambda: _Conn(), "Customer", "riskFlag")
    assert "return" in typing.get_type_hints(r)  # annotated → strawberry can build it

def test_resolver_returns_value():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"severity": "high"}), lambda: _Conn(), "Customer", "riskFlag")
    assert r(_Obj())["severity"] == "high"

def test_resolver_none_when_no_id():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"x": 1}), lambda: _Conn(), "Customer", "riskFlag")
    class NoId: pass
    assert r(NoId()) is None

def test_resolver_isolates_errors():
    def boom(): raise RuntimeError("db down")
    r = ResolverFactory.make_overlay_field_resolver(_Store({"x": 1}), boom, "Customer", "riskFlag")
    assert r(_Obj()) is None  # error swallowed → None, not raised
```

- [ ] **Step 2: Run → FAIL** (`test_resolver_has_return_annotation` fails: no `return` hint; `test_resolver_isolates_errors` raises)
Run: `uv run pytest tests/units/actions/test_overlay_resolver.py -v`

- [ ] **Step 3: Implement** — at top of `ResolverFactory.py` add the import (near the other strawberry imports):
```python
from strawberry.scalars import JSON
```
Replace the `make_overlay_field_resolver` body with:
```python
    @staticmethod
    def make_overlay_field_resolver(store, connect, object_type, prop):
        """Resolver for an overlay-backed scalar field on an object type.

        Returns the current overlay value (arbitrary JSON) for the object's id,
        or None. Read failures are isolated to this field (logged, return None)
        so one field never breaks the whole query."""

        def resolver(root) -> typing.Optional[JSON]:
            object_id = getattr(root, "id", None)
            if object_id is None:
                return None
            try:
                with connect() as conn, conn.cursor() as cur:
                    return store.current_value(cur, object_type, str(object_id), prop)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "overlay field %s.%s read failed: %s", object_type, prop, exc
                )
                return None

        return resolver
```
Add `import typing` at the top if not present (the module already imports `from typing import ... Optional`; you may use `Optional[JSON]` directly instead of `typing.Optional[JSON]` — match the module's existing style, just ensure the annotation is present).

- [ ] **Step 4: Run → PASS** (4 passed)
Run: `uv run pytest tests/units/actions/test_overlay_resolver.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/back/core/graphql/ResolverFactory.py tests/units/actions/test_overlay_resolver.py
git commit -m "fix(actions): annotate make_overlay_field_resolver (-> Optional[JSON]) + isolate read errors"
```

---

### Task 4: `_add_overlay_fields` in the schema builder + build through strawberry

**Files:**
- Modify: `src/back/core/graphql/GraphQLSchemaBuilder.py`
- Test: `tests/units/actions/test_overlay_schema_build.py`

First READ `GraphQLSchemaBuilder.py` `_create_python_classes`, `_add_relationship_annotations`, `_apply_strawberry_types`, `_build`, and `build_for_domain` to match the existing threading of `service_factory`/`ctx_factory`.

- [ ] **Step 1: Write the failing test** (builds a schema THROUGH strawberry)
```python
# tests/units/actions/test_overlay_schema_build.py
import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder

class _Cur:
    def __enter__(self): return self
    def __exit__(self, *a): return False
class _Conn:
    def cursor(self): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_add_overlay_fields_attaches_buildable_json_field():
    # a plain Python class like _create_python_classes produces
    Customer = type("Customer", (), {"__annotations__": {"id": strawberry.ID}, "id": ""})
    py_classes = {"Customer": Customer}
    GraphQLSchemaBuilder._add_overlay_fields(
        py_classes, {"Customer": {"riskFlag"}}, "customers", lambda: _Conn())
    # now freeze + build a schema through strawberry (catches annotation bugs)
    gql = strawberry.type(Customer)
    @strawberry.type
    class Query:
        @strawberry.field
        def customer(self) -> gql:  # type: ignore
            return gql(id="C1")
    sdl = strawberry.Schema(query=Query).as_str()
    assert "riskFlag" in sdl

def test_add_overlay_fields_skips_unknown_type():
    py_classes = {"Customer": type("Customer", (), {"__annotations__": {"id": strawberry.ID}, "id": ""})}
    # 'Account' not in py_classes → no error, no-op
    GraphQLSchemaBuilder._add_overlay_fields(py_classes, {"Account": {"frozen"}}, "customers", lambda: _Conn())
    assert not hasattr(py_classes["Customer"], "frozen")
```

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... '_add_overlay_fields'`)
Run: `uv run pytest tests/units/actions/test_overlay_schema_build.py -v`

- [ ] **Step 3: Implement**
Add the static method to `GraphQLSchemaBuilder` (place near `_add_relationship_annotations`):
```python
    @staticmethod
    def _add_overlay_fields(py_classes, overlay_map, domain, connect):
        """Attach overlay-backed JSON read-back fields to the plain Python
        classes BEFORE they are frozen by _apply_strawberry_types. For each
        object_type present in py_classes, add one strawberry.field per declared
        overlay property, resolved from the Lakebase overlay store."""
        import strawberry
        from strawberry.scalars import JSON
        from typing import Optional
        from back.core.graphql.ResolverFactory import ResolverFactory
        from back.objects.actions.overlay_store import OverlayStore

        store = OverlayStore(domain)
        for object_type, props in (overlay_map or {}).items():
            cls = py_classes.get(object_type)
            if cls is None:
                continue
            for prop in props:
                if prop in cls.__annotations__:
                    continue  # don't clobber an ontology-declared field
                cls.__annotations__[prop] = Optional[JSON]
                setattr(
                    cls,
                    prop,
                    strawberry.field(
                        resolver=ResolverFactory.make_overlay_field_resolver(
                            store, connect, object_type, prop
                        ),
                        description=f"Overlay-backed kinetic field '{prop}' (current applied value, or null).",
                    ),
                )
```
Then thread `overlay_connect` through, mirroring how `service_factory`/`ctx_factory` are already threaded:
- Add `overlay_connect=None` to `build_for_domain(...)` and to `_build(...)`.
- In `_build`, AFTER `self._add_relationship_annotations(py_classes, rel_by_domain)` and BEFORE `gql_types = self._apply_strawberry_types(...)`, insert:
```python
        if overlay_connect is not None:
            from back.objects.actions.registry import default_registry
            import back.objects.actions.types  # noqa: F401  (ensure types register)
            overlay_map = default_registry.overlay_fields_by_type()
            if overlay_map:
                self._add_overlay_fields(py_classes, overlay_map, base_uri_domain, overlay_connect)
```
NOTE on the domain argument: `_add_overlay_fields` needs the **domain** used by `OverlayStore` (the registry domain, same value the route's `ctx_factory` passes as `ActionContext.domain`). `_build` has `base_uri`, not the domain name — thread the domain name from `build_for_domain` into `_build` (add a `domain` param if not already present; `build_for_domain` receives the domain — pass it down). Use that domain, NOT `base_uri`. (Replace `base_uri_domain` above with that threaded `domain`.)

- [ ] **Step 4: Run → PASS** (2 passed). Also regression-check existing graphql: `uv run pytest tests/units -k graphql -q`
Run: `uv run pytest tests/units/actions/test_overlay_schema_build.py -v`

- [ ] **Step 5: Commit**
```bash
git add src/back/core/graphql/GraphQLSchemaBuilder.py tests/units/actions/test_overlay_schema_build.py
git commit -m "feat(actions): _add_overlay_fields attaches overlay JSON fields before freeze"
```

---

### Task 5: Wire `overlay_connect` in the GraphQL route

**Files:**
- Modify: `src/back/fastapi/graphql_routes.py`
- Test: covered by Task 4 regression + the full suite (no new unit; this is wiring an existing `connect` into an existing call)

First READ `_get_schema_and_context` in `graphql_routes.py` — it already builds `connect` and passes `service_factory`/`ctx_factory` to `build_for_domain` when Lakebase is reachable.

- [ ] **Step 1: Implement** — in `_get_schema_and_context`, where `build_for_domain(...)` is called with `service_factory=...`/`ctx_factory=...`, also pass:
```python
            overlay_connect=connect,   # same pooled connection used for the mutation factories
```
(Only in the branch where `request is not None` and `connect`/factories are built — i.e. the Lakebase-reachable, mutation-capable path. The query-only/`request=None` paths pass nothing, unchanged.)

- [ ] **Step 2: Verify no regression**
Run: `uv run pytest tests/units -k "graphql or fastapi or actions" -q`
Expected: green (no new failures vs the known pre-existing 2 in `test_external_api.py::TestDomainVersions`).

- [ ] **Step 3: Headless build-through-strawberry sanity** (mirrors the slice-1 verification that caught the mutation bug)
Run:
```bash
uv run python -c "
import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
Customer = type('Customer', (), {'__annotations__': {'id': strawberry.ID}, 'id': ''})
GraphQLSchemaBuilder._add_overlay_fields({'Customer': Customer}, {'Customer': {'riskFlag'}}, 'customers', lambda: None)
gql = strawberry.type(Customer)
@strawberry.type
class Q:
    @strawberry.field
    def customer(self) -> gql: return gql(id='C1')
print('riskFlag' in strawberry.Schema(query=Q).as_str())
"
```
Expected: `True`.

- [ ] **Step 4: Commit**
```bash
git add src/back/fastapi/graphql_routes.py
git commit -m "feat(actions): pass overlay_connect into build_for_domain (read-back fields live)"
```

---

### Task 6: Docs + changelog + full suite

**Files:**
- Modify: `docs/architecture.md` (the "Kinetic Actions" section) + `README.md` if it mentions kinetic read-back
- Create: `changelogs/v0.4.0/2026-06-08.log` (append if it exists)

- [ ] **Step 1: Docs** — in the "Kinetic Actions" section, update the read-back line: overlay-backed fields are now live (e.g. `Customer.riskFlag`), declared via `ActionType.overlay_fields`, returned as `JSON`. Remove "riskFlag not yet wired" from the follow-ups list; leave the remaining follow-ups (real Effect connectors, ontology-defined Action Types).

- [ ] **Step 2: Full suite**
Run: `uv run pytest -q`
Expected: green except the 2 pre-existing unrelated `TestDomainVersions` failures (record this in the changelog).

- [ ] **Step 3: Changelog** — invoke the `changelog` skill: write `changelogs/v0.4.0/2026-06-08.log` with title, context, numbered changes (file paths), modified-files list, and the test result (note the 2 pre-existing failures). (Note: `changelogs/` is gitignored in this repo — the file is the local record, not committed.)

- [ ] **Step 4: Commit**
```bash
git add docs/ README.md 2>/dev/null; git commit -m "docs(actions): overlay read-back fields are live (slice 2)"
```

---

## Self-review notes (resolved)

- **Spec coverage:** `overlay_fields` decl (T1), registry aggregation (T2), annotated resolver + error isolation (T3), `_add_overlay_fields` + threading + build-through-strawberry test (T4), route wiring on the mutation-capable/cached path (T5), docs+changelog (T6). Non-goals (real connectors, ontology-defined types, typed fields, approve/revert mutations) excluded.
- **Annotation-bug guard:** T3 asserts the resolver is annotated and T4/T5 build the schema *through strawberry* — directly guarding the slice-1 failure class.
- **Cache safety:** `overlay_connect` is only passed on the `request`-present path (which already carries the `-m` cache key); query-only callers unchanged. `connect` is the stable pooled connection → cache-safe.
- **Known adaptation point (flagged, not a placeholder):** the exact `domain` value threaded into `_build`/`_add_overlay_fields` must equal the `OverlayStore` domain the route uses in `ctx_factory` — T4 Step 3 calls this out explicitly; confirm against `build_for_domain`'s signature during implementation.
