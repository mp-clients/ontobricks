# Kinetic Action Layer — Design (Vertical Slice 1)

**Date:** 2026-06-08
**Status:** Approved (design); pending implementation plan
**Scope:** First production-shaped Action primitive for OntoBricks, proving the
"kinetic" half of the ontology (à la Palantir Foundry) end-to-end on the live
`customers` domain.

## Goal

OntoBricks today is the **semantic** half of an ontology: object types, links,
properties, mappings, and a derived read-only triple store. This adds the
**kinetic** half — typed, validated, audited, reversible *Actions* that change
ontology state — built as a small but real framework that future Actions plug
into. The concrete first Action is **`flag_customer_high_risk`**.

## Context (current state)

- Object-instance data is **one-way and read-only**: source → R2RML mappings →
  triple store (rebuilt on every sync). The only existing writes are
  registry/config (domains, versions, permissions, schedules, global config) in
  Lakebase via `RegistryStore`.
- Reusable building blocks already present:
  - `src/agents/tools/` — tool definition + handler dict pattern (`SQL_TOOL_DEFINITIONS` / `SQL_TOOL_HANDLERS`) with a `ToolContext`.
  - `back/core/task_manager` — `run_background_task(...)` + `TaskManager` (create/start/complete/fail + steps): async worker primitive.
  - `back/core/graphql` — `GraphQLSchemaBuilder` + `ResolverFactory` (strawberry). **Query-only today; no Mutation type yet.**
  - `back/core/w3c/shacl/SHACLService.validate_graph` — reusable Action preconditions.
  - `back/core/reasoning/ReasoningService` — decision tables / SWRL / SPARQL rules — reusable for validation/effects.
- Live deployment: `ontology` app on the `moneypool` (risk-management) workspace,
  Lakebase registry schema `ontology_registry`, warehouse `ontos`.

## Decisions (locked with stakeholder)

1. **Build the real framework** (not a throwaway PoC) — a small production-shaped Action primitive.
2. **Overlay is authoritative.** Action edits live in an OntoBricks-owned Lakebase store; source tables are untouched.
3. **Overlay + audit + Effect *seam*** this slice. Pluggable Effect interface + outbox table, but **no live connector** (ships a no-op/log effect).
4. **Approval policy is per Action Type.** Full lifecycle `PROPOSED → APPROVED → APPLIED → REJECTED/REVERTED/FAILED`. `flag_customer_high_risk` = `REQUIRES_APPROVAL`.
5. **Entry surfaces:** one `ActionService` core, exposed via (a) the first **GraphQL Mutation** and (b) an **agents/tools** handler (the kinetic-agent loop). UI button later.
6. **Read-back via an overlay-backed object field** — `Customer.riskFlag` resolves from the overlay store; the triple-store sync pipeline is **not** touched.
7. **Approach A** (code-registered Action Types + generic property-edit overlay).

### North star (explicitly deferred): Approach B

The end-state we are building *toward* is **ontology-defined Action Types** —
Action Types declared as data in the ontology/registry and interpreted by the
framework (no-code authoring), as in Foundry. Approach A must therefore keep the
**registry as a seam**: the Action Type registry is populated from code now, but
designed so it can later be populated from ontology metadata **without rewriting
`ActionService`, the overlay, the audit log, or the effect machinery.**

## Architecture & components

New subpackage `back/objects/actions/` plus thin adapters into existing surfaces.
One core service; everything else is an adapter or a store.

```
        GraphQL Mutation adapter            agents/tools: action tool
        (back/core/graphql)                 (src/agents/tools/actions.py)
                  \                              /
                   \                            /
                ┌──────────────────────────────────┐
                │          ActionService (core)      │   back/objects/actions/
                │  resolve type → validate →         │
                │  lifecycle → apply → audit →       │
                │  enqueue effects                   │
                └─────┬────────────┬─────────────────┘
            ┌─────────┘      │      └──────────────────────┐
      ActionType registry  OverlayStore          AuditLog + EffectOutbox
      (Python classes;     (Lakebase:            (Lakebase: action_log,
       seam → ontology = B) ontology_overlay)     action_effects_outbox)
                                  │
                            GraphQL resolver reads overlay → Customer.riskFlag
                            (read-back; no triple-store change)

      EffectRunner (worker via task_manager) drains outbox → Effect connectors
      (slice ships a no-op/log Effect; Delta/SAP connectors plug in later)
```

**Components:**

1. **`ActionType`** (abstract) + **registry.** Each type declares: `id`, bound
   `object_type`, Pydantic `params` schema, `approval_policy`
   (`AUTO` | `REQUIRES_APPROVAL`), `validate(ctx, params)`,
   `apply(ctx, params) -> list[OverlayEdit]`, `effects()`. Registered like
   `SQL_TOOL_DEFINITIONS`/`HANDLERS`. **Seam for B:** registry loadable from
   ontology metadata later.
2. **`ActionService`** — the *only* mutation path. Resolve type → validate
   (reuses `SHACLService` / `ReasoningService`) → advance lifecycle → write
   overlay + audit atomically → enqueue effects. Pure orchestration; knows
   nothing about GraphQL or agents.
3. **`OverlayStore`** — Lakebase, generic property-edit table; authoritative
   operational truth. Follows the existing registry-store/Lakebase access pattern.
4. **`AuditLog` + `EffectOutbox`** — immutable action records + pending effects.
5. **`EffectRunner`** — drains the outbox via `task_manager.run_background_task`,
   runs `Effect` connectors with retries/status. Slice ships one no-op/log Effect
   behind the interface.
6. **Adapters** — (a) first **GraphQL `Mutation`** type on the schema builder;
   (b) **agent tool** in `agents/tools/`. Both marshal params into `ActionService`.
7. **Read-back resolver** — `Customer.riskFlag` resolves from `OverlayStore`.

First concrete Action: **`flag_customer_high_risk`** — bound to the `customers`
domain Customer object; the customer is identified by `object_id`, params are
`{reason, severity}`; `approval_policy = REQUIRES_APPROVAL`.

## Data model

Tables live in the existing `ontology_registry` Lakebase schema.

```
action_log                      -- immutable; one row per Action invocation
  action_id (uuid, pk)
  action_type        text       -- 'flag_customer_high_risk'
  domain             text
  object_type        text       -- 'Customer'
  object_id          text
  params             jsonb
  actor              text        -- user email OR agent id
  actor_kind         text        -- 'user' | 'agent'
  status             text        -- PROPOSED|APPROVED|APPLIED|REJECTED|REVERTED|FAILED
  before             jsonb        -- overlay state pre-apply (revert/audit)
  after              jsonb
  created_at, applied_at, ts
  approved_by        text null
  parent_action_id   uuid null    -- a REVERT points at what it reverts

ontology_overlay                -- authoritative property edits (the overlay)
  domain, object_type, object_id, property, value (jsonb)
  action_id          uuid         -- provenance → action_log
  status             text         -- ACTIVE | SUPERSEDED | REVERTED
  valid_from, valid_to            -- bitemporal-lite; current = status ACTIVE
  pk (domain, object_type, object_id, property, valid_from)

action_effects_outbox           -- pending external effects (seam; no live connector)
  effect_id (uuid, pk), action_id, effect_name, payload jsonb,
  status (PENDING|RUNNING|DONE|FAILED), attempts, last_error, next_attempt_at
```

### Lifecycle state machine (per-type `approval_policy`)

```
AUTO:              PROPOSED → APPLIED              (validate passes → apply immediately)
REQUIRES_APPROVAL: PROPOSED → APPROVED → APPLIED   (or → REJECTED)
any APPLIED:       → REVERTED                      (compensating action; new log row)
validate/apply fail: → FAILED                      (nothing written to overlay)
```

"Current value of property P on object O" = newest `ontology_overlay` row with
`status=ACTIVE`. The `Customer.riskFlag` resolver does exactly this lookup.

## Data flow — `flag_customer_high_risk` (REQUIRES_APPROVAL)

```
1. Agent or GraphQL mutation → ActionService.propose(
     type='flag_customer_high_risk', object_id=C, params={severity, reason}, actor)
2. Registry resolves ActionType → Pydantic validates params (shape)
3. validate(): semantic preconditions
     • object exists in domain graph
     • SHACLService.validate_graph on the proposed post-state (targeted shape)
     • optional DecisionTableEngine rule (e.g. severity ≥ X requires reason)
   fail ⇒ status FAILED, nothing written, return structured errors
4. Policy REQUIRES_APPROVAL ⇒ write action_log row status=PROPOSED, return action_id
5. ActionService.approve(action_id, approver):
     BEGIN (one Lakebase txn)
       upsert ontology_overlay: Customer/C/riskFlag = {severity, reason}, status=ACTIVE
       supersede any prior ACTIVE riskFlag row
       update action_log → APPLIED (before/after captured)
       insert action_effects_outbox (effect='noop_log', PENDING)
     COMMIT
6. EffectRunner (task_manager worker) drains outbox → runs noop_log effect → DONE
7. Read-back: GraphQL `customer(id:C){ riskFlag }` resolver reads overlay → shows flag
8. Revert: ActionService.revert(action_id) → compensating action,
     overlay row → REVERTED, new action_log row (parent_action_id set)
```

`Mutation.flagCustomerHighRisk(...)` and the agent tool are ~10-line adapters
that call `propose`/`approve`.

## Validation & approval wiring

- `validate()` reuses `SHACLService` + `ReasoningService` — **no new rule engine**.
- `approval_policy` is a field on the ActionType; `ActionService` branches on it.
  Flipping an Action `REQUIRES_APPROVAL → AUTO` is a one-line change.

## Error handling

- **Validation failure** → `FAILED`, overlay untouched, structured errors to caller.
- **Apply txn failure** → atomic rollback (no partial overlay/audit/outbox).
- **Effect failure** → isolated in the outbox (retries w/ backoff,
  `attempts`/`last_error`); **never** affects committed authoritative state.
  Surfaced as effect status, not Action failure.
- **Concurrent edits to same property** → last-writer-wins via `valid_from`; prior
  row marked `SUPERSEDED` (full history retained).

## Testing

- **Unit:** registry resolution; Pydantic param validation; `validate()`
  happy/precondition-fail; lifecycle transitions for both policies (illegal
  transitions rejected); overlay upsert/supersede/revert; "current value" read;
  outbox enqueue.
- **Integration (against Lakebase):** propose→approve→APPLIED writes
  overlay+audit+outbox in one txn; `EffectRunner` drains outbox; GraphQL mutation
  path; agent-tool path; `customer.riskFlag` read-back reflects applied flag;
  revert restores prior state.
- **Effect seam:** a fake connector asserts it receives the event and that its
  failure does **not** roll back the Action.

## Scope / non-goals (this slice)

Out of scope (later slices): live Effect connectors (Delta sync, SAP, notify);
ontology-defined Action Types (north star B); UI action button; merging the
overlay into the triple store / SPARQL; Functions registry (typed compute bound
to object types); multi-object/transactional batch Actions.

## File / placement map

- `src/back/objects/actions/__init__.py` — package + registry seam
- `src/back/objects/actions/base.py` — `ActionType` ABC, `OverlayEdit`, lifecycle enums
- `src/back/objects/actions/service.py` — `ActionService`
- `src/back/objects/actions/overlay_store.py` — `OverlayStore` (Lakebase)
- `src/back/objects/actions/audit.py` — `AuditLog` + `EffectOutbox`
- `src/back/objects/actions/effects.py` — `Effect` ABC + `EffectRunner` + `noop_log`
- `src/back/objects/actions/types/flag_customer_high_risk.py` — first Action Type
- `src/back/core/graphql/` — add `Mutation` type + `flagCustomerHighRisk`; `Customer.riskFlag` resolver
- `src/agents/tools/actions.py` — agent tool adapter (definition + handler)
- Lakebase DDL — `action_log`, `ontology_overlay`, `action_effects_outbox`
  (in `ontology_registry`), applied via the registry store's init/DDL path
