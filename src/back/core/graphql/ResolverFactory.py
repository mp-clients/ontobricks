"""GraphQL resolver factory functions."""

from typing import Callable, List, Optional

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from back.core.graphql.SchemaMetadata import SchemaMetadata
from back.core.logging import get_logger

logger = get_logger(__name__)


@strawberry.type
class ActionMutationResult:
    """Result returned by action mutation fields."""

    action_id: Optional[str]
    status: str
    errors: List[str]


class ResolverFactory:
    """Factory for creating GraphQL resolvers from schema metadata."""

    @staticmethod
    def make_list_resolver(
        metadata: SchemaMetadata,
        type_name: str,
        gql_type: type,
    ) -> Callable:
        """Create a root list resolver for a given entity type."""

        def resolver(
            info: Info,
            limit: int = 50,
            offset: int = 0,
            search: Optional[str] = None,
        ) -> List[gql_type]:  # type: ignore[valid-type]
            store = info.context["triplestore"]
            table = info.context["table_name"]
            depth = info.context.get("depth")
            return metadata.resolve_list(
                store, table, type_name, limit, offset, search, depth=depth
            )

        resolver.__name__ = f"resolve_{type_name}_list"
        return resolver

    @staticmethod
    def make_single_resolver(
        metadata: SchemaMetadata,
        type_name: str,
        gql_type: type,
    ) -> Callable:
        """Create a root single-entity resolver for a given type."""

        def resolver(
            info: Info,
            id: strawberry.ID,
        ) -> Optional[gql_type]:  # type: ignore[valid-type]
            store = info.context["triplestore"]
            table = info.context["table_name"]
            depth = info.context.get("depth")
            return metadata.resolve_single(
                store, table, type_name, str(id), depth=depth
            )

        resolver.__name__ = f"resolve_{type_name}_single"
        return resolver

    @staticmethod
    def make_overlay_field_resolver(store, connect, object_type, prop):
        """Resolver for an overlay-backed scalar field on an object type.

        Returns the current overlay value (arbitrary JSON) for the object's id,
        or None. Read failures are isolated to this field (logged, return None)
        so one field never breaks the whole query."""

        def resolver(root) -> Optional[JSON]:
            object_id = getattr(root, "id", None)
            if object_id is None:
                return None
            try:
                with connect() as conn, conn.cursor() as cur:
                    return store.current_value(cur, object_type, str(object_id), prop)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "overlay field %s.%s read failed: %s", object_type, prop, exc
                )
                return None

        return resolver

    @staticmethod
    def make_approve_resolver(service_factory, ctx_factory):
        """Mutation resolver: approve a PROPOSED action (approver = current user)."""
        from back.objects.actions.service import ActionError

        def approveAction(info: Info, action_id: strawberry.ID) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.approve(str(action_id), ctx.actor, ctx)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return approveAction

    @staticmethod
    def make_reject_resolver(service_factory, ctx_factory):
        """Mutation resolver: reject a PROPOSED action with an optional reason."""
        from back.objects.actions.service import ActionError

        def rejectAction(info: Info, action_id: strawberry.ID, reason: str = "") -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.reject(str(action_id), ctx.actor, reason)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return rejectAction

    @staticmethod
    def make_review_withdrawal_resolver(service_factory, ctx_factory):
        """Mutation resolver: an agent proposes a withdrawal-review decision."""

        def reviewWithdrawal(info: Info, withdrawal_id: str, recommendation: str,
                             rationale: str = "",
                             risk_assessment: Optional[JSON] = None) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, withdrawal_id)
            # purpose-built resolver for the reviewWithdrawal field; the action type id is fixed by design
            res = svc.propose(
                "review_withdrawal",
                withdrawal_id,
                {
                    "withdrawal_id": withdrawal_id,
                    "recommendation": recommendation,
                    "rationale": rationale,
                    "risk_assessment": risk_assessment,
                },
                ctx,
            )
            return ActionMutationResult(
                action_id=str(res.action_id) if res.action_id else None,
                status=res.status,
                errors=list(res.errors),
            )
        return reviewWithdrawal

    @staticmethod
    def make_override_resolver(service_factory, ctx_factory):
        """Mutation resolver: a human overrides a PROPOSED action with their own decision."""
        from back.objects.actions.service import ActionError

        def overrideAction(info: Info, action_id: strawberry.ID, decision: str,
                           reason: str) -> ActionMutationResult:
            svc = service_factory(info)
            ctx = ctx_factory(info, None)
            try:
                res = svc.override(str(action_id), ctx.actor, decision, reason, ctx)
                return ActionMutationResult(
                    action_id=str(res.action_id) if res.action_id else None,
                    status=res.status, errors=list(res.errors))
            except ActionError as exc:
                return ActionMutationResult(action_id=str(action_id), status="ERROR",
                                            errors=[str(exc)])
        return overrideAction
