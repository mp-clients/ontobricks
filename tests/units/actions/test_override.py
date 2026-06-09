import uuid
import pytest
from pydantic import BaseModel, Field
from back.objects.actions.base import ApprovalPolicy, OverlayEdit, ActionContext
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry
from back.objects.actions.service import ActionService, ActionError
from tests.units.actions.fakes import FakeConn


class _P(BaseModel):
    transaction_id: str
    recommendation: str = Field(pattern="^(approve|reject)$")


class _Review(ActionType):
    id = "review_transaction"; object_type = "Transaction"
    overlay_fields = ["decision"]
    requires_separate_approver = True
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = _P
    def validate(self, ctx, p): return []
    def apply(self, ctx, p):
        override = (ctx.metadata or {}).get("decision_override")
        human = override or p.recommendation
        return [OverlayEdit("Transaction", p.transaction_id, "decision",
                            {"agent_recommendation": p.recommendation,
                             "human_decision": human,
                             "agreed": human == p.recommendation,
                             "decided_by": ctx.actor})]
    def effects(self, p): return [("noop_log", {"transaction_id": p.transaction_id})]


def _svc(conn):
    reg = ActionRegistry(); reg.register(_Review())
    return ActionService(registry=reg, connect=lambda: conn.ctx())


def _ctx():
    return ActionContext(domain="fraud", actor="human@x", actor_kind="user",
                         connect=lambda: None)


def _row(status, actor="agent@x"):
    return ("review_transaction", "fraud", "Transaction", "W1",
            {"transaction_id": "W1", "recommendation": "reject"}, status, actor)


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
