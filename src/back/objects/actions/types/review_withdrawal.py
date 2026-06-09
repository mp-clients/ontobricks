from __future__ import annotations
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field
from back.objects.actions.action_type import ActionType
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewWithdrawalParams(BaseModel):
    withdrawal_id: str
    recommendation: str = Field(pattern="^(approve|reject)$")
    rationale: str = ""
    risk_assessment: Optional[dict] = None  # agent's risk detail, preserved on the proposal (used by reviewWithdrawal resolver + slice-5 agent)


class ReviewWithdrawal(ActionType):
    """An agent proposes a decision on a risky withdrawal; a human accepts
    (approveAction) or overrides (overrideAction). The applied overlay records
    both the agent recommendation and the human decision."""
    id = "review_withdrawal"
    object_type = "Withdrawal"
    overlay_fields = ["decision"]
    requires_separate_approver = True
    approval_policy = ApprovalPolicy.REQUIRES_APPROVAL
    params_model = ReviewWithdrawalParams

    def validate(self, ctx: ActionContext, params: ReviewWithdrawalParams) -> List[str]:
        # No propose-time preconditions yet; override-reason is enforced in ActionService.override.
        return []

    def apply(self, ctx: ActionContext, params: ReviewWithdrawalParams) -> List[OverlayEdit]:
        override = (ctx.metadata or {}).get("decision_override")
        human_decision = override or params.recommendation
        reason = (ctx.metadata or {}).get("override_reason", "")
        value = {
            "agent_recommendation": params.recommendation,
            "human_decision": human_decision,
            "agreed": human_decision == params.recommendation,
            "decided_by": ctx.actor,
            "reason": reason,
            "decided_at": _utcnow_iso(),
        }
        return [OverlayEdit(
            object_type="Withdrawal",
            object_id=params.withdrawal_id,
            property="decision",
            value=value,
        )]

    def effects(self, params: ReviewWithdrawalParams) -> List[Tuple[str, dict]]:
        # Slice 6 replaces noop_log with the moneypool main-app callback.
        return [("noop_log", {"withdrawal_id": params.withdrawal_id})]
