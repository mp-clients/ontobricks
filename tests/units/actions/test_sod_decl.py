from back.objects.actions.action_type import ActionType
from back.objects.actions.types.review_transaction import ReviewTransaction
from back.objects.actions.audit import AuditLog
from tests.units.actions.fakes import FakeCursor


def test_default_no_sod():
    assert ActionType.requires_separate_approver is False


def test_review_transaction_requires_separate_approver():
    assert ReviewTransaction().requires_separate_approver is True


def test_auditlog_get_returns_actor():
    cur = FakeCursor(rows=[("review_transaction", "fraud", "Transaction", "W1",
                            {"recommendation": "reject"}, "PROPOSED", "alice@x")])
    rec = AuditLog().get(cur, __import__("uuid").uuid4())
    assert rec["actor"] == "alice@x"
    assert "actor" in cur.executed[0].lower()
