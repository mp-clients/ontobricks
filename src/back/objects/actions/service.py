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
        """Validate and record a new Action; apply immediately if AUTO-approval policy."""
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

        applied = False
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    aid = self._audit.insert_proposed(
                        cur, action_type=type_id, domain=ctx.domain,
                        object_type=atype.object_type, object_id=object_id,
                        params=params.model_dump(), actor=ctx.actor,
                        actor_kind=ctx.actor_kind)
                    if atype.approval_policy == ApprovalPolicy.AUTO:
                        self._apply(cur, atype, aid, object_id, params, ctx)
                        applied = True
        if applied:
            self._drain_effects()
            return ActionResult(aid, "APPLIED")
        return ActionResult(aid, "PROPOSED")

    def approve(self, action_id: uuid.UUID, approver: str, ctx: ActionContext) -> ActionResult:
        """Approve a PROPOSED action and apply its overlay edits."""
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    rec = self._audit.get(cur, action_id)
                    if rec is None:
                        raise ActionError(f"unknown action: {action_id}")
                    if rec["status"] != "PROPOSED":
                        raise ActionError(f"cannot approve action in status {rec['status']}")
                    atype = self._registry.get(rec["action_type"])
                    if getattr(atype, "requires_separate_approver", False) \
                            and approver == rec.get("actor"):
                        raise ActionError(
                            "4-eyes: the proposer cannot approve their own action")
                    params = atype.params_model(**rec["params"])
                    self._audit.mark(cur, action_id, "APPROVED", approved_by=approver)
                    self._apply(cur, atype, action_id, rec["object_id"], params, ctx)
        self._drain_effects()
        return ActionResult(action_id, "APPLIED")

    def reject(self, action_id: uuid.UUID, approver: str, reason: str = "") -> ActionResult:
        """Reject a PROPOSED action without applying any overlay edits."""
        with self._connect() as conn, conn.transaction():
            with conn.cursor() as cur:
                rec = self._audit.get(cur, action_id)
                if rec is None or rec["status"] != "PROPOSED":
                    raise ActionError(
                        f"cannot reject action in status "
                        f"{rec['status'] if rec else 'unknown'}")
                self._audit.mark(cur, action_id, "REJECTED", approved_by=approver,
                                 after={"rejected_reason": reason} if reason else None)
        return ActionResult(action_id, "REJECTED")

    def revert(self, action_id: uuid.UUID, ctx: ActionContext) -> ActionResult:
        """Revert an APPLIED action by rolling back its overlay edits and recording a REVERTED child."""
        overlay = OverlayStore(domain=ctx.domain)
        with self._connect() as conn, conn.transaction():
            with conn.cursor() as cur:
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

    def _drain_effects(self) -> None:
        """Fire pending effects after commit. Best-effort; never raises into
        the caller (effect failures are isolated in the outbox)."""
        try:
            from back.core.task_manager import run_background_task
            from back.objects.actions.effects import EffectRunner, NoopLogEffect

            def _run(connect):
                EffectRunner(connect, {"noop_log": NoopLogEffect()}).run_pending()

            run_background_task("drain-effects", "effects", _run, self._connect)
        except Exception as exc:  # noqa: BLE001
            logger.warning("effect drain could not be scheduled: %s", exc)

    def override(self, action_id: uuid.UUID, approver: str, decision: str,
                 reason: str, ctx: ActionContext) -> ActionResult:
        """Override a PROPOSED action's recommendation with the human's own
        decision. Marks the agent proposal OVERRIDDEN and writes the human's
        decision overlay in the same transaction (agent recommendation preserved
        in the row's params)."""
        if decision not in ("approve", "reject"):
            raise ActionError("decision must be 'approve' or 'reject'")
        if not reason or not reason.strip():
            raise ActionError("override requires a reason")
        with self._connect() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    rec = self._audit.get(cur, action_id)
                    if rec is None:
                        raise ActionError(f"unknown action: {action_id}")
                    if rec["status"] != "PROPOSED":
                        raise ActionError(
                            f"cannot override action in status {rec['status']}")
                    atype = self._registry.get(rec["action_type"])
                    params = atype.params_model(**rec["params"])
                    ctx.metadata = {**(ctx.metadata or {}),
                                    "decision_override": decision,
                                    "override_reason": reason}
                    self._apply(cur, atype, action_id, rec["object_id"], params, ctx,
                                status="OVERRIDDEN", approved_by=approver,
                                extra_after={"override_decision": decision,
                                             "override_reason": reason})
        self._drain_effects()
        return ActionResult(action_id, "OVERRIDDEN")

    def _apply(self, cur: Any, atype, action_id: uuid.UUID, object_id: str,
               params, ctx: ActionContext, *, status: str = "APPLIED",
               approved_by: Optional[str] = None,
               extra_after: Optional[dict] = None) -> None:
        overlay = OverlayStore(domain=ctx.domain)
        edits = atype.apply(ctx, params)
        before = {e.property: overlay.current_value(cur, e.object_type, e.object_id, e.property)
                  for e in edits}
        overlay.apply_edits(cur, action_id, edits)
        after = {e.property: e.value for e in edits}
        if extra_after:
            after = {**after, **extra_after}
        self._audit.mark(cur, action_id, status, before=before, after=after,
                         approved_by=approved_by)
        for name, payload in atype.effects(params):
            self._outbox.enqueue(cur, action_id, name, {**payload, "action_id": str(action_id)})
