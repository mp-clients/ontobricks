from back.objects.actions.base import (
    ActionStatus, ApprovalPolicy, OverlayEdit, ActionContext,
)

def test_enums_have_expected_members():
    assert {s.value for s in ActionStatus} == {
        "PROPOSED", "APPROVED", "APPLIED", "REJECTED", "REVERTED", "OVERRIDDEN", "FAILED",
    }
    assert {p.value for p in ApprovalPolicy} == {"AUTO", "REQUIRES_APPROVAL"}

def test_overlay_edit_is_immutable_value():
    e = OverlayEdit(object_type="Customer", object_id="C1",
                    property="riskFlag", value={"severity": "high"})
    assert e.object_type == "Customer"
    assert e.value["severity"] == "high"

def test_action_context_carries_actor_and_connect():
    ctx = ActionContext(domain="customers", actor="jerry@moneypool.mx",
                        actor_kind="user", connect=lambda: None)
    assert ctx.actor_kind == "user"
    assert callable(ctx.connect)
