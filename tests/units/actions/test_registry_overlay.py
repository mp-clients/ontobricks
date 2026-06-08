from pydantic import BaseModel
from back.objects.actions.base import ApprovalPolicy, OverlayEdit
from back.objects.actions.action_type import ActionType
from back.objects.actions.registry import ActionRegistry

class _P(BaseModel):
    pass

def _mk(_id, otype, fields):
    class T(ActionType):
        id = _id; object_type = otype; approval_policy = ApprovalPolicy.AUTO
        params_model = _P; overlay_fields = fields
        def validate(self, ctx, p): return []
        def apply(self, ctx, p): return []
        def effects(self, p): return []
    return T()

def test_empty_registry_returns_empty():
    assert ActionRegistry().overlay_fields_by_type() == {}

def test_aggregates_by_object_type():
    reg = ActionRegistry()
    reg.register(_mk("a", "Customer", ["riskFlag"]))
    reg.register(_mk("b", "Customer", ["watchlist"]))
    reg.register(_mk("c", "Account", ["frozen"]))
    reg.register(_mk("d", "Order", []))  # no fields -> no entry
    out = reg.overlay_fields_by_type()
    assert out["Customer"] == {"riskFlag", "watchlist"}
    assert out["Account"] == {"frozen"}
    assert "Order" not in out
