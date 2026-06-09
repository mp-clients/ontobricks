# Kinetic approve / reject mutations — Implementation Plan (Slice 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Expose `approveAction` / `rejectAction` GraphQL mutations over the existing `ActionService.approve`/`reject`, with per-ActionType segregation-of-duties (4-eyes) on approve. Closes the kinetic loop in-browser (propose → other user approves → `riskFlag` reflects it).

**Architecture:** `ActionType.requires_separate_approver` (default `False`) declares 4-eyes; `ActionService.approve` enforces it (proposer ≠ approver) using `action_log.actor`; two new annotated, `ActionError`-catching resolvers add `approveAction`/`rejectAction` to the `Mutation` type. Authz (approver role) deferred to a later slice.

**Tech stack:** Python 3.12, strawberry, pytest. Base `feat/kinetic-approve-reject` off `mp/master`. Spec: `docs/superpowers/specs/2026-06-08-kinetic-approve-reject-design.md`. Tests use `tests/units/actions/fakes.py` (`FakeConn`/`FakeCursor`) and build schemas **through strawberry**.

---

### Task 1: SoD flag + `AuditLog.get` returns the proposer

**Files:** modify `action_type.py`, `types/flag_customer_high_risk.py`, `audit.py`; test `tests/units/actions/test_sod_decl.py`

- [ ] **Step 1: failing test**
```python
# tests/units/actions/test_sod_decl.py
from back.objects.actions.action_type import ActionType
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk
from back.objects.actions.audit import AuditLog
from tests.units.actions.fakes import FakeCursor

def test_default_no_sod():
    assert ActionType.requires_separate_approver is False

def test_flag_requires_separate_approver():
    assert FlagCustomerHighRisk().requires_separate_approver is True

def test_auditlog_get_returns_actor():
    cur = FakeCursor(rows=[("flag_customer_high_risk","Customers","Customer","C1",
                            {"severity":"high"},"PROPOSED","alice@x")])
    rec = AuditLog().get(cur, __import__("uuid").uuid4())
    assert rec["actor"] == "alice@x"
    assert "actor" in cur.executed[0].lower()  # SELECT now includes actor
```

- [ ] **Step 2: run → FAIL** — `uv run pytest tests/units/actions/test_sod_decl.py -v`

- [ ] **Step 3: implement**
In `action_type.py`, after `overlay_fields: List[str] = []`:
```python
    # When True, approve() requires a different user than the proposer (4-eyes).
    requires_separate_approver: bool = False
```
In `flag_customer_high_risk.py` `FlagCustomerHighRisk` body (next to `overlay_fields`):
```python
    requires_separate_approver = True
```
In `audit.py` `AuditLog.get`, add `actor` to the SELECT and the returned dict:
```python
        cur.execute(
            "SELECT action_type, domain, object_type, object_id, params, status, actor "
            "FROM action_log WHERE action_id=%s", (str(action_id),))
        row = cur.fetchone()
        if not row:
            return None
        return {"action_type": row[0], "domain": row[1], "object_type": row[2],
                "object_id": row[3], "params": row[4], "status": row[5], "actor": row[6]}
```

- [ ] **Step 4: run → PASS** (3 passed) + `uv run pytest tests/units/actions/ -q` (no regression — `get` now returns an extra key; existing approve/reject tests using `_row` 6-tuples will need a 7th element — if any fail, that's Task 2's `_row` helper; check and note).

> NOTE: `tests/units/actions/test_service.py` `_row(status)` returns a 6-tuple. Adding `actor` to `get`'s SELECT means `FakeCursor` rows need a 7th element. Update `_row` in Task 2 (where the SoD tests live). If the regression run here fails ONLY on `test_service.py` row-arity, proceed — Task 2 fixes it. If it fails elsewhere, stop and report.

- [ ] **Step 5: commit**
```bash
git add src/back/objects/actions/action_type.py src/back/objects/actions/types/flag_customer_high_risk.py src/back/objects/actions/audit.py tests/units/actions/test_sod_decl.py
git commit -m "feat(actions): requires_separate_approver flag + AuditLog.get returns proposer"
```

---

### Task 2: `ActionService.approve` SoD enforcement + `reject(reason)`

**Files:** modify `service.py`; modify `tests/units/actions/test_service.py` (update `_row` arity + add SoD/reject tests)

- [ ] **Step 1: failing test** — append to `test_service.py` and update the `_row` helper to a 7-tuple (add the proposer email):
```python
# update existing helper:
def _row(status, actor="proposer@x"):
    return ("approval_flag","customers","Customer","C1",{"severity":"high"},status,actor)

def test_sod_blocks_self_approval():
    # _ApprovalFlag must declare requires_separate_approver for this test;
    # set it on the class used by _svc (see Step 3 note).
    conn = FakeConn(rows=[_row("PROPOSED", actor="alice@x")])
    with pytest.raises(ActionError):
        _svc(conn).approve(uuid.uuid4(), "alice@x", _ctx())  # same person → blocked

def test_sod_allows_different_approver():
    conn = FakeConn(rows=[_row("PROPOSED", actor="alice@x")])
    res = _svc(conn).approve(uuid.uuid4(), "bob@x", _ctx())  # different person → ok
    assert res.status == "APPLIED"

def test_reject_records_reason():
    conn = FakeConn(rows=[_row("PROPOSED")])
    res = _svc(conn).reject(uuid.uuid4(), "bob@x", reason="false positive")
    assert res.status == "REJECTED"
    flat = " ".join(str(p) for p in conn.cursor_obj.params)
    assert "false positive" in flat
```
In `test_service.py`, make `_ApprovalFlag` declare SoD so the block applies:
```python
class _ApprovalFlag(_AutoFlag):
    id = "approval_flag"; approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    requires_separate_approver = True
```

- [ ] **Step 2: run → FAIL** — `uv run pytest tests/units/actions/test_service.py -v` (SoD tests fail; reject(reason=) is a TypeError)

- [ ] **Step 3: implement** in `service.py`.
`approve` — add the SoD check after the `PROPOSED` guard (before/right after resolving `atype`):
```python
                    atype = self._registry.get(rec["action_type"])
                    if getattr(atype, "requires_separate_approver", False) \
                            and approver == rec.get("actor"):
                        raise ActionError(
                            "4-eyes: the proposer cannot approve their own action")
                    params = atype.params_model(**rec["params"])
                    self._audit.mark(cur, action_id, "APPROVED", approved_by=approver)
                    self._apply(cur, atype, action_id, rec["object_id"], params, ctx)
```
`reject` — add `reason` param and record it:
```python
    def reject(self, action_id: uuid.UUID, approver: str, reason: str = "") -> ActionResult:
        """Reject a PROPOSED action without applying any overlay edits."""
        with self._connect() as conn, conn.transaction():
            with conn.cursor() as cur:
                rec = self._audit.get(cur, action_id)
                if rec is None or rec["status"] != "PROPOSED":
                    raise ActionError(
                        f"cannot reject action in status "
                        f"{rec['status'] if rec else 'unknown'}")
                self._audit.mark(cur, action_id, "REJECTED", approved_by=approver,
                                 after={"rejected_reason": reason} if reason else None)
        return ActionResult(action_id, "REJECTED")
```

- [ ] **Step 4: run → PASS** — `uv run pytest tests/units/actions/test_service.py -v` (all incl. new), then `uv run pytest tests/units/actions/ -q`.

- [ ] **Step 5: commit**
```bash
git add src/back/objects/actions/service.py tests/units/actions/test_service.py
git commit -m "feat(actions): 4-eyes SoD in approve + reject reason"
```

---

### Task 3: `approveAction` / `rejectAction` GraphQL mutations

**Files:** modify `ResolverFactory.py`, `GraphQLSchemaBuilder.py`; test `tests/units/actions/test_approve_reject_mutation.py`

- [ ] **Step 1: failing test** (build THROUGH strawberry + resolver error-catch):
```python
# tests/units/actions/test_approve_reject_mutation.py
import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
from back.core.graphql.ResolverFactory import ResolverFactory
from back.objects.actions.service import ActionError

def test_mutation_sdl_has_approve_and_reject():
    mut = GraphQLSchemaBuilder._build_mutation(
        service_factory=lambda info: None, ctx_factory=lambda info, oid: None)
    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str: return "ok"
    sdl = strawberry.Schema(query=Query, mutation=mut).as_str()
    assert "approveAction" in sdl and "rejectAction" in sdl

def test_approve_resolver_calls_service():
    seen = {}
    class _Svc:
        def approve(self, aid, approver, ctx):
            seen.update(aid=aid, approver=approver)
            class R: action_id=aid; status="APPLIED"; errors=[]
            return R()
    class _Ctx: actor = "bob@x"
    r = ResolverFactory.make_approve_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1")
    assert out.status == "APPLIED" and seen["approver"] == "bob@x"

def test_approve_resolver_catches_actionerror():
    class _Svc:
        def approve(self, *a, **k): raise ActionError("4-eyes: ...")
    class _Ctx: actor = "alice@x"
    r = ResolverFactory.make_approve_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1")
    assert out.status == "ERROR" and out.errors and "4-eyes" in out.errors[0]
```

- [ ] **Step 2: run → FAIL** — `uv run pytest tests/units/actions/test_approve_reject_mutation.py -v`

- [ ] **Step 3: implement** in `ResolverFactory.py` (add after `make_action_mutation_resolver`; import `ActionError` locally to avoid a circular import at module load):
```python
    @staticmethod
    def make_approve_resolver(service_factory, ctx_factory):
        """Mutation resolver: approve a PROPOSED action (approver = current user)."""
        from back.objects.actions.service import ActionError

        def resolver(info: Info, action_id: strawberry.ID) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.approve(str(action_id), ctx.actor, ctx)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return resolver

    @staticmethod
    def make_reject_resolver(service_factory, ctx_factory):
        """Mutation resolver: reject a PROPOSED action with an optional reason."""
        from back.objects.actions.service import ActionError

        def resolver(info: Info, action_id: strawberry.ID, reason: str = "") -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.reject(str(action_id), ctx.actor, reason)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return resolver
```
In `GraphQLSchemaBuilder._build_mutation`, append two fields to `mutation_fields`:
```python
            strawberry.field(
                name="approveAction",
                resolver=ResolverFactory.make_approve_resolver(
                    service_factory=service_factory, ctx_factory=ctx_factory),
                description="Approve a PROPOSED action (4-eyes enforced per action type).",
            ),
            strawberry.field(
                name="rejectAction",
                resolver=ResolverFactory.make_reject_resolver(
                    service_factory=service_factory, ctx_factory=ctx_factory),
                description="Reject a PROPOSED action with an optional reason.",
            ),
```

- [ ] **Step 4: run → PASS** (3 passed). Regression: `uv run pytest tests/units -k "graphql or actions" -q`. Headless sanity:
```bash
uv run python -c "
import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
m=GraphQLSchemaBuilder._build_mutation(lambda i:None, lambda i,o:None)
@strawberry.type
class Q:
    @strawberry.field
    def ping(self)->str: return 'ok'
sdl=strawberry.Schema(query=Q,mutation=m).as_str()
print('approveAction' in sdl, 'rejectAction' in sdl, 'flagCustomerHighRisk' in sdl)
"
```
Expected: `True True True`.

- [ ] **Step 5: commit**
```bash
git add src/back/core/graphql/ResolverFactory.py src/back/core/graphql/GraphQLSchemaBuilder.py tests/units/actions/test_approve_reject_mutation.py
git commit -m "feat(actions): approveAction / rejectAction GraphQL mutations (annotated, ActionError-safe)"
```

---

### Task 4: docs + changelog + full suite

**Files:** `docs/architecture.md`, `README.md` (if it lists the kinetic entry points), `changelogs/v0.4.0/2026-06-08.log`

- [ ] **Step 1: docs** — in the Kinetic Actions "Entry points", add `approveAction(actionId)` / `rejectAction(actionId, reason)` to the GraphQL mutations (alongside `flagCustomerHighRisk`); note **4-eyes is enforced per ActionType** (`requires_separate_approver`), and that **approver authz is a deferred follow-up**. **Read the actual code before writing — do NOT describe fields/types that don't exist** (e.g. no `OverlayFieldSpec`, no `actionLog` resolver). Keep it accurate and tight.

- [ ] **Step 2: full suite** — `uv run pytest -q`. Expected: green except the 2 pre-existing unrelated `tests/units/api/test_external_api.py::TestDomainVersions` failures (and no-browser e2e errors). Confirm NO new failures.

- [ ] **Step 3: changelog** — append a "Kinetic approve/reject mutations (slice 3)" section to `changelogs/v0.4.0/2026-06-08.log` (gitignored — local record). Title, context, numbered changes with file paths, modified-files list, test result (noting the 2 pre-existing failures). Describe ONLY what was actually built.

- [ ] **Step 4: commit**
```bash
git add docs/ README.md 2>/dev/null; git commit -m "docs(actions): document approve/reject mutations + 4-eyes (slice 3)" || echo "(no doc change)"
```

---

## Self-review notes (resolved)
- **Spec coverage:** SoD flag (T1), `get` returns proposer (T1), approve SoD enforcement + reject reason (T2), both mutations annotated + ActionError-caught + build-through-strawberry (T3), docs/changelog (T4). Authz explicitly deferred (noted in T4 docs).
- **Annotation-bug guard:** T3 builds the schema through strawberry and asserts the SDL — the slice-1/2 lesson.
- **Cross-task arity gotcha (flagged, not a placeholder):** adding `actor` to `AuditLog.get` makes its row a 7-tuple; T1 Step 4 + T2 Step 1 explicitly update `test_service.py`'s `_row` helper to match. Reviewer/implementer must apply T2's `_row` change or the T1 regression run will show `test_service.py` row-arity failures.
- **Approver source:** `ctx.actor` (current user via the route's existing email extraction); `ctx_factory` ignores its `object_id` arg, so `ctx_factory(info, None)` is safe.
