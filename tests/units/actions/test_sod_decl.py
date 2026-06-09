from back.objects.actions.action_type import ActionType
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk
from back.objects.actions.audit import AuditLog
from tests.units.actions.fakes import FakeCursor


def test_default_no_sod():
    assert ActionType.requires_separate_approver is False


def test_flag_requires_separate_approver():
    assert FlagCustomerHighRisk().requires_separate_approver is True


def test_auditlog_get_returns_actor():
    cur = FakeCursor(rows=[("flag_customer_high_risk", "Customers", "Customer", "C1",
                            {"severity": "high"}, "PROPOSED", "alice@x")])
    rec = AuditLog().get(cur, __import__("uuid").uuid4())
    assert rec["actor"] == "alice@x"
    assert "actor" in cur.executed[0].lower()
