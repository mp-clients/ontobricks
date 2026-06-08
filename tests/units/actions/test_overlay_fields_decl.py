from back.objects.actions.action_type import ActionType
from back.objects.actions.types.flag_customer_high_risk import FlagCustomerHighRisk


def test_actiontype_default_overlay_fields_empty():
    assert ActionType.overlay_fields == []


def test_flag_declares_riskflag():
    a = FlagCustomerHighRisk()
    assert a.object_type == "Customer"
    assert a.overlay_fields == ["riskFlag"]
