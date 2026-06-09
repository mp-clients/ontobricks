from back.objects.actions.action_type import ActionType
from back.objects.actions.types.review_transaction import ReviewTransaction


def test_actiontype_default_overlay_fields_empty():
    assert ActionType.overlay_fields == []


def test_review_transaction_declares_decision():
    a = ReviewTransaction()
    assert a.object_type == "Transaction"
    assert a.overlay_fields == ["decision"]
