"""Tests for GraphQL mutation resolver and overlay-backed field resolver."""

from back.core.graphql.ResolverFactory import ResolverFactory


def test_overlay_field_resolver_reads_current_value():
    class _Store:
        def current_value(self, cur, ot, oid, prop):
            return {"severity": "high"}

    class _C:
        def __enter__(s):
            return s

        def __exit__(s, *a):
            return False

    class _Conn:
        def cursor(self):
            return _C()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    resolver = ResolverFactory.make_overlay_field_resolver(
        store=_Store(), connect=lambda: _Conn(), object_type="Customer", prop="riskFlag"
    )

    class Obj:
        id = "C1"

    assert resolver(Obj())["severity"] == "high"


def test_mutation_resolver_calls_service():
    calls = {}

    class _Svc:
        def propose(self, type_id, object_id, params, ctx):
            calls.update(type_id=type_id, object_id=object_id, params=params)

            class R:
                action_id = "aid"
                status = "PROPOSED"
                errors = []

            return R()

    resolver = ResolverFactory.make_action_mutation_resolver(
        service_factory=lambda info: _Svc(),
        type_id="flag_customer_high_risk",
        ctx_factory=lambda info, oid: None,
    )
    out = resolver(info=None, customer_id="C1", severity="high", reason="r")
    assert calls["type_id"] == "flag_customer_high_risk"
    assert out.status == "PROPOSED"


def test_mutation_schema_builds_through_strawberry():
    """Regression: the mutation resolver must be fully annotated (info + return
    type) so strawberry can build the schema. A direct resolver call (above)
    does NOT exercise this — only schema construction does, which is what the
    real app does on every GraphQL request. Guards against
    MissingArgumentsAnnotationsError / UnresolvedFieldTypeError."""
    import strawberry
    from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder

    mutation = GraphQLSchemaBuilder._build_mutation(
        service_factory=lambda info: None,
        ctx_factory=lambda info, oid: None,
    )

    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str:
            return "ok"

    schema = strawberry.Schema(query=Query, mutation=mutation)
    sdl = schema.as_str()
    assert "flagCustomerHighRisk" in sdl
    assert "ActionMutationResult" in sdl
