from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from pydantic import ValidationError as PydanticValidationError
from back.core.logging import get_logger
from back.objects.actions.base import ActionContext, ApprovalPolicy
from back.objects.actions.registry import ActionRegistry
from back.objects.actions.overlay_store import OverlayStore
from back.objects.actions.audit import AuditLog, EffectOutbox

logger = get_logger(__name__)


class ActionError(Exception):
    """Unrecoverable Action invocation error (unknown type, bad state)."""


@dataclass
class ActionResult:
    action_id: Optional[uuid.UUID]
    status: str
    errors: List[str] = field(default_factory=list)


class ActionService:
    """The single mutation path for the ontology overlay."""

    def __init__(self, registry: ActionRegistry, connect: Callable[[], Any]):
        self._registry = registry
        self._connect = connect
        self._audit = AuditLog()
        self._outbox = EffectOutbox()

    def propose(self, type_id: str, object_id: str, raw_params: dict,
                ctx: ActionContext) -> ActionResult:
        try:
            atype = self._registry.get(type_id)
        except KeyError as exc:
            raise ActionError(str(exc)) from exc

        try:
            params = atype.params_model(**raw_params)
        except PydanticValidationError as exc:
            return ActionResult(None, "FAILED", [str(exc)])

        errors = atype.validate(ctx, params)
        if errors:
            return ActionResult(None, "FAILED", errors)

        with self._connect() as conn:
            with conn.transaction():
                cur = conn.cursor()
                aid = self._audit.insert_proposed(
                    cur, action_type=type_id, domain=ctx.domain,
                    object_type=atype.object_type, object_id=object_id,
                    params=params.model_dump(), actor=ctx.actor,
                    actor_kind=ctx.actor_kind)
                if atype.approval_policy == ApprovalPolicy.AUTO:
                    self._apply(cur, atype, aid, object_id, params, ctx)
                    return ActionResult(aid, "APPLIED")
        return ActionResult(aid, "PROPOSED")

    def approve(self, action_id: uuid.UUID, approver: str, ctx: ActionContext) -> ActionResult:
        with self._connect() as conn:
            with conn.transaction():
                cur = conn.cursor()
                rec = self._audit.get(cur, action_id)
                if rec is None:
                    raise ActionError(f"unknown action: {action_id}")
                if rec["status"] != "PROPOSED":
                    raise ActionError(f"cannot approve action in status {rec['status']}")
                atype = self._registry.get(rec["action_type"])
                params = atype.params_model(**rec["params"])
                self._audit.mark(cur, action_id, "APPROVED", approved_by=approver)
                self._apply(cur, atype, action_id, rec["object_id"], params, ctx)
        return ActionResult(action_id, "APPLIED")

    def reject(self, action_id: uuid.UUID, approver: str) -> ActionResult:
        with self._connect() as conn, conn.transaction():
            cur = conn.cursor()
            rec = self._audit.get(cur, action_id)
            if rec is None or rec["status"] != "PROPOSED":
                raise ActionError(
                    f"cannot reject action in status "
                    f"{rec['status'] if rec else 'unknown'}")
            self._audit.mark(cur, action_id, "REJECTED", approved_by=approver)
        return ActionResult(action_id, "REJECTED")

    def revert(self, action_id: uuid.UUID, ctx: ActionContext) -> ActionResult:
        overlay = OverlayStore(domain=ctx.domain)
        with self._connect() as conn, conn.transaction():
            cur = conn.cursor()
            rec = self._audit.get(cur, action_id)
            if rec is None or rec["status"] != "APPLIED":
                raise ActionError("only APPLIED actions can be reverted")
            overlay.revert_action(cur, action_id)
            self._audit.mark(cur, action_id, "REVERTED")
            child = self._audit.insert_proposed(
                cur, action_type=rec["action_type"], domain=rec["domain"],
                object_type=rec["object_type"], object_id=rec["object_id"],
                params=rec["params"], actor=ctx.actor, actor_kind=ctx.actor_kind,
                parent_action_id=action_id)
            self._audit.mark(cur, child, "REVERTED")
        return ActionResult(action_id, "REVERTED")

    def _apply(self, cur: Any, atype, action_id: uuid.UUID, object_id: str,
               params, ctx: ActionContext) -> None:
        overlay = OverlayStore(domain=ctx.domain)
        edits = atype.apply(ctx, params)
        overlay.apply_edits(cur, action_id, edits)
        after = {e.property: e.value for e in edits}
        self._audit.mark(cur, action_id, "APPLIED", after=after)
        for name, payload in atype.effects(params):
            self._outbox.enqueue(cur, action_id, name, {**payload, "action_id": str(action_id)})
