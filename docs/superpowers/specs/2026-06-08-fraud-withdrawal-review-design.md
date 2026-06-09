# Fraud withdrawal review — Design (kinetic slice 4+)

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan

> **Update 2026-06-09:** the core object was generalised from `Withdrawal` to
> **`Transaction`** before merge (action `review_transaction`, mutation
> `reviewTransaction`, overlay `Transaction.decision`, agent tool
> `propose_review_transaction`). Withdrawals are the first reviewed type,
> distinguished by `txn_type`/`direction` columns on the source table rather than
> by the ontology. Everything below reads "withdrawal" as the original design
> vocabulary; the shipped names use "transaction".
**Branch base:** `mp/master` (kinetic slices 1–3 merged)
**Builds on:** `docs/superpowers/specs/2026-06-08-kinetic-action-layer-design.md`,
`docs/superpowers/specs/2026-06-08-kinetic-approve-reject-design.md`

## Goal

Pivot the POC from AML customer-flagging to **fraud detection on bank
withdrawals**. An **agent proposes** an approve/reject decision on a risky
withdrawal; a **human reviewer accepts or overrides** it. Decisions are recorded
on the kinetic overlay (system-of-record) and written back to moneypool's main
app via API. This is *fraud*, not AML, and lives in a **new `fraud` domain**;
the customer `flag_customer_high_risk` POC is retired.

## Decisions (locked)

- **Core object: `Withdrawal`.** Carries raw features (`amount`, `channel`,
  `account_id`, `recent_txns`, `device`, `geo`, …). The agent computes risk from
  these features — risk logic lives in the agent, not an upstream score.
- **Agent proposes, human is the authority.** An agent (`actor_kind='agent'`)
  auto-proposes a `review_withdrawal` action for incoming risky withdrawals,
  which queue for human review. The human **accepts** (agent's decision applied
  as-is) or **overrides** (human substitutes their own decision). The agent's
  recommendation is **always preserved** for audit + future model evaluation.
- **Accept reuses slice-3 `approveAction`** exactly (4-eyes naturally satisfied:
  proposer = agent, approver = human). **Override is one new mutation**
  `overrideAction`. No reject-then-propose two-step; no parallel decision path.
- **4-eyes applies; approver RBAC stays deferred** (consistent with slices 1–3).
- **Downstream effect: write back to moneypool's main app via API** on apply
  (release/block the withdrawal), via the existing outbox + EffectRunner.
- **New `fraud` domain; retire the customer POC** (`flag_customer_high_risk` +
  `Customer.riskFlag` demo removed/deprecated).

## Flow

```
1. Agent computes risk from the Withdrawal's features and PROPOSES
   review_withdrawal(withdrawal_id, recommendation, rationale, risk_assessment)
        → action_log: PROPOSED   (agent recommendation preserved in params)

2. Withdrawal enters a human review queue (GraphQL: pending-decision withdrawals).

3. Human reviewer:
     ACCEPT   → approveAction(actionId)                       [slice-3, reused]
                  → APPLIED;  decision.human = agent rec; agreed=true
     OVERRIDE → overrideAction(actionId, decision, reason)    [new]
                  → agent row OVERRIDDEN (human decision+reason in `after`)
                  → final decision overlay written; agreed=false

4. On apply (either path) the overlay Withdrawal.decision is set (see below).

5. Post-commit Effect `moneypool_decision_callback` POSTs the decision to
   moneypool's main-app API. Retryable via the existing outbox.
```

## Decision overlay value

`Withdrawal.decision`, written at apply time on both paths:

```jsonc
{
  "agent_recommendation": "approve" | "reject",  // from the proposal params
  "human_decision":       "approve" | "reject",  // = agent_recommendation on accept
  "agreed":               true | false,           // human_decision == agent_recommendation
  "decided_by":           "<approver identity>",
  "reason":               "<string>",             // required on override, optional on accept
  "decided_at":           "<timestamp>"
}
```

`agreed` is the accept-vs-override signal and the basis for later agent evaluation.

## Action-log lifecycle

- **Accept:** agent's row `PROPOSED → APPROVED → APPLIED` (existing slice-3 path).
  Overlay written with `human_decision = agent_recommendation`, `agreed=true`,
  `decided_by=approver`.
- **Override:** agent's row `PROPOSED → OVERRIDDEN` (new terminal status). In the
  **same transaction**, `override()` writes the final decision overlay with the
  human's decision (`agreed=false`) and records
  `{human_decision, reason, decided_by}` in the row's `after`. The agent's
  recommendation stays in the row's `params` — one row tells the whole story.

Mechanically, `service` passes the approver and an optional `decision_override`
into the apply step; `review_withdrawal.apply()` composes the `decision` value
from the proposal params + those. `approve` is enriched so the applied overlay
records `decided_by`/`agreed=true`.

## Components

| Component | File | What |
|---|---|---|
| Withdrawal review ActionType | `objects/actions/types/review_withdrawal.py` (new) | `id="review_withdrawal"`, `object_type="Withdrawal"`, `overlay_fields=["decision"]`, `requires_separate_approver=True`, `approval_policy=REQUIRES_APPROVAL`, params `{withdrawal_id, recommendation, rationale, risk_assessment}` |
| Override mechanics | `objects/actions/service.py`, `base.py` | new `ActionService.override(action_id, approver, decision, reason)`; new `OVERRIDDEN` status; `approve` enriched to record `decided_by`/`agreed=true` |
| Override mutation | `core/graphql/ResolverFactory.py`, `GraphQLSchemaBuilder.py` | `make_override_resolver` (annotated, `ActionError`-safe) + `overrideAction(actionId, decision, reason)` field. `Withdrawal.decision` read-back comes free from the overlay-fields registry |
| Real Effect | `objects/actions/effects.py` + gitignored config | `moneypool_decision_callback` — HTTP POST to the main-app API; endpoint/auth in per-client config |
| Fraud agent | `agents/…` (new) | computes risk from features, proposes via the MCP action tool as `actor_kind='agent'` |
| Fraud domain + data | app-side / seed | `Withdrawal` ontology + a source of withdrawal rows (seed for POC) |

## Error handling

All raised as `ActionError`, caught in the resolver → `ActionMutationResult(status="ERROR", errors=[msg])`, never a 500 (per slice 3):

- `override` of a non-`PROPOSED` action.
- `decision` not in `{"approve","reject"}`.
- empty `reason` on override.
- unknown action id.
- Apply failure → existing single-transaction rollback; the effect fires only post-commit.

## Testing

TDD per task; build-through-strawberry discipline (the slice-1/2 lesson):

- `override()` state transition (`PROPOSED → OVERRIDDEN`) + non-`PROPOSED` guard.
- Overlay composition: accept (`agreed=true`, `human=agent_rec`) vs override (`agreed=false`, `human=override decision`).
- `reason` required on override; `decision` enum validation.
- Build-through-strawberry SDL check: `overrideAction` + `Withdrawal.decision` present on the schema.
- Agent recommendation preserved after override (row `params` intact).

## Scope / slicing

This feature is more than one PR. Decomposed into working increments (each its own plan → implementation), consistent with slices 1–3:

- **Slice 4 — the decision loop (FIRST, this plan).** Fraud domain + `Withdrawal`
  ontology/seed (task 1) → `review_withdrawal` ActionType → `OVERRIDDEN` status +
  `ActionService.override` + enriched `approve` → `overrideAction` mutation +
  `Withdrawal.decision` read-back. Effect stays `noop`; agent is a manual/stub
  propose. Proves accept/override end-to-end in the browser.
- **Slice 5 — the fraud agent.** Real risk computation from features + auto-propose.
- **Slice 6 — moneypool API effect.** Real `moneypool_decision_callback` write-back
  to the main app.

### Out of scope (this slice)

Approver role/authz gating; the real fraud agent (slice 5); the real main-app API
connector (slice 6); production withdrawal-table ingestion (seed data for the POC).

## File / change map (slice 4)

- `src/back/objects/actions/types/review_withdrawal.py` — new ActionType.
- `src/back/objects/actions/base.py` — add `OVERRIDDEN` to `ActionStatus`.
- `src/back/objects/actions/service.py` — `override(...)`; enrich `approve` apply to record `decided_by`/`agreed`.
- `src/back/core/graphql/ResolverFactory.py` — `make_override_resolver` (annotated, `ActionError`-catching).
- `src/back/core/graphql/GraphQLSchemaBuilder.py` — add `overrideAction(actionId, decision, reason)` field.
- `src/back/objects/actions/types/flag_customer_high_risk.py` — removed/deprecated (customer POC retired).
- Fraud domain `Withdrawal` ontology + seed withdrawals (app-side / fixture; task 1 of the plan).
- `tests/units/actions/` + graphql tests — override, accept-vs-override overlay, OVERRIDDEN guard, build-through-strawberry.
- `docs/architecture.md`, `README.md` — fraud-review loop; note agent + API effect deferred.
