"""Agent tool adapter — lets the agent loop PROPOSE Actions (kinetic loop).
Thin marshalling over back.objects.actions.ActionService."""
import json
from typing import Callable, Dict, List
from back.core.logging import get_logger
from agents.tools.context import ToolContext
from back.objects.actions.base import ActionContext
from back.objects.actions.service import ActionService, ActionError

logger = get_logger(__name__)


def _build_service(ctx: ToolContext) -> ActionService:
    from back.objects.actions import build_action_service
    connect = ctx.metadata.get("lakebase_connect")
    return build_action_service(connect)


def tool_propose_review_withdrawal(ctx: ToolContext, *, withdrawal_id: str = "",
                                   recommendation: str = "", rationale: str = "",
                                   risk_assessment: dict | None = None,
                                   **_kw) -> str:
    actor = getattr(ctx, "actor", "") or "agent"
    try:
        svc = _build_service(ctx)
        action_ctx = ActionContext(
            domain=ctx.domain_name or "fraud", actor=actor, actor_kind="agent",
            connect=ctx.metadata.get("lakebase_connect"))
        res = svc.propose("review_withdrawal", withdrawal_id,
                          {"withdrawal_id": withdrawal_id,
                           "recommendation": recommendation,
                           "rationale": rationale,
                           "risk_assessment": risk_assessment},
                          action_ctx)
        return json.dumps({"success": not res.errors, "status": res.status,
                           "action_id": str(res.action_id) if res.action_id else None,
                           "errors": res.errors})
    except ActionError as exc:
        return json.dumps({"success": False, "error": str(exc)})


ACTION_TOOL_DEFINITIONS: List[dict] = [{
    "type": "function",
    "function": {
        "name": "propose_review_withdrawal",
        "description": ("Propose an approve/reject decision on a risky withdrawal. "
                        "Requires human approval (approveAction) or override (overrideAction) "
                        "before the decision is applied. Returns the action_id."),
        "parameters": {
            "type": "object",
            "properties": {
                "withdrawal_id": {"type": "string", "description": "Withdrawal object id."},
                "recommendation": {"type": "string", "enum": ["approve", "reject"]},
                "rationale": {"type": "string", "description": "Agent rationale for the recommendation."},
                "risk_assessment": {"type": "object", "description": "Optional structured risk detail."},
            },
            "required": ["withdrawal_id", "recommendation"],
        },
    },
}]

ACTION_TOOL_HANDLERS: Dict[str, Callable] = {
    "propose_review_withdrawal": tool_propose_review_withdrawal,
}
