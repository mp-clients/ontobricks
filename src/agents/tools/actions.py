"""Agent tool adapter — lets the agent loop PROPOSE Actions (kinetic loop).
Thin marshalling over back.objects.actions.ActionService."""
import json
from typing import Callable, Dict, List
from back.core.logging import get_logger
from agents.tools.context import ToolContext
from back.objects.actions.base import ActionContext
from back.objects.actions.registry import default_registry
import back.objects.actions.types  # noqa: F401  (registers action types)
from back.objects.actions.service import ActionService, ActionError

logger = get_logger(__name__)


def _build_service(ctx: ToolContext) -> ActionService:
    connect = ctx.metadata.get("lakebase_connect")
    return ActionService(registry=default_registry, connect=connect)


def tool_propose_flag_customer_high_risk(ctx: ToolContext, *, customer_id: str = "",
                                         severity: str = "", reason: str = "",
                                         **_kw) -> str:
    actor = getattr(ctx, "actor", "") or "agent"
    try:
        svc = _build_service(ctx)
        action_ctx = ActionContext(
            domain=ctx.domain_name or "customers", actor=actor, actor_kind="agent",
            connect=ctx.metadata.get("lakebase_connect"))
        res = svc.propose("flag_customer_high_risk", customer_id,
                          {"customer_id": customer_id, "severity": severity, "reason": reason},
                          action_ctx)
        return json.dumps({"success": not res.errors, "status": res.status,
                           "action_id": str(res.action_id) if res.action_id else None,
                           "errors": res.errors})
    except ActionError as exc:
        return json.dumps({"success": False, "error": str(exc)})


ACTION_TOOL_DEFINITIONS: List[dict] = [{
    "type": "function",
    "function": {
        "name": "propose_flag_customer_high_risk",
        "description": ("Propose flagging a customer as high-risk in the ontology. "
                        "Requires human approval before it is applied. Returns the action_id."),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer object id."},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                "reason": {"type": "string", "description": "Required when severity is 'high'."},
            },
            "required": ["customer_id", "severity"],
        },
    },
}]

ACTION_TOOL_HANDLERS: Dict[str, Callable] = {
    "propose_flag_customer_high_risk": tool_propose_flag_customer_high_risk,
}
