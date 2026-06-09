from back.objects.actions.action_type import ActionType
from back.objects.actions.types.review_withdrawal import ReviewWithdrawal
from back.objects.actions.audit import AuditLog
from tests.units.actions.fakes import FakeCursor


def test_default_no_sod():
    assert ActionType.requires_separate_approver is False


def test_review_withdrawal_requires_separate_approver():
    assert ReviewWithdrawal().requires_separate_approver is True


def test_auditlog_get_returns_actor():
    cur = FakeCursor(rows=[("review_withdrawal", "fraud", "Withdrawal", "W1",
                            {"recommendation": "reject"}, "PROPOSED", "alice@x")])
    rec = AuditLog().get(cur, __import__("uuid").uuid4())
    assert rec["actor"] == "alice@x"
    assert "actor" in cur.executed[0].lower()
