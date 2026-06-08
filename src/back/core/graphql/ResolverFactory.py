"""GraphQL resolver factory functions."""

from typing import Callable, List, Optional

import strawberry
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
        """Resolver for an overlay-backed scalar field on an object type."""

        def resolver(root):
            object_id = getattr(root, "id", None)
            if object_id is None:
                return None
            with connect() as conn, conn.cursor() as cur:
                return store.current_value(cur, object_type, str(object_id), prop)

        return resolver

    @staticmethod
    def make_action_mutation_resolver(service_factory, type_id, ctx_factory):
        """Resolver for a strawberry Mutation field that proposes an action."""

        def resolver(info, customer_id: str, severity: str, reason: str = ""):
            svc = service_factory(info)
            action_ctx = ctx_factory(info, customer_id)
            res = svc.propose(
                type_id,
                customer_id,
                {"customer_id": customer_id, "severity": severity, "reason": reason},
                action_ctx,
            )
            return ActionMutationResult(
                action_id=str(res.action_id) if res.action_id else None,
                status=res.status,
                errors=list(res.errors),
            )

        return resolver
