# Kinetic approve / reject GraphQL mutations — Design (Slice 3)

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan
**Branch base:** `mp/master` (kinetic slices 1 + 2)
**Builds on:** `docs/superpowers/specs/2026-06-08-kinetic-action-layer-design.md`

## Goal

Expose the kinetic lifecycle's `approve` / `reject` over GraphQL so the **full
loop runs end-to-end in the browser** (propose → a *different* user approves →
`Customer.riskFlag` reflects it) and so AML can later drive approvals via the
API. `ActionService.approve(action_id, approver, ctx)` and
`reject(action_id, approver)` already exist; today only `flagCustomerHighRisk`
(propose) is exposed.

## Decisions (locked)

- **Segregation of duties: configurable per ActionType.** A new
  `ActionType.requires_separate_approver: bool = False` (default keeps existing /
  AUTO actions unaffected). `FlagCustomerHighRisk` sets it `True`. SoD applies to
  **approve only** — withdrawing/rejecting your own proposal is allowed.
- **Authz: deferred.** No approver-role check this slice; safety rests on the
  `PROPOSED`-state guard + SoD. Role-gating lands with the AML/auth slice.

## Components

**1. `ActionType.requires_separate_approver: bool = False`** (`action_type.py`)
`FlagCustomerHighRisk.requires_separate_approver = True`.

**2. `AuditLog.get` returns the proposer** (`audit.py`)
Add `actor` to the SELECT + returned dict so `approve` can compare approver vs
proposer. (Currently returns action_type/domain/object_type/object_id/params/status.)

**3. `ActionService.approve` enforces SoD** (`service.py`)
After the existing `rec["status"] != "PROPOSED"` guard:
```python
atype = self._registry.get(rec["action_type"])
if getattr(atype, "requires_separate_approver", False) and approver == rec["actor"]:
    raise ActionError("4-eyes: the proposer cannot approve their own action")
```
`reject` is unchanged re: SoD. `reject` gains an optional `reason: str = ""`
recorded on the audit row (stored in `after` jsonb as `{"rejected_reason": reason}`
via the existing `mark(..., after=...)`).

**4. GraphQL mutations** (`ResolverFactory.py`, `GraphQLSchemaBuilder.py`)
Two new fields on the `Mutation` type (added in `_build_mutation` alongside
`flagCustomerHighRisk`):
- `approveAction(actionId: ID!): ActionMutationResult`
- `rejectAction(actionId: ID!, reason: String = ""): ActionMutationResult`

New resolver factories `make_approve_resolver(service_factory, ctx_factory)` and
`make_reject_resolver(service_factory, ctx_factory)`. Both:
- are **fully annotated** (`info: Info`, `-> ActionMutationResult`) — the
  slice-1/2 bug lesson; tests build the schema **through strawberry**.
- derive the **approver from the current user** (`ctx.actor`, the same
  `x-forwarded-email`/`request.state.user_email` extraction the route already does
  in `ctx_factory`).
- **catch `ActionError`** (not-`PROPOSED`, SoD violation, unknown action) and
  return `ActionMutationResult(action_id=..., status="ERROR", errors=[str(exc)])`
  — a clean client result, never a 500.

`_build_mutation` already builds the `Mutation` type with `service_factory` /
`ctx_factory`; it gains the two extra fields. No route change needed — the
existing `request`-present path already supplies the factories.

## Data flow

```
mutation { approveAction(actionId:"<uuid>") { actionId status errors } }
  → make_approve_resolver → ActionService.approve(uuid, approver=ctx.actor, ctx)
      • load action_log (status must be PROPOSED)
      • SoD: if requires_separate_approver and approver == proposer → ActionError → {status:"ERROR", errors:[...]}
      • else mark APPROVED → _apply (overlay ACTIVE + audit APPLIED + effects)
  → {actionId, status:"APPLIED", errors:[]}
mutation { rejectAction(actionId:"<uuid>", reason:"false positive") { ... } }
  → ActionService.reject(uuid, approver=ctx.actor, reason) → mark REJECTED (+reason)
  → {actionId, status:"REJECTED", errors:[]}
```
End-to-end: user A proposes `flagCustomerHighRisk` → `PROPOSED`; user B `approveAction`
→ `APPLIED`; `customer { riskFlag }` now returns `{severity, reason}`. User A approving
their own → `{status:"ERROR", errors:["4-eyes: ..."]}`.

## Error handling
- Not `PROPOSED` / unknown action / SoD violation → `ActionError` caught in the
  resolver → `ActionMutationResult(status="ERROR", errors=[msg])`. No 500.
- `approve` apply failure → the existing single-transaction rollback (overlay/audit
  untouched). Effects fire post-commit as before.

## Scope / non-goals
In scope: `approve`/`reject` mutations, per-type SoD, reject reason. Out of scope
(later slices): approver role/authz gating; AML service-to-service auth; a flags
list/"changed-since" read surface; the `prod_webhook` Effect; the real Delta/AML
connector. SoD applies only to `approve`.

## File / change map
- `src/back/objects/actions/action_type.py` — add `requires_separate_approver: bool = False`.
- `src/back/objects/actions/types/flag_customer_high_risk.py` — set it `True`.
- `src/back/objects/actions/audit.py` — `AuditLog.get` returns `actor`.
- `src/back/objects/actions/service.py` — SoD check in `approve`; `reject(reason="")` records reason.
- `src/back/core/graphql/ResolverFactory.py` — `make_approve_resolver`, `make_reject_resolver` (annotated, ActionError-catching).
- `src/back/core/graphql/GraphQLSchemaBuilder.py` — add the two fields in `_build_mutation`.
- `tests/units/actions/` + graphql tests — SoD, approve/reject outcomes, build-through-strawberry, resolver error result.
