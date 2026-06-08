# Kinetic Action Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first production-shaped Action primitive (`flag_customer_high_risk`) — the "kinetic" half of the ontology — with a typed `ActionService`, an authoritative Lakebase overlay, immutable audit, a pluggable Effect outbox (no live connector), and GraphQL Mutation + agent-tool entry surfaces.

**Architecture:** A new `back/objects/actions/` subpackage. `ActionService` is the only mutation path: resolve a code-registered `ActionType` → validate → advance lifecycle → write overlay + audit + outbox in one Lakebase transaction → effects drain post-commit. The Lakebase connection pool is **reused** from the registry store (injected `connect` callable); kinetic tables are created idempotently. Read-back is an overlay-backed `Customer.riskFlag` GraphQL field. Action Types are code-registered now, but the registry is a **seam** toward ontology-defined Action Types (north-star B).

**Tech Stack:** Python 3.12, Pydantic v2, psycopg3 (Lakebase Postgres, `autocommit=True` pool → explicit `conn.transaction()`), strawberry-graphql, pytest. Spec: `docs/superpowers/specs/2026-06-08-kinetic-action-layer-design.md`.

**Conventions:** New subpackage under `back/objects/` — follow `.cursor/07-project-conventions.mdc` (the `adding-subpackage` skill). After code changes, run the `changelog` skill and the test suite (`.cursorrules`).

**Test seam for Lakebase:** Unit tests use a `FakeConn`/`FakeCursor` that records executed SQL and returns canned rows (no live DB). A `connect` callable returning a context manager yielding the connection is injected everywhere — tests pass a fake; production passes the registry pool's `connection`.

---

### Task 1: Core types — enums, `OverlayEdit`, `ActionContext`

**Files:**
- Create: `src/back/objects/actions/__init__.py`
- Create: `src/back/objects/actions/base.py`
- Test: `tests/units/actions/test_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_base.py
from back.objects.actions.base import (
    ActionStatus, ApprovalPolicy, OverlayEdit, ActionContext,
)

def test_enums_have_expected_members():
    assert {s.value for s in ActionStatus} == {
        "PROPOSED", "APPROVED", "APPLIED", "REJECTED", "REVERTED", "FAILED",
    }
    assert {p.value for p in ApprovalPolicy} == {"AUTO", "REQUIRES_APPROVAL"}

def test_overlay_edit_is_immutable_value():
    e = OverlayEdit(object_type="Customer", object_id="C1",
                    property="riskFlag", value={"severity": "high"})
    assert e.object_type == "Customer"
    assert e.value["severity"] == "high"

def test_action_context_carries_actor_and_connect():
    ctx = ActionContext(domain="customers", actor="jerry@moneypool.mx",
                        actor_kind="user", connect=lambda: None)
    assert ctx.actor_kind == "user"
    assert callable(ctx.connect)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'back.objects.actions'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/__init__.py
"""Kinetic Action layer — typed, validated, audited, reversible Actions
that mutate ontology state through a single ActionService seam.

Action Types are code-registered today (see ``registry``); the registry is
designed to later load definitions from ontology metadata (north-star B)
without changing ActionService, the overlay, the audit log, or effects.
"""
```

```python
# src/back/objects/actions/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"
    FAILED = "FAILED"


class ApprovalPolicy(str, Enum):
    AUTO = "AUTO"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


@dataclass(frozen=True)
class OverlayEdit:
    """One property edit an Action applies to an object."""
    object_type: str
    object_id: str
    property: str
    value: Dict[str, Any]


@dataclass
class ActionContext:
    """Runtime context for an Action invocation.

    ``connect`` returns a context manager yielding a live Lakebase
    connection (the registry pool's ``connection`` in production, a fake
    in tests).
    """
    domain: str
    actor: str
    actor_kind: str  # 'user' | 'agent'
    connect: Callable[[], Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_base.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/__init__.py src/back/objects/actions/base.py tests/units/actions/test_base.py
git commit -m "feat(actions): core types — status/policy enums, OverlayEdit, ActionContext"
```

---

### Task 2: `ActionType` ABC + registry (the north-star seam)

**Files:**
- Create: `src/back/objects/actions/action_type.py`
- Create: `src/back/objects/actions/registry.py`
- Test: `tests/units/actions/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_registry.py
import pytest
from pydantic import BaseModel
from back.objects.actions.base import ApprovalPolicy, OverlayEdit, ActionContext
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry


class _Params(BaseModel):
    value: str

class _Demo(ActionType):
    id = "demo_action"
    object_type = "Customer"
    approval_policy = ApprovalPolicy.AUTO
    params_model = _Params
    def validate(self, ctx, p):  # returns list[str] of errors
        return [] if p.value else ["value required"]
    def apply(self, ctx, p):
        return [OverlayEdit("Customer", "C1", "demo", {"v": p.value})]
    def effects(self, p):
        return []

def test_register_and_resolve():
    reg = ActionRegistry()
    reg.register(_Demo())
    assert reg.get("demo_action").object_type == "Customer"

def test_unknown_type_raises():
    reg = ActionRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")

def test_duplicate_registration_raises():
    reg = ActionRegistry()
    reg.register(_Demo())
    with pytest.raises(ValueError):
        reg.register(_Demo())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.action_type`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/action_type.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Tuple, Type
from pydantic import BaseModel
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


class ActionType(ABC):
    """Declarative definition of one kind of Action.

    Subclasses set the class attributes and implement validate/apply/effects.
    The registry stores instances; future work can synthesize ActionType
    instances from ontology metadata (north-star B) with no consumer changes.
    """
    id: str
    object_type: str
    approval_policy: ApprovalPolicy
    params_model: Type[BaseModel]

    @abstractmethod
    def validate(self, ctx: ActionContext, params: BaseModel) -> List[str]:
        """Return a list of human-readable precondition errors ([] = ok)."""

    @abstractmethod
    def apply(self, ctx: ActionContext, params: BaseModel) -> List[OverlayEdit]:
        """Return the overlay edits this action applies (no I/O here)."""

    @abstractmethod
    def effects(self, params: BaseModel) -> List[Tuple[str, dict]]:
        """Return (effect_name, payload) pairs to enqueue post-commit."""
```

```python
# src/back/objects/actions/registry.py
from __future__ import annotations
from typing import Dict
from back.objects.actions.action_type import ActionType


class ActionRegistry:
    """In-memory registry of ActionType instances, keyed by id."""

    def __init__(self) -> None:
        self._types: Dict[str, ActionType] = {}

    def register(self, action_type: ActionType) -> None:
        if action_type.id in self._types:
            raise ValueError(f"Action type already registered: {action_type.id}")
        self._types[action_type.id] = action_type

    def get(self, type_id: str) -> ActionType:
        if type_id not in self._types:
            raise KeyError(f"Unknown action type: {type_id}")
        return self._types[type_id]

    def ids(self) -> list[str]:
        return sorted(self._types)


# Process-wide default registry. Action type modules register here on import.
default_registry = ActionRegistry()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/action_type.py src/back/objects/actions/registry.py tests/units/actions/test_registry.py
git commit -m "feat(actions): ActionType ABC + registry seam"
```

---

### Task 3: Kinetic DDL + idempotent schema applier

**Files:**
- Create: `src/back/objects/actions/schema.sql`
- Create: `src/back/objects/actions/schema.py`
- Test: `tests/units/actions/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_schema.py
from back.objects.actions.schema import ensure_schema
from tests.units.actions.fakes import FakeConn  # created in this task

def test_ensure_schema_runs_ddl_idempotently():
    conn = FakeConn()
    ensure_schema(lambda: conn.ctx())
    executed = " ".join(conn.cursor_obj.executed).lower()
    assert "create table if not exists action_log" in executed
    assert "create table if not exists ontology_overlay" in executed
    assert "create table if not exists action_effects_outbox" in executed
```

```python
# tests/units/actions/fakes.py
from contextlib import contextmanager


class FakeCursor:
    def __init__(self, rows=None):
        self.executed = []          # list of SQL strings
        self.params = []            # list of param tuples
        self._rows = rows or []
    def execute(self, sql, params=None):
        self.executed.append(sql)
        self.params.append(params)
    def fetchone(self):
        return self._rows[0] if self._rows else None
    def fetchall(self):
        return list(self._rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakeTxn:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, rows=None):
        self.cursor_obj = FakeCursor(rows)
    def cursor(self):
        return self.cursor_obj
    def transaction(self):
        return _FakeTxn()
    @contextmanager
    def ctx(self):
        yield self
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.schema`

- [ ] **Step 3: Write minimal implementation**

```sql
-- src/back/objects/actions/schema.sql
-- Kinetic Action layer tables. Idempotent. Applied into the active
-- Lakebase registry schema (search_path is set by the pooled connection).

CREATE TABLE IF NOT EXISTS action_log (
    action_id        uuid PRIMARY KEY,
    action_type      text NOT NULL,
    domain           text NOT NULL,
    object_type      text NOT NULL,
    object_id        text NOT NULL,
    params           jsonb NOT NULL,
    actor            text NOT NULL,
    actor_kind       text NOT NULL,
    status           text NOT NULL,
    before           jsonb,
    after            jsonb,
    approved_by      text,
    parent_action_id uuid,
    created_at       timestamptz NOT NULL DEFAULT now(),
    applied_at       timestamptz
);

CREATE TABLE IF NOT EXISTS ontology_overlay (
    domain      text NOT NULL,
    object_type text NOT NULL,
    object_id   text NOT NULL,
    property    text NOT NULL,
    value       jsonb NOT NULL,
    action_id   uuid NOT NULL,
    status      text NOT NULL,                 -- ACTIVE | SUPERSEDED | REVERTED
    valid_from  timestamptz NOT NULL DEFAULT now(),
    valid_to    timestamptz,
    PRIMARY KEY (domain, object_type, object_id, property, valid_from)
);

CREATE INDEX IF NOT EXISTS ontology_overlay_current_idx
    ON ontology_overlay (domain, object_type, object_id, property)
    WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS action_effects_outbox (
    effect_id    uuid PRIMARY KEY,
    action_id    uuid NOT NULL,
    effect_name  text NOT NULL,
    payload      jsonb NOT NULL,
    status       text NOT NULL,                -- PENDING|RUNNING|DONE|FAILED
    attempts     int NOT NULL DEFAULT 0,
    last_error   text,
    next_attempt_at timestamptz NOT NULL DEFAULT now()
);
```

```python
# src/back/objects/actions/schema.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

_DDL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def ensure_schema(connect: Callable[[], Any]) -> None:
    """Create the kinetic tables if absent. Idempotent.

    ``connect`` returns a context manager yielding a Lakebase connection
    whose search_path is already the active registry schema.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(_DDL)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_schema.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/schema.sql src/back/objects/actions/schema.py tests/units/actions/test_schema.py tests/units/actions/fakes.py
git commit -m "feat(actions): idempotent Lakebase DDL + schema applier"
```

---

### Task 4: `OverlayStore` — write edits, current value, supersede, revert

**Files:**
- Create: `src/back/objects/actions/overlay_store.py`
- Test: `tests/units/actions/test_overlay_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_overlay_store.py
import uuid
from back.objects.actions.base import OverlayEdit
from back.objects.actions.overlay_store import OverlayStore
from tests.units.actions.fakes import FakeConn, FakeCursor

def test_apply_edits_supersedes_then_inserts():
    cur = FakeCursor()
    store = OverlayStore(domain="customers")
    aid = uuid.uuid4()
    store.apply_edits(cur, aid, [OverlayEdit("Customer", "C1", "riskFlag", {"severity": "high"})])
    sql = " ".join(cur.executed).lower()
    assert "update ontology_overlay" in sql and "superseded" in sql
    assert "insert into ontology_overlay" in sql

def test_current_value_returns_active_row_value():
    cur = FakeCursor(rows=[({"severity": "high"},)])
    store = OverlayStore(domain="customers")
    val = store.current_value(cur, "Customer", "C1", "riskFlag")
    assert val == {"severity": "high"}
    assert "status = 'active'" in cur.executed[-1].lower()

def test_current_value_none_when_no_row():
    cur = FakeCursor(rows=[])
    store = OverlayStore(domain="customers")
    assert store.current_value(cur, "Customer", "C1", "riskFlag") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_overlay_store.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.overlay_store`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/overlay_store.py
from __future__ import annotations
import json
import uuid
from typing import Any, List, Optional
from back.objects.actions.base import OverlayEdit


class OverlayStore:
    """Authoritative property-edit overlay (Lakebase).

    All methods take an open cursor so they compose inside the
    ActionService transaction. No connection management here.
    """

    def __init__(self, domain: str) -> None:
        self.domain = domain

    def apply_edits(self, cur: Any, action_id: uuid.UUID, edits: List[OverlayEdit]) -> None:
        for e in edits:
            cur.execute(
                "UPDATE ontology_overlay SET status='SUPERSEDED', valid_to=now() "
                "WHERE domain=%s AND object_type=%s AND object_id=%s "
                "AND property=%s AND status='ACTIVE'",
                (self.domain, e.object_type, e.object_id, e.property),
            )
            cur.execute(
                "INSERT INTO ontology_overlay "
                "(domain, object_type, object_id, property, value, action_id, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')",
                (self.domain, e.object_type, e.object_id, e.property,
                 json.dumps(e.value), str(action_id)),
            )

    def current_value(self, cur: Any, object_type: str, object_id: str,
                      prop: str) -> Optional[dict]:
        cur.execute(
            "SELECT value FROM ontology_overlay "
            "WHERE domain=%s AND object_type=%s AND object_id=%s "
            "AND property=%s AND status='ACTIVE' "
            "ORDER BY valid_from DESC LIMIT 1",
            (self.domain, object_type, object_id, prop),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def revert_action(self, cur: Any, action_id: uuid.UUID) -> None:
        cur.execute(
            "UPDATE ontology_overlay SET status='REVERTED', valid_to=now() "
            "WHERE action_id=%s AND status='ACTIVE'",
            (str(action_id),),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_overlay_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/overlay_store.py tests/units/actions/test_overlay_store.py
git commit -m "feat(actions): OverlayStore — edits, supersede, current value, revert"
```

---

### Task 5: `AuditLog` + `EffectOutbox`

**Files:**
- Create: `src/back/objects/actions/audit.py`
- Test: `tests/units/actions/test_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_audit.py
import uuid
from back.objects.actions.audit import AuditLog, EffectOutbox
from tests.units.actions.fakes import FakeCursor

def test_insert_proposed_writes_row_and_returns_uuid():
    cur = FakeCursor()
    aid = AuditLog().insert_proposed(
        cur, action_type="flag_customer_high_risk", domain="customers",
        object_type="Customer", object_id="C1", params={"severity": "high"},
        actor="jerry@moneypool.mx", actor_kind="user")
    assert isinstance(aid, uuid.UUID)
    assert "insert into action_log" in cur.executed[0].lower()
    assert "proposed" in " ".join(str(p) for p in cur.params[0]).lower()

def test_mark_updates_status():
    cur = FakeCursor()
    aid = uuid.uuid4()
    AuditLog().mark(cur, aid, "APPLIED", after={"riskFlag": {"severity": "high"}})
    assert "update action_log set status" in cur.executed[0].lower()

def test_enqueue_effect_inserts_pending():
    cur = FakeCursor()
    EffectOutbox().enqueue(cur, uuid.uuid4(), "noop_log", {"k": "v"})
    sql = cur.executed[0].lower()
    assert "insert into action_effects_outbox" in sql
    assert "pending" in " ".join(str(p) for p in cur.params[0]).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.audit`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/audit.py
from __future__ import annotations
import json
import uuid
from typing import Any, Optional


class AuditLog:
    """Immutable-ish action_log writer (status transitions are updates)."""

    def insert_proposed(self, cur: Any, *, action_type: str, domain: str,
                        object_type: str, object_id: str, params: dict,
                        actor: str, actor_kind: str,
                        parent_action_id: Optional[uuid.UUID] = None) -> uuid.UUID:
        aid = uuid.uuid4()
        cur.execute(
            "INSERT INTO action_log (action_id, action_type, domain, object_type, "
            "object_id, params, actor, actor_kind, status, parent_action_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PROPOSED',%s)",
            (str(aid), action_type, domain, object_type, object_id,
             json.dumps(params), actor, actor_kind,
             str(parent_action_id) if parent_action_id else None),
        )
        return aid

    def mark(self, cur: Any, action_id: uuid.UUID, status: str, *,
             approved_by: Optional[str] = None, before: Optional[dict] = None,
             after: Optional[dict] = None) -> None:
        cur.execute(
            "UPDATE action_log SET status=%s, approved_by=COALESCE(%s, approved_by), "
            "before=COALESCE(%s, before), after=COALESCE(%s, after), "
            "applied_at=CASE WHEN %s='APPLIED' THEN now() ELSE applied_at END "
            "WHERE action_id=%s",
            (status, approved_by,
             json.dumps(before) if before is not None else None,
             json.dumps(after) if after is not None else None,
             status, str(action_id)),
        )

    def get(self, cur: Any, action_id: uuid.UUID) -> Optional[dict]:
        cur.execute(
            "SELECT action_type, domain, object_type, object_id, params, status "
            "FROM action_log WHERE action_id=%s", (str(action_id),))
        row = cur.fetchone()
        if not row:
            return None
        return {"action_type": row[0], "domain": row[1], "object_type": row[2],
                "object_id": row[3], "params": row[4], "status": row[5]}


class EffectOutbox:
    """Pending external effects (seam; no live connector in this slice)."""

    def enqueue(self, cur: Any, action_id: uuid.UUID, name: str, payload: dict) -> None:
        cur.execute(
            "INSERT INTO action_effects_outbox "
            "(effect_id, action_id, effect_name, payload, status) "
            "VALUES (%s,%s,%s,%s,'PENDING')",
            (str(uuid.uuid4()), str(action_id), name, json.dumps(payload)),
        )

    def claim_pending(self, cur: Any, limit: int = 20) -> list[dict]:
        cur.execute(
            "SELECT effect_id, action_id, effect_name, payload FROM action_effects_outbox "
            "WHERE status='PENDING' AND next_attempt_at <= now() "
            "ORDER BY next_attempt_at LIMIT %s", (limit,))
        return [{"effect_id": r[0], "action_id": r[1], "effect_name": r[2],
                 "payload": r[3]} for r in cur.fetchall()]

    def mark(self, cur: Any, effect_id: Any, status: str, error: Optional[str] = None) -> None:
        cur.execute(
            "UPDATE action_effects_outbox SET status=%s, attempts=attempts+1, "
            "last_error=%s WHERE effect_id=%s",
            (status, error, str(effect_id)),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_audit.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/audit.py tests/units/actions/test_audit.py
git commit -m "feat(actions): AuditLog + EffectOutbox"
```

---

### Task 6: `Effect` ABC + `EffectRunner` + `noop_log` effect

**Files:**
- Create: `src/back/objects/actions/effects.py`
- Test: `tests/units/actions/test_effects.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_effects.py
import uuid
from back.objects.actions.effects import Effect, EffectRunner, NoopLogEffect
from tests.units.actions.fakes import FakeConn, FakeCursor

def test_noop_log_effect_runs_ok():
    NoopLogEffect().run({"action_id": str(uuid.uuid4())})  # must not raise

def test_runner_marks_done_on_success():
    cur = FakeCursor(rows=[("eff-1", "act-1", "noop_log", {"x": 1})])
    runner = EffectRunner(connect=lambda: FakeConn(rows=cur._rows).ctx(),
                          effects={"noop_log": NoopLogEffect()})
    # use a conn whose cursor is our recording cur
    conn = FakeConn(); conn.cursor_obj = cur
    runner._connect = lambda: conn.ctx()
    runner.run_pending()
    sql = " ".join(cur.executed).lower()
    assert "status='done'" in sql.replace(" ", "") or "done" in sql

def test_runner_marks_failed_when_effect_raises():
    class Boom(Effect):
        name = "boom"
        def run(self, payload): raise RuntimeError("nope")
    cur = FakeCursor(rows=[("eff-2", "act-2", "boom", {})])
    conn = FakeConn(); conn.cursor_obj = cur
    runner = EffectRunner(connect=lambda: conn.ctx(), effects={"boom": Boom()})
    runner.run_pending()
    assert "failed" in " ".join(cur.executed).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_effects.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.effects`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/effects.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict
from back.core.logging import get_logger
from back.objects.actions.audit import EffectOutbox

logger = get_logger(__name__)


class Effect(ABC):
    """A pluggable outbound effect (Delta sync, SAP connector, notify…).

    This slice ships only NoopLogEffect; real connectors register later
    with no change to ActionService or the outbox."""
    name: str

    @abstractmethod
    def run(self, payload: Dict[str, Any]) -> None:
        ...


class NoopLogEffect(Effect):
    name = "noop_log"
    def run(self, payload: Dict[str, Any]) -> None:
        logger.info("noop_log effect fired: %s", payload)


class EffectRunner:
    """Drains the outbox and runs effects. Failures are isolated to the
    outbox row and never roll back the committed Action."""

    def __init__(self, connect: Callable[[], Any], effects: Dict[str, Effect]):
        self._connect = connect
        self._effects = effects
        self._outbox = EffectOutbox()

    def run_pending(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            pending = self._outbox.claim_pending(cur)
            for row in pending:
                effect = self._effects.get(row["effect_name"])
                try:
                    if effect is None:
                        raise KeyError(f"no effect registered: {row['effect_name']}")
                    effect.run(row["payload"])
                    self._outbox.mark(cur, row["effect_id"], "DONE")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("effect %s failed: %s", row["effect_name"], exc)
                    self._outbox.mark(cur, row["effect_id"], "FAILED", error=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_effects.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/effects.py tests/units/actions/test_effects.py
git commit -m "feat(actions): Effect ABC + EffectRunner + noop_log"
```

---

### Task 7: `ActionService` — propose / approve / apply / revert

**Files:**
- Create: `src/back/objects/actions/service.py`
- Test: `tests/units/actions/test_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_service.py
import uuid
import pytest
from pydantic import BaseModel
from back.objects.actions.base import ApprovalPolicy, OverlayEdit, ActionContext
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry
from back.objects.actions.service import ActionService, ActionError
from tests.units.actions.fakes import FakeConn

class _P(BaseModel):
    severity: str
    reason: str = ""

class _AutoFlag(ActionType):
    id = "auto_flag"; object_type = "Customer"
    approval_policy = ApprovalPolicy.AUTO; params_model = _P
    def validate(self, ctx, p): return [] if p.severity else ["severity required"]
    def apply(self, ctx, p): return [OverlayEdit("Customer", "C1", "riskFlag", {"severity": p.severity})]
    def effects(self, p): return [("noop_log", {"severity": p.severity})]

class _ApprovalFlag(_AutoFlag):
    id = "approval_flag"; approval_policy = ApprovalPolicy.REQUIRES_APPROVAL

def _svc(conn):
    reg = ActionRegistry(); reg.register(_AutoFlag()); reg.register(_ApprovalFlag())
    return ActionService(registry=reg, connect=lambda: conn.ctx())

def _ctx(): 
    return ActionContext(domain="customers", actor="a@b.c", actor_kind="user", connect=lambda: None)

def test_validation_failure_returns_failed_no_overlay():
    conn = FakeConn()
    res = _svc(conn).propose("auto_flag", "C1", {"severity": ""}, _ctx())
    assert res.status == "FAILED" and res.errors
    assert "insert into ontology_overlay" not in " ".join(conn.cursor_obj.executed).lower()

def test_auto_policy_applies_immediately():
    conn = FakeConn()
    res = _svc(conn).propose("auto_flag", "C1", {"severity": "high"}, _ctx())
    assert res.status == "APPLIED"
    sql = " ".join(conn.cursor_obj.executed).lower()
    assert "insert into ontology_overlay" in sql
    assert "insert into action_effects_outbox" in sql

def test_approval_policy_stops_at_proposed():
    conn = FakeConn()
    res = _svc(conn).propose("approval_flag", "C1", {"severity": "high"}, _ctx())
    assert res.status == "PROPOSED"
    assert "insert into ontology_overlay" not in " ".join(conn.cursor_obj.executed).lower()

def test_unknown_type_raises():
    with pytest.raises(ActionError):
        _svc(FakeConn()).propose("nope", "C1", {"severity": "x"}, _ctx())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.service`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/service.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from pydantic import ValidationError as PydanticValidationError
from back.core.logging import get_logger
from back.objects.actions.base import ActionContext, ApprovalPolicy
from back.objects.actions.registry import ActionRegistry
from back.objects.actions.overlay_store import OverlayStore
from back.objects.actions.audit import AuditLog, EffectOutbox

logger = get_logger(__name__)


class ActionError(Exception):
    """Unrecoverable Action invocation error (unknown type, bad state)."""


@dataclass
class ActionResult:
    action_id: Optional[uuid.UUID]
    status: str
    errors: List[str] = field(default_factory=list)


class ActionService:
    """The single mutation path for the ontology overlay."""

    def __init__(self, registry: ActionRegistry, connect: Callable[[], Any]):
        self._registry = registry
        self._connect = connect
        self._audit = AuditLog()
        self._outbox = EffectOutbox()

    def propose(self, type_id: str, object_id: str, raw_params: dict,
                ctx: ActionContext) -> ActionResult:
        try:
            atype = self._registry.get(type_id)
        except KeyError as exc:
            raise ActionError(str(exc)) from exc

        try:
            params = atype.params_model(**raw_params)
        except PydanticValidationError as exc:
            return ActionResult(None, "FAILED", [str(exc)])

        errors = atype.validate(ctx, params)
        if errors:
            return ActionResult(None, "FAILED", errors)

        with self._connect() as conn:
            with conn.transaction():
                cur = conn.cursor()
                aid = self._audit.insert_proposed(
                    cur, action_type=type_id, domain=ctx.domain,
                    object_type=atype.object_type, object_id=object_id,
                    params=params.model_dump(), actor=ctx.actor,
                    actor_kind=ctx.actor_kind)
                if atype.approval_policy == ApprovalPolicy.AUTO:
                    self._apply(cur, atype, aid, object_id, params, ctx)
                    return ActionResult(aid, "APPLIED")
        return ActionResult(aid, "PROPOSED")

    def approve(self, action_id: uuid.UUID, approver: str, ctx: ActionContext) -> ActionResult:
        with self._connect() as conn:
            with conn.transaction():
                cur = conn.cursor()
                rec = self._audit.get(cur, action_id)
                if rec is None:
                    raise ActionError(f"unknown action: {action_id}")
                if rec["status"] != "PROPOSED":
                    raise ActionError(f"cannot approve action in status {rec['status']}")
                atype = self._registry.get(rec["action_type"])
                params = atype.params_model(**rec["params"])
                self._audit.mark(cur, action_id, "APPROVED", approved_by=approver)
                self._apply(cur, atype, action_id, rec["object_id"], params, ctx)
        return ActionResult(action_id, "APPLIED")

    def reject(self, action_id: uuid.UUID, approver: str) -> ActionResult:
        with self._connect() as conn, conn.transaction():
            cur = conn.cursor()
            self._audit.mark(cur, action_id, "REJECTED", approved_by=approver)
        return ActionResult(action_id, "REJECTED")

    def revert(self, action_id: uuid.UUID, ctx: ActionContext) -> ActionResult:
        overlay = OverlayStore(domain=ctx.domain)
        with self._connect() as conn, conn.transaction():
            cur = conn.cursor()
            rec = self._audit.get(cur, action_id)
            if rec is None or rec["status"] != "APPLIED":
                raise ActionError("only APPLIED actions can be reverted")
            overlay.revert_action(cur, action_id)
            self._audit.mark(cur, action_id, "REVERTED")
            child = self._audit.insert_proposed(
                cur, action_type=rec["action_type"], domain=rec["domain"],
                object_type=rec["object_type"], object_id=rec["object_id"],
                params=rec["params"], actor=ctx.actor, actor_kind=ctx.actor_kind,
                parent_action_id=action_id)
            self._audit.mark(cur, child, "REVERTED")
        return ActionResult(action_id, "REVERTED")

    def _apply(self, cur: Any, atype, action_id: uuid.UUID, object_id: str,
               params, ctx: ActionContext) -> None:
        overlay = OverlayStore(domain=ctx.domain)
        edits = atype.apply(ctx, params)
        overlay.apply_edits(cur, action_id, edits)
        after = {e.property: e.value for e in edits}
        self._audit.mark(cur, action_id, "APPLIED", after=after)
        for name, payload in atype.effects(params):
            self._outbox.enqueue(cur, action_id, name, {**payload, "action_id": str(action_id)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_service.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/service.py tests/units/actions/test_service.py
git commit -m "feat(actions): ActionService — propose/approve/reject/revert with txn apply"
```

---

### Task 8: First Action Type — `flag_customer_high_risk`

**Files:**
- Create: `src/back/objects/actions/types/__init__.py`
- Create: `src/back/objects/actions/types/flag_customer_high_risk.py`
- Test: `tests/units/actions/test_flag_customer_high_risk.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_flag_customer_high_risk.py
from back.objects.actions.base import ApprovalPolicy
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk
from back.objects.actions.base import ActionContext

def _ctx():
    return ActionContext(domain="customers", actor="a@b.c", actor_kind="agent", connect=lambda: None)

def test_metadata():
    a = FlagCustomerHighRisk()
    assert a.id == "flag_customer_high_risk"
    assert a.object_type == "Customer"
    assert a.approval_policy == ApprovalPolicy.REQUIRES_APPROVAL

def test_high_severity_requires_reason():
    a = FlagCustomerHighRisk()
    p_bad = a.params_model(severity="high", reason="")
    assert a.validate(_ctx(), p_bad)  # non-empty error list
    p_ok = a.params_model(severity="high", reason="sanctions match")
    assert a.validate(_ctx(), p_ok) == []

def test_apply_produces_riskflag_edit():
    a = FlagCustomerHighRisk()
    p = a.params_model(severity="high", reason="sanctions match")
    edits = a.apply(_ctx(), p)
    assert len(edits) == 1
    assert edits[0].property == "riskFlag"
    assert edits[0].value["severity"] == "high"

def test_effects_enqueue_noop_log():
    a = FlagCustomerHighRisk()
    p = a.params_model(severity="medium", reason="x")
    assert a.effects(p)[0][0] == "noop_log"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_flag_customer_high_risk.py -v`
Expected: FAIL — `ModuleNotFoundError: back.objects.actions.types`

- [ ] **Step 3: Write minimal implementation**

```python
# src/back/objects/actions/types/__init__.py
"""Code-registered Action Types. Importing this package registers them on
``back.objects.actions.registry.default_registry``."""
from back.objects.actions.registry import default_registry
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk

default_registry.register(FlagCustomerHighRisk())
```

```python
# src/back/objects/actions/types/flag_customer_high_risk.py
from __future__ import annotations
from typing import List, Tuple
from pydantic import BaseModel, Field
from back.objects.actions.action_type import ActionType
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


class FlagHighRiskParams(BaseModel):
    severity: str = Field(pattern="^(low|medium|high)$")
    reason: str = ""
    customer_id: str  # the object_id; carried in params for the GraphQL/tool adapters


class FlagCustomerHighRisk(ActionType):
    id = "flag_customer_high_risk"
    object_type = "Customer"
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = FlagHighRiskParams

    def validate(self, ctx: ActionContext, params: FlagHighRiskParams) -> List[str]:
        errors: List[str] = []
        if params.severity == "high" and not params.reason.strip():
            errors.append("reason is required when severity is 'high'")
        # NOTE: object-existence + SHACL post-state checks are added when the
        # overlay/graph read API lands; kept out of this slice's validate to
        # stay within scope (see spec non-goals).
        return errors

    def apply(self, ctx: ActionContext, params: FlagHighRiskParams) -> List[OverlayEdit]:
        return [OverlayEdit(
            object_type="Customer", object_id=params.customer_id,
            property="riskFlag",
            value={"severity": params.severity, "reason": params.reason},
        )]

    def effects(self, params: FlagHighRiskParams) -> List[Tuple[str, dict]]:
        return [("noop_log", {"object_id": params.customer_id,
                              "severity": params.severity})]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_flag_customer_high_risk.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/types/ tests/units/actions/test_flag_customer_high_risk.py
git commit -m "feat(actions): flag_customer_high_risk action type + auto-registration"
```

---

### Task 9: Agent tool adapter

**Files:**
- Create: `src/agents/tools/actions.py`
- Test: `tests/units/actions/test_agent_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_agent_tool.py
import json
from agents.tools.actions import ACTION_TOOL_DEFINITIONS, ACTION_TOOL_HANDLERS

def test_tool_definition_exposes_flag_high_risk():
    names = [d["function"]["name"] for d in ACTION_TOOL_DEFINITIONS]
    assert "propose_flag_customer_high_risk" in names

def test_handler_returns_json_with_action_id(monkeypatch):
    from back.objects.actions import service as svc_mod
    class _Res:
        action_id = "11111111-1111-1111-1111-111111111111"; status = "PROPOSED"; errors = []
    class _Svc:
        def propose(self, *a, **k): return _Res()
    monkeypatch.setattr("agents.tools.actions._build_service", lambda ctx: _Svc())
    from agents.tools.context import ToolContext
    ctx = ToolContext(host="h", token="t", domain_name="customers", actor="agent:dtwin")
    out = ACTION_TOOL_HANDLERS["propose_flag_customer_high_risk"](
        ctx, customer_id="C1", severity="high", reason="sanctions")
    payload = json.loads(out)
    assert payload["status"] == "PROPOSED" and payload["action_id"]
```

> NOTE: `ToolContext` may need an `actor` field if absent. If the test fails on
> an unexpected `actor` kwarg, add `actor: str = ""` to `ToolContext` in
> `src/agents/tools/context.py` (one line) as part of Step 3 and commit it with this task.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_agent_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: agents.tools.actions`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agents/tools/actions.py
"""Agent tool adapter — lets the agent loop PROPOSE Actions (kinetic loop).
Thin marshalling over back.objects.actions.ActionService."""
import json
from typing import Callable, Dict, List
from back.core.logging import get_logger
from agents.tools.context import ToolContext
from back.objects.actions.base import ActionContext
from back.objects.actions.registry import default_registry
import back.objects.actions.types  # noqa: F401  (registers action types)
from back.objects.actions.service import ActionService, ActionError

logger = get_logger(__name__)


def _build_service(ctx: ToolContext) -> ActionService:
    # connect is supplied by the registry Lakebase pool in production wiring;
    # see Task 11 for how the request layer injects it onto the context metadata.
    connect = ctx.metadata.get("lakebase_connect")
    return ActionService(registry=default_registry, connect=connect)


def tool_propose_flag_customer_high_risk(ctx: ToolContext, *, customer_id: str = "",
                                         severity: str = "", reason: str = "",
                                         **_kw) -> str:
    actor = getattr(ctx, "actor", "") or "agent"
    try:
        svc = _build_service(ctx)
        action_ctx = ActionContext(
            domain=ctx.domain_name or "customers", actor=actor, actor_kind="agent",
            connect=ctx.metadata.get("lakebase_connect"))
        res = svc.propose("flag_customer_high_risk", customer_id,
                          {"customer_id": customer_id, "severity": severity, "reason": reason},
                          action_ctx)
        return json.dumps({"success": not res.errors, "status": res.status,
                           "action_id": str(res.action_id) if res.action_id else None,
                           "errors": res.errors})
    except ActionError as exc:
        return json.dumps({"success": False, "error": str(exc)})


ACTION_TOOL_DEFINITIONS: List[dict] = [{
    "type": "function",
    "function": {
        "name": "propose_flag_customer_high_risk",
        "description": ("Propose flagging a customer as high-risk in the ontology. "
                        "Requires human approval before it is applied. Returns the action_id."),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer object id."},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                "reason": {"type": "string", "description": "Required when severity is 'high'."},
            },
            "required": ["customer_id", "severity"],
        },
    },
}]

ACTION_TOOL_HANDLERS: Dict[str, Callable] = {
    "propose_flag_customer_high_risk": tool_propose_flag_customer_high_risk,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_agent_tool.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/agents/tools/actions.py tests/units/actions/test_agent_tool.py src/agents/tools/context.py
git commit -m "feat(actions): agent tool adapter to propose actions"
```

---

### Task 10: GraphQL Mutation + `Customer.riskFlag` read-back

**Files:**
- Modify: `src/back/core/graphql/GraphQLSchemaBuilder.py` (add `_build_mutation`, pass `mutation=` to `strawberry.Schema`, add `riskFlag` field)
- Modify: `src/back/core/graphql/ResolverFactory.py` (add `make_overlay_field_resolver` + `make_action_mutation_resolver`)
- Test: `tests/units/actions/test_graphql_mutation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/units/actions/test_graphql_mutation.py
import strawberry
from back.core.graphql.ResolverFactory import ResolverFactory

def test_overlay_field_resolver_reads_current_value():
    class _Store:
        def current_value(self, cur, ot, oid, prop): return {"severity": "high"}
    class _Conn:
        def cursor(self): 
            class C: 
                def __enter__(s): return s
                def __exit__(s,*a): return False
            return C()
        def __enter__(self): return self
        def __exit__(self,*a): return False
    resolver = ResolverFactory.make_overlay_field_resolver(
        store=_Store(), connect=lambda: _Conn(), object_type="Customer", prop="riskFlag")
    # resolver(self) where self carries the object id
    class Obj: id = "C1"
    assert resolver(Obj())["severity"] == "high"

def test_mutation_resolver_calls_service():
    calls = {}
    class _Svc:
        def propose(self, type_id, object_id, params, ctx):
            calls.update(type_id=type_id, object_id=object_id, params=params)
            class R: action_id="aid"; status="PROPOSED"; errors=[]
            return R()
    resolver = ResolverFactory.make_action_mutation_resolver(
        service_factory=lambda info: _Svc(),
        type_id="flag_customer_high_risk", ctx_factory=lambda info, oid: None)
    out = resolver(info=None, customer_id="C1", severity="high", reason="r")
    assert calls["type_id"] == "flag_customer_high_risk"
    assert out.status == "PROPOSED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/units/actions/test_graphql_mutation.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'make_overlay_field_resolver'`

- [ ] **Step 3: Write minimal implementation**

Add to `ResolverFactory` (follow the existing `make_list_resolver` style — these are static methods returning resolver callables):

```python
# append inside class ResolverFactory in src/back/core/graphql/ResolverFactory.py
    @staticmethod
    def make_overlay_field_resolver(store, connect, object_type, prop):
        """Resolver for an overlay-backed scalar field on an object type."""
        def resolver(root) -> "Optional[dict]":  # root carries .id
            object_id = getattr(root, "id", None)
            if object_id is None:
                return None
            with connect() as conn, conn.cursor() as cur:
                return store.current_value(cur, object_type, str(object_id), prop)
        return resolver

    @staticmethod
    def make_action_mutation_resolver(service_factory, type_id, ctx_factory):
        """Resolver for a strawberry Mutation field that proposes an action."""
        import strawberry  # local import to mirror module usage
        def resolver(info, customer_id: str, severity: str, reason: str = ""):
            svc = service_factory(info)
            action_ctx = ctx_factory(info, customer_id)
            res = svc.propose(type_id, customer_id,
                              {"customer_id": customer_id, "severity": severity, "reason": reason},
                              action_ctx)
            return ActionMutationResult(
                action_id=str(res.action_id) if res.action_id else None,
                status=res.status, errors=list(res.errors))
        return resolver
```

Add the result type near the top of `ResolverFactory.py` (after imports):

```python
import strawberry
from typing import List, Optional

@strawberry.type
class ActionMutationResult:
    action_id: Optional[str]
    status: str
    errors: List[str]
```

In `GraphQLSchemaBuilder.py`, add a `_build_mutation` mirroring `_build_query`, and pass it to the schema. Modify the final `return strawberry.Schema(query=Query)` in `_build_query` so the builder constructs both (do this where the schema is assembled — keep `_build_query` returning the `Query` type, and assemble the `Schema` in the caller, OR add the mutation alongside):

```python
# in GraphQLSchemaBuilder, replace the schema assembly so it includes a Mutation:
    @staticmethod
    def _build_mutation(service_factory, ctx_factory):
        import strawberry
        from strawberry.tools import create_type
        from back.core.graphql.ResolverFactory import ResolverFactory
        field = strawberry.field(
            name="flagCustomerHighRisk",
            resolver=ResolverFactory.make_action_mutation_resolver(
                service_factory=service_factory,
                type_id="flag_customer_high_risk",
                ctx_factory=ctx_factory),
            description="Propose flagging a customer high-risk (requires approval).")
        return create_type("Mutation", [field])
```

> Wiring of `service_factory`/`ctx_factory` (which build an `ActionService` and
> `ActionContext` from the request, injecting the Lakebase `connect`) is done in
> Task 11 where `build_for_domain` is called. For this task, `_build_query`'s
> `strawberry.Schema(query=Query)` becomes
> `strawberry.Schema(query=Query, mutation=GraphQLSchemaBuilder._build_mutation(service_factory, ctx_factory))`
> with the factories threaded through `build_for_domain`'s signature
> (add params `service_factory=None, ctx_factory=None`; only attach the mutation
> when both are provided, so existing query-only callers keep working).
> Add the `riskFlag` field to the Customer gql type in `_apply_strawberry_types`
> via `ResolverFactory.make_overlay_field_resolver`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/units/actions/test_graphql_mutation.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/back/core/graphql/ResolverFactory.py src/back/core/graphql/GraphQLSchemaBuilder.py tests/units/actions/test_graphql_mutation.py
git commit -m "feat(actions): GraphQL mutation + overlay-backed riskFlag resolver"
```

---

### Task 11: Wire it together — schema init, request wiring, integration test

**Files:**
- Modify: `src/back/objects/actions/__init__.py` (export a `build_action_service(connect)` helper that calls `ensure_schema` once)
- Modify: the GraphQL route/`build_for_domain` caller (the FastAPI graphql route, e.g. `src/back/fastapi/graphql_routes.py`) to pass `service_factory`/`ctx_factory` that inject the registry Lakebase `connection` and the request user
- Test: `tests/integration/actions/test_action_loop_lakebase.py` (env-gated)

- [ ] **Step 1: Write the failing test (env-gated integration)**

```python
# tests/integration/actions/test_action_loop_lakebase.py
import os, uuid, pytest
pytestmark = pytest.mark.skipif(
    not os.environ.get("LAKEBASE_TEST_CONNECT"),
    reason="requires live Lakebase (set LAKEBASE_TEST_CONNECT=1 + app env)")

def test_propose_approve_applies_and_reads_back():
    from back.objects.actions import build_action_service
    from back.objects.actions.base import ActionContext
    from back.objects.actions.overlay_store import OverlayStore
    from back.objects.session.lakebase_test_helpers import test_connect  # provides connect()
    svc = build_action_service(test_connect)
    cid = f"itest-{uuid.uuid4().hex[:8]}"
    ctx = ActionContext(domain="customers", actor="itest", actor_kind="user", connect=test_connect)
    r = svc.propose("flag_customer_high_risk", cid,
                    {"customer_id": cid, "severity": "high", "reason": "sanctions"}, ctx)
    assert r.status == "PROPOSED"
    r2 = svc.approve(r.action_id, "approver@x", ctx)
    assert r2.status == "APPLIED"
    with test_connect() as conn, conn.cursor() as cur:
        assert OverlayStore("customers").current_value(cur, "Customer", cid, "riskFlag")["severity"] == "high"
```

> If `back.objects.session.lakebase_test_helpers.test_connect` does not exist,
> create it in Step 3 to return the registry pool's `connection` context manager
> bound to the `ontology_registry` schema, reading the same env the app uses.

- [ ] **Step 2: Run test to verify it is skipped/fails**

Run: `uv run pytest tests/integration/actions/test_action_loop_lakebase.py -v`
Expected: SKIPPED (no `LAKEBASE_TEST_CONNECT`) — confirms the gate works. (Run live in the devcontainer with app env to exercise it.)

- [ ] **Step 3: Write the wiring**

```python
# add to src/back/objects/actions/__init__.py
from typing import Any, Callable
from back.objects.actions.schema import ensure_schema
from back.objects.actions.registry import default_registry
from back.objects.actions.service import ActionService
import back.objects.actions.types  # noqa: F401  (registers action types)

_schema_ready = False

def build_action_service(connect: Callable[[], Any]) -> ActionService:
    """Return an ActionService bound to a Lakebase connection provider,
    ensuring the kinetic tables exist (once per process)."""
    global _schema_ready
    if not _schema_ready:
        ensure_schema(connect)
        _schema_ready = True
    return ActionService(registry=default_registry, connect=connect)
```

In the GraphQL route caller, build the factories from the request (pseudocode to adapt to the existing route — follow how the route currently obtains the registry store / Lakebase access):

```python
# where build_for_domain(...) is invoked in the graphql route
from back.objects.actions import build_action_service
from back.objects.actions.base import ActionContext

def _connect():
    # reuse the registry store's Lakebase pool connection context manager
    return registry_store.pool.connection()   # adapt to actual accessor

def _service_factory(info):
    return build_action_service(_connect)

def _ctx_factory(info, object_id):
    user = current_user_email(info)            # adapt to existing auth helper
    return ActionContext(domain=domain_name, actor=user, actor_kind="user", connect=_connect)

schema, meta = builder.build_for_domain(..., service_factory=_service_factory, ctx_factory=_ctx_factory)
```

- [ ] **Step 4: Run unit suite to confirm no regressions**

Run: `uv run pytest tests/units/actions/ -v`
Expected: PASS (all action unit tests green)

- [ ] **Step 5: Commit**

```bash
git add src/back/objects/actions/__init__.py tests/integration/actions/ src/back/fastapi/graphql_routes.py
git commit -m "feat(actions): wire ActionService into graphql route + schema bootstrap"
```

---

### Task 12: EffectRunner trigger, docs, changelog, full suite

**Files:**
- Modify: wherever async post-commit work is kicked (reuse `task_manager.run_background_task`) to call `EffectRunner.run_pending` after an apply, or a periodic drain
- Modify: `docs/` (Sphinx) + `README.md` — add a "Kinetic Actions" section
- Create: `changelogs/v<current>/2026-06-08.log` (via the `changelog` skill)

- [ ] **Step 1: Trigger the EffectRunner after apply**

In `ActionService._apply`, after the transaction commits, schedule a drain (out of the txn, fire-and-forget):

```python
# after `with self._connect()...` block returns in propose()/approve(), call:
from back.core.task_manager import run_background_task
from back.objects.actions.effects import EffectRunner, NoopLogEffect
def _drain(connect):
    EffectRunner(connect, {"noop_log": NoopLogEffect()}).run_pending()
run_background_task("drain-effects", "effects", _drain, self._connect)
```

(Place the `run_background_task(...)` call in `propose` (AUTO path) and `approve`
after the `with` block, so effects run only post-commit.)

- [ ] **Step 2: Run the full unit suite**

Run: `uv run pytest tests/units/actions/ -v`
Expected: PASS

- [ ] **Step 3: Update docs**

Add a "Kinetic Actions" subsection to `docs/sphinx/guides/architecture.md` and `README.md` describing: Action Types → ActionService → overlay/audit/outbox → effects, and that connectors (Delta/SAP) + ontology-defined Action Types (north-star B) are the next slices.

- [ ] **Step 4: Changelog + full test report**

Invoke the `changelog` skill: create `changelogs/v<version-from-pyproject>/2026-06-08.log` with title, context, numbered changes (file paths), modified-files list, and test result. Then:

Run: `uv run pytest -q`
Expected: full suite green (record the result in the changelog).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(actions): effect drain trigger + docs + changelog"
```

---

## Self-review notes (resolved)

- **Spec coverage:** ActionService (T7), code-registered types + seam (T2/T8), overlay authoritative (T4), audit (T5), effect outbox seam + no live connector (T5/T6), per-type approval + lifecycle (T7), GraphQL mutation + agent tool entry (T9/T10), overlay-backed `riskFlag` read-back (T10), validation reuse note + atomic txn + post-commit effects (T7/T12). Non-goals (live connectors, ontology-defined types, UI button, triple-store merge, Functions registry) intentionally excluded.
- **Type consistency:** `ActionResult{action_id,status,errors}`, `OverlayEdit{object_type,object_id,property,value}`, `ApprovalPolicy.{AUTO,REQUIRES_APPROVAL}`, `ActionStatus` values, and `OverlayStore`/`AuditLog`/`EffectOutbox` method names are used consistently across T4–T12.
- **Known adaptation points (flagged inline, not placeholders):** the exact registry-pool accessor for `connect`, the `ToolContext.actor` field, and the auth/user helper in the graphql route are environment-specific and called out with explicit fallback instructions in T9/T11. These are integration seams to confirm against the live code during execution, not unspecified behavior.
