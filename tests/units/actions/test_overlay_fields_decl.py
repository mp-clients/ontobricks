from back.objects.actions.action_type import ActionType
from back.objects.actions.types.review_withdrawal import ReviewWithdrawal


def test_actiontype_default_overlay_fields_empty():
    assert ActionType.overlay_fields == []


def test_review_withdrawal_declares_decision():
    a = ReviewWithdrawal()
    assert a.object_type == "Withdrawal"
    assert a.overlay_fields == ["decision"]
