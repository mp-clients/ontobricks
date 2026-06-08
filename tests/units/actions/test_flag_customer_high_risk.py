from back.objects.actions.base import ApprovalPolicy, ActionContext
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk

def _ctx():
    return ActionContext(domain="customers", actor="a@b.c", actor_kind="agent", connect=lambda: None)

def test_metadata():
    a = FlagCustomerHighRisk()
    assert a.id == "flag_customer_high_risk"
    assert a.object_type == "Customer"
    assert a.approval_policy == ApprovalPolicy.REQUIRES_APPROVAL

def test_high_severity_requires_reason():
    a = FlagCustomerHighRisk()
    p_bad = a.params_model(severity="high", reason="", customer_id="C1")
    assert a.validate(_ctx(), p_bad)  # non-empty error list
    p_ok = a.params_model(severity="high", reason="sanctions match", customer_id="C1")
    assert a.validate(_ctx(), p_ok) == []

def test_apply_produces_riskflag_edit():
    a = FlagCustomerHighRisk()
    p = a.params_model(severity="high", reason="sanctions match", customer_id="C1")
    edits = a.apply(_ctx(), p)
    assert len(edits) == 1
    assert edits[0].property == "riskFlag"
    assert edits[0].value["severity"] == "high"

def test_effects_enqueue_noop_log():
    a = FlagCustomerHighRisk()
    p = a.params_model(severity="medium", reason="x", customer_id="C1")
    assert a.effects(p)[0][0] == "noop_log"
