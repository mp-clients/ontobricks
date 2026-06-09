import pytest
from pydantic import ValidationError
from back.objects.actions.base import ActionContext, ApprovalPolicy
from back.objects.actions.types.review_withdrawal import (
    ReviewWithdrawal, ReviewWithdrawalParams,
)


def _ctx(actor="reviewer@x", metadata=None):
    return ActionContext(domain="fraud", actor=actor, actor_kind="user",
                         connect=lambda: None, metadata=metadata or {})


def test_type_declares_withdrawal_overlay_and_4eyes():
    t = ReviewWithdrawal()
    assert t.id == "review_withdrawal"
    assert t.object_type == "Withdrawal"
    assert t.overlay_fields == ["decision"]
    assert t.requires_separate_approver is True
    assert t.approval_policy == ApprovalPolicy.REQUIRES_APPROVAL


def test_apply_accept_composes_agreed_decision():
    # No override in metadata => accept: human_decision == agent_recommendation.
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="reject",
                               rationale="velocity spike")
    edits = t.apply(_ctx(actor="boss@x"), p)
    assert len(edits) == 1
    e = edits[0]
    assert e.object_type == "Withdrawal" and e.object_id == "W1" and e.property == "decision"
    assert e.value["agent_recommendation"] == "reject"
    assert e.value["human_decision"] == "reject"
    assert e.value["agreed"] is True
    assert e.value["decided_by"] == "boss@x"
    assert "decided_at" in e.value


def test_apply_override_flips_decision_and_marks_disagreement():
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="reject",
                               rationale="velocity spike")
    ctx = _ctx(actor="boss@x",
               metadata={"decision_override": "approve", "override_reason": "known customer"})
    e = t.apply(ctx, p)[0]
    assert e.value["agent_recommendation"] == "reject"
    assert e.value["human_decision"] == "approve"
    assert e.value["agreed"] is False
    assert e.value["reason"] == "known customer"


def test_params_reject_bad_recommendation():
    with pytest.raises(ValidationError):
        ReviewWithdrawalParams(withdrawal_id="W1", recommendation="maybe")


def test_effects_enqueue_noop_for_now():
    t = ReviewWithdrawal()
    p = ReviewWithdrawalParams(withdrawal_id="W1", recommendation="approve")
    effects = t.effects(p)
    assert effects and effects[0][0] == "noop_log"
    assert effects[0][1]["withdrawal_id"] == "W1"
