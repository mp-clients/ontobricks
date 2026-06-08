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
