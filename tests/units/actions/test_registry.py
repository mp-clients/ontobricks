import pytest
from pydantic import BaseModel
from back.objects.actions.base import ApprovalPolicy, OverlayEdit, ActionContext
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry


class _Params(BaseModel):
    value: str

class _Demo(ActionType):
    id = "demo_action"
    object_type = "Customer"
    approval_policy = ApprovalPolicy.AUTO
    params_model = _Params
    def validate(self, ctx, p):  # returns list[str] of errors
        return [] if p.value else ["value required"]
    def apply(self, ctx, p):
        return [OverlayEdit("Customer", "C1", "demo", {"v": p.value})]
    def effects(self, p):
        return []

def test_register_and_resolve():
    reg = ActionRegistry()
    reg.register(_Demo())
    assert reg.get("demo_action").object_type == "Customer"

def test_unknown_type_raises():
    reg = ActionRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")

def test_duplicate_registration_raises():
    reg = ActionRegistry()
    reg.register(_Demo())
    with pytest.raises(ValueError):
        reg.register(_Demo())
