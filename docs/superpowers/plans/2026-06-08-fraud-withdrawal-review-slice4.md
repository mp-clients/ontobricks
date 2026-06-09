# Fraud Withdrawal Review — Slice 4 (the decision loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-proposes / human-accepts-or-overrides decision loop on a new `Withdrawal` object, on top of the kinetic Action layer.

**Architecture:** A new `review_withdrawal` ActionType (`object_type="Withdrawal"`, `overlay_fields=["decision"]`, `REQUIRES_APPROVAL`, 4-eyes). Accept reuses slice-3 `approveAction` unchanged. Override is one new `ActionService.override()` + `overrideAction` GraphQL mutation that marks the agent's proposal `OVERRIDDEN` and writes the human's decision overlay in the same transaction. The applied `decision` overlay value carries both the agent recommendation and the human decision plus an `agreed` flag. The customer POC (`flag_customer_high_risk`) is retired in the last code task so earlier tasks keep their suites green.

**Tech Stack:** Python 3.12, pydantic v2, strawberry-graphql, psycopg (Lakebase/Postgres), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-08-fraud-withdrawal-review-design.md`

**Conventions for every task:** run tests with `uv run pytest <path> -v`; commit with a `feat(actions):` / `test:` / `docs:` prefix and the trailing `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` line. Work on a branch `feat/fraud-withdrawal-review` off `master`.

---

## File Structure

- `src/back/objects/actions/types/review_withdrawal.py` (new) — the `ReviewWithdrawal` ActionType + its params model + a `_utcnow_iso()` helper. Single responsibility: define the withdrawal-review action and compose its `decision` overlay value.
- `src/back/objects/actions/types/__init__.py` (modify) — register `ReviewWithdrawal`; (Task 7) unregister `FlagCustomerHighRisk`.
- `src/back/objects/actions/base.py` (modify) — add `OVERRIDDEN` to `ActionStatus`.
- `src/back/objects/actions/service.py` (modify) — generalize `_apply(... , *, status, approved_by, extra_after)`; add `override()`.
- `src/back/core/graphql/ResolverFactory.py` (modify) — add `make_review_withdrawal_resolver` + `make_override_resolver`.
- `src/back/core/graphql/GraphQLSchemaBuilder.py` (modify) — wire `reviewWithdrawal` + `overrideAction` into `_build_mutation`; (Task 7) drop the `flagCustomerHighRisk` field.
- `src/back/objects/actions/types/flag_customer_high_risk.py` (delete in Task 7).
- `tests/units/actions/test_review_withdrawal.py` (new) — ActionType apply/validate tests.
- `tests/units/actions/test_override.py` (new) — service-level override tests.
- `tests/units/actions/test_review_withdrawal_mutation.py` (new) — build-through-strawberry + resolver tests.
- `tests/units/graphql/` overlay read-back test for `Withdrawal.decision` (new test in the existing overlay test module, or a new file).
- `scripts/seed_fraud_withdrawals.sql` (new, Task 6) — sample withdrawals for the POC domain.
- `docs/architecture.md`, `README.md` (modify, Task 8).

---

## Task 1: `ReviewWithdrawal` ActionType (registered alongside the customer type)

**Files:**
- Create: `src/back/objects/actions/types/review_withdrawal.py`
- Modify: `src/back/objects/actions/types/__init__.py`
- Test: `tests/units/actions/test_review_withdrawal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_review_withdrawal.py
from back.objects.actions.base import ActionContext, ApprovalPolicy
from back.objects.actions.types.review_withdrawal import (
    ReviewWithdrawal, ReviewWithdrawalParams,
)


def _ctx(actor="reviewer@x", metadata=None):
    return ActionContext(domain="fraud", actor=actor, actor_kind="user",
                         connect=lambda: None, metadata=metadata or {})


def test_type_declares_withdrawal_overlay_and_4eyes():
    t = ReviewWithdrawal()
    assert t.id == "review_withdrawal"
    assert t.object_type == "Withdrawal"
    assert t.overlay_fields == ["decision"]
    assert t.requires_separate_approver is True
    assert t.approval_policy == ApprovalPolicy.REQUIRES_APPROVAL


def test_apply_accept_composes_agreed_decision():
    # No override in metadata => accept: human_decision == agent_recommendation.
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="reject",
                               rationale="velocity spike")
    edits = t.apply(_ctx(actor="boss@x"), p)
    assert len(edits) == 1
    e = edits[0]
    assert e.object_type == "Withdrawal" and e.object_id == "W1" and e.property == "decision"
    assert e.value["agent_recommendation"] == "reject"
    assert e.value["human_decision"] == "reject"
    assert e.value["agreed"] is True
    assert e.value["decided_by"] == "boss@x"
    assert "decided_at" in e.value


def test_apply_override_flips_decision_and_marks_disagreement():
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="reject",
                               rationale="velocity spike")
    ctx = _ctx(actor="boss@x",
               metadata={"decision_override": "approve", "override_reason": "known customer"})
    e = t.apply(ctx, p)[0]
    assert e.value["agent_recommendation"] == "reject"
    assert e.value["human_decision"] == "approve"
    assert e.value["agreed"] is False
    assert e.value["reason"] == "known customer"


def test_params_reject_bad_recommendation():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReviewWithdrawalParams(withdrawal_id="W1", recommendation="maybe")


def test_effects_enqueue_noop_for_now():
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="approve")
    effects = t.effects(p)
    assert effects and effects[0][0] == "noop_log"
    assert effects[0][1]["withdrawal_id"] == "W1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_review_withdrawal.py -v`
Expected: FAIL — `ModuleNotFoundError: ... review_withdrawal`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/types/review_withdrawal.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field
from back.objects.actions.action_type import ActionType
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewWithdrawalParams(BaseModel):
    withdrawal_id: str
    recommendation: str = Field(pattern="^(approve|reject)$")
    rationale: str = ""
    risk_assessment: Optional[dict] = None


class ReviewWithdrawal(ActionType):
    """An agent proposes a decision on a risky withdrawal; a human accepts
    (approveAction) or overrides (overrideAction). The applied overlay records
    both the agent recommendation and the human decision."""
    id = "review_withdrawal"
    object_type = "Withdrawal"
    overlay_fields = ["decision"]
    requires_separate_approver = True
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = ReviewWithdrawalParams

    def validate(self, ctx: ActionContext, params: ReviewWithdrawalParams) -> List[str]:
        return []

    def apply(self, ctx: ActionContext, params: ReviewWithdrawalParams) -> List[OverlayEdit]:
        override = (ctx.metadata or {}).get("decision_override")
        human_decision = override or params.recommendation
        reason = (ctx.metadata or {}).get("override_reason", "")
        value = {
            "agent_recommendation": params.recommendation,
            "human_decision": human_decision,
            "agreed": human_decision == params.recommendation,
            "decided_by": ctx.actor,
            "reason": reason,
            "decided_at": _utcnow_iso(),
        }
        return [OverlayEdit(object_type="Withdrawal", object_id=params.withdrawal_id,
                            property="decision", value=value)]

    def effects(self, params: ReviewWithdrawalParams) -> List[Tuple[str, dict]]:
        # Slice 6 replaces noop_log with the moneypool main-app callback.
        return [("noop_log", {"withdrawal_id": params.withdrawal_id})]
```

Then register it (keep the customer type for now — it is retired in Task 7):

```python
# src/back/objects/actions/types/__init__.py
"""Code-registered Action Types. Importing this package registers them on
``back.objects.actions.registry.default_registry``."""
from back.objects.actions.registry import default_registry
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk
from back.objects.actions.types.review_withdrawal import ReviewWithdrawal

default_registry.register(FlagCustomerHighRisk())
default_registry.register(ReviewWithdrawal())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_review_withdrawal.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/types/review_withdrawal.py \
        src/back/objects/actions/types/__init__.py \
        tests/units/actions/test_review_withdrawal.py
git commit -m "feat(actions): ReviewWithdrawal action type (agent-proposes decision overlay)"
```

---

## Task 2: `OVERRIDDEN` status + `ActionService.override()`

**Files:**
- Modify: `src/back/objects/actions/base.py:8-14` (add `OVERRIDDEN`)
- Modify: `src/back/objects/actions/service.py:135-145` (generalize `_apply`), add `override()` after `reject()` (~line 101)
- Test: `tests/units/actions/test_override.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_override.py
import uuid
import pytest
from pydantic import BaseModel, Field
from back.objects.actions.base import ApprovalPolicy, OverlayEdit, ActionContext
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry
from back.objects.actions.service import ActionService, ActionError
from tests.units.actions.fakes import FakeConn


class _P(BaseModel):
    withdrawal_id: str
    recommendation: str = Field(pattern="^(approve|reject)$")


class _Review(ActionType):
    id = "review_withdrawal"; object_type = "Withdrawal"
    overlay_fields = ["decision"]
    requires_separate_approver = True
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = _P
    def validate(self, ctx, p): return []
    def apply(self, ctx, p):
        override = (ctx.metadata or {}).get("decision_override")
        human = override or p.recommendation
        return [OverlayEdit("Withdrawal", p.withdrawal_id, "decision",
                            {"agent_recommendation": p.recommendation,
                             "human_decision": human,
                             "agreed": human == p.recommendation,
                             "decided_by": ctx.actor})]
    def effects(self, p): return [("noop_log", {"withdrawal_id": p.withdrawal_id})]


def _svc(conn):
    reg = ActionRegistry(); reg.register(_Review())
    return ActionService(registry=reg, connect=lambda: conn.ctx())


def _ctx():
    return ActionContext(domain="fraud", actor="human@x", actor_kind="user",
                         connect=lambda: None)


def _row(status, actor="agent@x"):
    return ("review_withdrawal", "fraud", "Withdrawal", "W1",
            {"withdrawal_id": "W1", "recommendation": "reject"}, status, actor)


def test_override_marks_overridden_and_writes_overlay():
    conn = FakeConn(rows=[_row("PROPOSED")])
    res = _svc(conn).override(uuid.uuid4(), "human@x", "approve", "known customer", _ctx())
    assert res.status == "OVERRIDDEN"
    sql = " ".join(conn.cursor_obj.executed).lower()
    assert "insert into ontology_overlay" in sql
    assert "insert into action_effects_outbox" in sql          # effect still fires
    flat = " ".join(str(p) for p in conn.cursor_obj.params)
    assert "OVERRIDDEN" in flat and "known customer" in flat
    assert "approve" in flat


def test_override_guards_non_proposed():
    conn = FakeConn(rows=[_row("APPLIED")])
    with pytest.raises(ActionError):
        _svc(conn).override(uuid.uuid4(), "human@x", "approve", "x", _ctx())


def test_override_rejects_bad_decision():
    conn = FakeConn(rows=[_row("PROPOSED")])
    with pytest.raises(ActionError):
        _svc(conn).override(uuid.uuid4(), "human@x", "maybe", "x", _ctx())


def test_override_requires_reason():
    conn = FakeConn(rows=[_row("PROPOSED")])
    with pytest.raises(ActionError):
        _svc(conn).override(uuid.uuid4(), "human@x", "approve", "   ", _ctx())


def test_override_unknown_action():
    conn = FakeConn(rows=[])
    with pytest.raises(ActionError):
        _svc(conn).override(uuid.uuid4(), "human@x", "approve", "x", _ctx())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_override.py -v`
Expected: FAIL — `AttributeError: 'ActionService' object has no attribute 'override'`.

- [ ] **Step 3: Write minimal implementation**

First add the status. In `src/back/objects/actions/base.py`, inside `class ActionStatus`:

```python
class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"
    OVERRIDDEN = "OVERRIDDEN"
    FAILED = "FAILED"
```

Generalize `_apply` in `service.py` (replace the existing method at lines 135-145):

```python
    def _apply(self, cur: Any, atype, action_id: uuid.UUID, object_id: str,
               params, ctx: ActionContext, *, status: str = "APPLIED",
               approved_by: Optional[str] = None,
               extra_after: Optional[dict] = None) -> None:
        overlay = OverlayStore(domain=ctx.domain)
        edits = atype.apply(ctx, params)
        before = {e.property: overlay.current_value(cur, e.object_type, e.object_id, e.property)
                  for e in edits}
        overlay.apply_edits(cur, action_id, edits)
        after = {e.property: e.value for e in edits}
        if extra_after:
            after = {**after, **extra_after}
        self._audit.mark(cur, action_id, status, before=before, after=after,
                         approved_by=approved_by)
        for name, payload in atype.effects(params):
            self._outbox.enqueue(cur, action_id, name, {**payload, "action_id": str(action_id)})
```

(The existing `approve`/`propose` calls to `self._apply(...)` keep working — the new kwargs default to the prior `APPLIED` behavior.)

Add `override()` immediately after `reject()` (after line 101):

```python
    def override(self, action_id: uuid.UUID, approver: str, decision: str,
                 reason: str, ctx: ActionContext) -> ActionResult:
        """Override a PROPOSED action's recommendation with the human's own
        decision. Marks the agent proposal OVERRIDDEN and writes the human's
        decision overlay in the same transaction (agent recommendation preserved
        in the row's params)."""
        if decision not in ("approve", "reject"):
            raise ActionError("decision must be 'approve' or 'reject'")
        if not reason or not reason.strip():
            raise ActionError("override requires a reason")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    rec = self._audit.get(cur, action_id)
                    if rec is None:
                        raise ActionError(f"unknown action: {action_id}")
                    if rec["status"] != "PROPOSED":
                        raise ActionError(
                            f"cannot override action in status {rec['status']}")
                    atype = self._registry.get(rec["action_type"])
                    params = atype.params_model(**rec["params"])
                    ctx.metadata = {**(ctx.metadata or {}),
                                    "decision_override": decision,
                                    "override_reason": reason}
                    self._apply(cur, atype, action_id, rec["object_id"], params, ctx,
                                status="OVERRIDDEN", approved_by=approver,
                                extra_after={"override_decision": decision,
                                             "override_reason": reason})
        self._drain_effects()
        return ActionResult(action_id, "OVERRIDDEN")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_override.py tests/units/actions/test_service.py -v`
Expected: PASS (override tests pass; existing service tests still pass — `_apply` defaults unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/base.py src/back/objects/actions/service.py \
        tests/units/actions/test_override.py
git commit -m "feat(actions): ActionService.override + OVERRIDDEN status (human substitutes decision)"
```

---

## Task 3: `overrideAction` + `reviewWithdrawal` GraphQL resolvers

**Files:**
- Modify: `src/back/core/graphql/ResolverFactory.py` (add two factory methods after `make_reject_resolver`, ~line 153)
- Test: `tests/units/actions/test_review_withdrawal_mutation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_review_withdrawal_mutation.py
"""Build-through-strawberry tests for reviewWithdrawal + overrideAction."""
import strawberry
from back.core.graphql.ResolverFactory import ResolverFactory
from back.objects.actions.service import ActionError


def test_review_resolver_proposes():
    seen = {}

    class _Svc:
        def propose(self, type_id, object_id, params, ctx):
            seen.update(type_id=type_id, object_id=object_id, params=params)
            class R: action_id = "A1"; status = "PROPOSED"; errors = []
            return R()

    class _Ctx: actor = "agent@x"

    r = ResolverFactory.make_review_withdrawal_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, withdrawal_id="W1", recommendation="reject", rationale="spike")
    assert out.status == "PROPOSED"
    assert seen["type_id"] == "review_withdrawal" and seen["object_id"] == "W1"
    assert seen["params"]["recommendation"] == "reject"


def test_override_resolver_calls_service():
    seen = {}

    class _Svc:
        def override(self, aid, approver, decision, reason, ctx):
            seen.update(aid=aid, approver=approver, decision=decision, reason=reason)
            class R: action_id = aid; status = "OVERRIDDEN"; errors = []
            return R()

    class _Ctx: actor = "human@x"

    r = ResolverFactory.make_override_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1", decision="approve", reason="known customer")
    assert out.status == "OVERRIDDEN"
    assert seen["approver"] == "human@x" and seen["decision"] == "approve"
    assert seen["reason"] == "known customer"


def test_override_resolver_catches_actionerror():
    class _Svc:
        def override(self, *a, **k): raise ActionError("cannot override action in status APPLIED")

    class _Ctx: actor = "human@x"

    r = ResolverFactory.make_override_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1", decision="approve", reason="x")
    assert out.status == "ERROR" and out.errors and "override" in out.errors[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_review_withdrawal_mutation.py -v`
Expected: FAIL — `AttributeError: ... make_review_withdrawal_resolver`.

- [ ] **Step 3: Write minimal implementation**

Add to `ResolverFactory` (after `make_reject_resolver`, around line 153):

```python
    @staticmethod
    def make_review_withdrawal_resolver(service_factory, ctx_factory):
        """Mutation resolver: an agent proposes a withdrawal-review decision."""
        from typing import Optional
        from strawberry.scalars import JSON

        def reviewWithdrawal(info: Info, withdrawal_id: str, recommendation: str,
                             rationale: str = "",
                             risk_assessment: Optional[JSON] = None) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, withdrawal_id)
            res = svc.propose(
                "review_withdrawal", withdrawal_id,
                {"withdrawal_id": withdrawal_id, "recommendation": recommendation,
                 "rationale": rationale, "risk_assessment": risk_assessment},
                ctx)
            return ActionMutationResult(
                action_id=str(res.action_id) if res.action_id else None,
                status=res.status, errors=list(res.errors))
        return reviewWithdrawal

    @staticmethod
    def make_override_resolver(service_factory, ctx_factory):
        """Mutation resolver: a human overrides a PROPOSED action with their own decision."""
        from back.objects.actions.service import ActionError

        def overrideAction(info: Info, action_id: strawberry.ID, decision: str,
                           reason: str) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.override(str(action_id), ctx.actor, decision, reason, ctx)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return overrideAction
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_review_withdrawal_mutation.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/back/core/graphql/ResolverFactory.py \
        tests/units/actions/test_review_withdrawal_mutation.py
git commit -m "feat(actions): reviewWithdrawal + overrideAction resolvers (annotated, ActionError-safe)"
```

---

## Task 4: Wire the new fields into the Mutation type (build through strawberry)

**Files:**
- Modify: `src/back/core/graphql/GraphQLSchemaBuilder.py:506-536` (`_build_mutation`)
- Test: append to `tests/units/actions/test_review_withdrawal_mutation.py`

- [ ] **Step 1: Write the failing test** (append to the file from Task 3)

```python
def test_mutation_sdl_has_review_and_override():
    from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
    import strawberry

    mut = GraphQLSchemaBuilder._build_mutation(
        service_factory=lambda info: None, ctx_factory=lambda info, oid: None)

    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str: return "ok"

    sdl = strawberry.Schema(query=Query, mutation=mut).as_str()
    assert "reviewWithdrawal" in sdl
    assert "overrideAction" in sdl
    # slice-3 governance fields remain
    assert "approveAction" in sdl and "rejectAction" in sdl
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_review_withdrawal_mutation.py::test_mutation_sdl_has_review_and_override -v`
Expected: FAIL — `reviewWithdrawal`/`overrideAction` not in SDL.

- [ ] **Step 3: Write minimal implementation**

In `_build_mutation`, add two fields to `mutation_fields` (keep `flagCustomerHighRisk` for now — removed in Task 7). Insert a `reviewWithdrawal` field and an `overrideAction` field:

```python
            strawberry.field(
                name="reviewWithdrawal",
                resolver=ResolverFactory.make_review_withdrawal_resolver(
                    service_factory=service_factory, ctx_factory=ctx_factory),
                description="Agent proposes an approve/reject decision on a risky withdrawal.",
            ),
            strawberry.field(
                name="overrideAction",
                resolver=ResolverFactory.make_override_resolver(
                    service_factory=service_factory, ctx_factory=ctx_factory),
                description="Human overrides a PROPOSED action with their own decision + reason.",
            ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_review_withdrawal_mutation.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/back/core/graphql/GraphQLSchemaBuilder.py \
        tests/units/actions/test_review_withdrawal_mutation.py
git commit -m "feat(actions): expose reviewWithdrawal + overrideAction on the Mutation type"
```

---

## Task 5: `Withdrawal.decision` overlay read-back (build through strawberry)

**Files:**
- Test: `tests/units/actions/test_withdrawal_overlay_field.py` (new)

This verifies the registry-driven overlay-field attachment surfaces `Withdrawal.decision` as a `JSON` field when a `Withdrawal` ontology class is present. `ReviewWithdrawal` is registered (Task 1), so `default_registry.overlay_fields_by_type()` includes `{"Withdrawal": {"decision"}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_withdrawal_overlay_field.py
"""The Withdrawal.decision overlay read-back field is attached when the
fraud ontology has a Withdrawal class. Built through strawberry."""
import back.objects.actions.types  # noqa: F401  (registers ReviewWithdrawal)
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder


def test_withdrawal_decision_field_present_in_sdl():
    classes = [{"name": "Withdrawal", "uri": "http://ex/fraud/Withdrawal",
                "dataProperties": [{"name": "amount", "uri": "http://ex/fraud/amount"}]}]
    props = []
    builder = GraphQLSchemaBuilder()
    result = builder.build_for_domain(
        classes, props, "http://ex/fraud/", "fraud",
        overlay_connect=lambda: None)          # connect never called at build time
    assert result is not None
    schema, _meta = result
    sdl = schema.as_str()
    assert "type Withdrawal" in sdl
    assert "decision" in sdl          # overlay-backed JSON field
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/units/actions/test_withdrawal_overlay_field.py -v`
Expected: PASS once `ReviewWithdrawal` is registered (Task 1). If it FAILS with `decision` absent, confirm `import back.objects.actions.types` ran and `overlay_fields_by_type()` includes `Withdrawal`. (This task is a guard test; if it already passes, keep it as a regression guard.)

- [ ] **Step 3: (only if failing) Fix**

No production change expected — the slice-2 `_add_overlay_fields` path already attaches declared overlay fields. If the field is missing, the cause is registration order; ensure `types/__init__.py` registers `ReviewWithdrawal` (Task 1).

- [ ] **Step 4: Commit**

```bash
git add tests/units/actions/test_withdrawal_overlay_field.py
git commit -m "test(actions): Withdrawal.decision overlay read-back present in SDL"
```

---

## Task 6: Fraud domain + seed withdrawals (operational setup)

**Files:**
- Create: `scripts/seed_fraud_withdrawals.sql`

This task is operational (no unit test). It provides sample withdrawals so the loop can be exercised in-browser. The `fraud` domain's `Withdrawal` ontology + R2RML mapping is built in the app (Domain → Metadata → Import Metadata, then build the Digital Twin) against the seeded table; that UI step is documented in the changelog/runbook, not scripted here.

- [ ] **Step 1: Write the seed SQL**

```sql
-- scripts/seed_fraud_withdrawals.sql
-- Sample risky withdrawals for the fraud POC. Load into the catalog/schema the
-- fraud domain's R2RML mapping reads from. Adjust the fully-qualified name to the
-- target client (e.g. sandbox.fraud.withdrawals).
CREATE TABLE IF NOT EXISTS fraud_withdrawals (
    withdrawal_id text PRIMARY KEY,
    account_id    text NOT NULL,
    amount        numeric NOT NULL,
    channel       text NOT NULL,
    device        text,
    geo           text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fraud_withdrawals (withdrawal_id, account_id, amount, channel, device, geo) VALUES
  ('W1001', 'ACC-001', 95000, 'atm',    'new-device', 'MX-DF'),
  ('W1002', 'ACC-002',  4200, 'transfer','known',     'MX-NL'),
  ('W1003', 'ACC-003', 75000, 'transfer','new-device','US-TX')
ON CONFLICT (withdrawal_id) DO NOTHING;
```

- [ ] **Step 2: Verify it parses**

Run: `python -c "open('scripts/seed_fraud_withdrawals.sql').read(); print('ok')"`
Expected: `ok` (file present/readable; SQL is executed against Lakebase during domain setup, out of band).

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_fraud_withdrawals.sql
git commit -m "chore(fraud): seed sample withdrawals for the fraud POC domain"
```

---

## Task 7: Retire the customer POC (`flag_customer_high_risk`)

**Files:**
- Delete: `src/back/objects/actions/types/flag_customer_high_risk.py`
- Modify: `src/back/objects/actions/types/__init__.py`
- Modify: `src/back/core/graphql/GraphQLSchemaBuilder.py:_build_mutation` (drop `flagCustomerHighRisk` field)
- Modify: `src/back/core/graphql/ResolverFactory.py` (remove `make_action_mutation_resolver`)
- Modify/Delete: tests referencing the customer type (see Step 1)

- [ ] **Step 1: Find everything referencing the retired type**

Run: `uv run grep -rl -e flag_customer_high_risk -e FlagCustomerHighRisk -e flagCustomerHighRisk -e make_action_mutation_resolver -e riskFlag src/ tests/`
Expected: a list including `types/__init__.py`, `GraphQLSchemaBuilder.py`, `ResolverFactory.py`, `tests/units/actions/test_sod_decl.py`, and any slice-2 overlay read-back test asserting `Customer.riskFlag`. Read each before editing.

- [ ] **Step 2: Remove the registration + the file**

```python
# src/back/objects/actions/types/__init__.py
"""Code-registered Action Types. Importing this package registers them on
``back.objects.actions.registry.default_registry``."""
from back.objects.actions.registry import default_registry
from back.objects.actions.types.review_withdrawal import ReviewWithdrawal

default_registry.register(ReviewWithdrawal())
```

```bash
git rm src/back/objects/actions/types/flag_customer_high_risk.py
```

- [ ] **Step 3: Remove the `flagCustomerHighRisk` mutation field**

In `_build_mutation`, delete the `strawberry.field(name="flagCustomerHighRisk", ...)` entry (the first item in `mutation_fields`). The list then contains `reviewWithdrawal`, `overrideAction`, `approveAction`, `rejectAction`.

- [ ] **Step 4: Remove `make_action_mutation_resolver`**

Delete the `make_action_mutation_resolver` static method from `ResolverFactory` (lines ~96-117). It was only used for the customer propose field.

- [ ] **Step 5: Update/retire the affected tests**

- `tests/units/actions/test_sod_decl.py` — it asserts `FlagCustomerHighRisk.requires_separate_approver`. Replace its subject with `ReviewWithdrawal` (same assertion: `requires_separate_approver is True`, `overlay_fields == ["decision"]`). If the file's sole purpose was the customer type, rewrite it to assert against `ReviewWithdrawal`; otherwise edit the relevant cases.
- Any slice-2 test asserting `Customer.riskFlag` in SDL or an overlay value: re-point to `Withdrawal`/`decision`, or delete the case if it duplicates Task 5's guard. Read the test first; preserve coverage intent.
- `tests/units/actions/test_approve_reject_mutation.py::test_mutation_sdl_has_approve_and_reject` — unaffected (only asserts approve/reject); leave as-is.

- [ ] **Step 6: Run the full action + graphql suites**

Run: `uv run pytest tests/units/actions tests/units/graphql -v`
Expected: PASS — no references to the retired type remain; `grep` from Step 1 (re-run) returns nothing under `src/`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(actions): retire flag_customer_high_risk customer POC (fraud replaces it)"
```

---

## Task 8: Docs + changelog

**Files:**
- Modify: `docs/architecture.md`, `README.md`
- Create/append: `changelogs/v0.4.0/2026-06-08.log` (prepend a slice-4 section)

- [ ] **Step 1: Read the current Kinetic Actions sections**

Read the "Kinetic Actions" entry-points section in `docs/architecture.md` and the Kinetic Actions blurb in `README.md` (added in slices 1-3). Note the exact wording so the update is consistent.

- [ ] **Step 2: Update `docs/architecture.md`**

Replace customer-flagging examples with the fraud loop: `review_withdrawal` (agent proposes), accept via `approveAction`, override via `overrideAction`, the `Withdrawal.decision` overlay value shape `{agent_recommendation, human_decision, agreed, decided_by, reason, decided_at}`, the new `OVERRIDDEN` status, and that the effect is `noop` for now (moneypool API write-back is slice 6, the agent is slice 5). Note RBAC stays deferred.

- [ ] **Step 3: Update `README.md`**

Update the Kinetic Actions blurb: the POC is fraud withdrawal review (agent proposes, human accepts/overrides); the customer flag demo is retired.

- [ ] **Step 4: Write the changelog section** (prepend; use the version from `pyproject.toml`)

Create or prepend to `changelogs/v0.4.0/2026-06-08.log` a section titled "Fraud withdrawal review — slice 4 (decision loop)" with: context, numbered changes with file paths, the modified-files list, and the test result (fill in actual counts after Step 5).

- [ ] **Step 5: Run the full unit suite and record results**

Run: `uv run pytest tests/units`
Expected: PASS except the 2 known pre-existing unrelated `tests/units/api/test_external_api.py::TestDomainVersions` failures (registry-not-configured offline). Record exact counts in the changelog.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md README.md changelogs/
git commit -m "docs(actions): fraud withdrawal review loop (slice 4) + changelog"
```

---

## Definition of done (slice 4)

- `review_withdrawal` proposes a decision; `approveAction` accepts it; `overrideAction` substitutes a human decision with a required reason; `Withdrawal.decision` overlay reflects either path with an `agreed` flag and preserved agent recommendation.
- `OVERRIDDEN` status persists; no schema migration was needed.
- `flag_customer_high_risk` retired; no `src/` references remain.
- Full unit suite green except the 2 known pre-existing `TestDomainVersions` failures.
- Docs + changelog updated. Agent (slice 5) and moneypool API effect (slice 6) remain out of scope.
