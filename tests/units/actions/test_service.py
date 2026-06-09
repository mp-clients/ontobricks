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
    requires_separate_approver = True

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


def _row(status, actor="proposer@x"):
    return ("approval_flag", "customers", "Customer", "C1", {"severity": "high"}, status, actor)


def test_approve_applies_proposed_action():
    conn = FakeConn(rows=[_row("PROPOSED")])
    res = _svc(conn).approve(uuid.uuid4(), "approver@x", _ctx())
    assert res.status == "APPLIED"
    sql = " ".join(conn.cursor_obj.executed).lower()
    assert "insert into ontology_overlay" in sql
    assert "insert into action_effects_outbox" in sql


def test_approve_rejects_non_proposed():
    conn = FakeConn(rows=[_row("APPLIED")])
    with pytest.raises(ActionError):
        _svc(conn).approve(uuid.uuid4(), "approver@x", _ctx())


def test_reject_marks_proposed_rejected():
    conn = FakeConn(rows=[_row("PROPOSED")])
    res = _svc(conn).reject(uuid.uuid4(), "approver@x")
    assert res.status == "REJECTED"
    assert "rejected" in " ".join(str(p) for p in conn.cursor_obj.params).lower()


def test_reject_guards_non_proposed():
    conn = FakeConn(rows=[_row("APPLIED")])
    with pytest.raises(ActionError):
        _svc(conn).reject(uuid.uuid4(), "approver@x")


def test_revert_only_applied_raises_otherwise():
    conn = FakeConn(rows=[_row("PROPOSED")])
    with pytest.raises(ActionError):
        _svc(conn).revert(uuid.uuid4(), _ctx())


def test_revert_applied_action():
    conn = FakeConn(rows=[_row("APPLIED")])
    res = _svc(conn).revert(uuid.uuid4(), _ctx())
    assert res.status == "REVERTED"
    assert "reverted" in " ".join(conn.cursor_obj.executed).lower()


def test_sod_blocks_self_approval():
    conn = FakeConn(rows=[_row("PROPOSED", actor="alice@x")])
    with pytest.raises(ActionError):
        _svc(conn).approve(uuid.uuid4(), "alice@x", _ctx())


def test_sod_allows_different_approver():
    conn = FakeConn(rows=[_row("PROPOSED", actor="alice@x")])
    res = _svc(conn).approve(uuid.uuid4(), "bob@x", _ctx())
    assert res.status == "APPLIED"


def test_reject_records_reason():
    conn = FakeConn(rows=[_row("PROPOSED")])
    res = _svc(conn).reject(uuid.uuid4(), "bob@x", reason="false positive")
    assert res.status == "REJECTED"
    flat = " ".join(str(p) for p in conn.cursor_obj.params)
    assert "false positive" in flat
