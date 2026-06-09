"""Action type unit tests — re-pointed from the retired FlagCustomerHighRisk
customer demo to ReviewWithdrawal (fraud domain replacement).
Coverage intent preserved: metadata, validation, apply, effects."""
import pytest
from pydantic import ValidationError
from back.objects.actions.base import ApprovalPolicy, ActionContext
from back.objects.actions.types.review_withdrawal import ReviewWithdrawal, ReviewWithdrawalParams


def _ctx(actor="a@b.c", metadata=None):
    return ActionContext(domain="fraud", actor=actor, actor_kind="agent",
                        connect=lambda: None, metadata=metadata or {})


def test_metadata():
    a = ReviewWithdrawal()
    assert a.id == "review_withdrawal"
    assert a.object_type == "Withdrawal"
    assert a.approval_policy == ApprovalPolicy.REQUIRES_APPROVAL


def test_bad_recommendation_rejected_by_params():
    with pytest.raises(ValidationError):
        ReviewWithdrawalParams(withdrawal_id="W1", recommendation="maybe")


def test_apply_produces_decision_edit():
    a = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="reject",
                               rationale="velocity spike")
    edits = a.apply(_ctx(), p)
    assert len(edits) == 1
    assert edits[0].property == "decision"
    assert edits[0].value["agent_recommendation"] == "reject"


def test_effects_enqueue_noop_log():
    a = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="approve")
    assert a.effects(p)[0][0] == "noop_log"
