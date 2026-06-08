from __future__ import annotations
from typing import List, Tuple
from pydantic import BaseModel, Field
from back.objects.actions.action_type import ActionType
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


class FlagHighRiskParams(BaseModel):
    severity: str = Field(pattern="^(low|medium|high)$")
    reason: str = ""
    customer_id: str  # the object_id; carried in params for the GraphQL/tool adapters


class FlagCustomerHighRisk(ActionType):
    id = "flag_customer_high_risk"
    object_type = "Customer"
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = FlagHighRiskParams

    def validate(self, ctx: ActionContext, params: FlagHighRiskParams) -> List[str]:
        errors: List[str] = []
        if params.severity == "high" and not params.reason.strip():
            errors.append("reason is required when severity is 'high'")
        return errors

    def apply(self, ctx: ActionContext, params: FlagHighRiskParams) -> List[OverlayEdit]:
        return [OverlayEdit(
            object_type="Customer", object_id=params.customer_id,
            property="riskFlag",
            value={"severity": params.severity, "reason": params.reason},
        )]

    def effects(self, params: FlagHighRiskParams) -> List[Tuple[str, dict]]:
        return [("noop_log", {"object_id": params.customer_id,
                              "severity": params.severity})]
