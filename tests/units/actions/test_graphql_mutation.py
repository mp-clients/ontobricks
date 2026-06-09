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
        store=_Store(), connect=lambda: _Conn(), object_type="Withdrawal", prop="decision"
    )

    class Obj:
        id = "W1"

    assert resolver(Obj())["severity"] == "high"


def test_mutation_schema_builds_through_strawberry():
    """Regression: all mutation resolvers must be fully annotated so strawberry
    can build the schema. Guards against MissingArgumentsAnnotationsError /
    UnresolvedFieldTypeError."""
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
    assert "reviewWithdrawal" in sdl
    assert "approveAction" in sdl
    assert "overrideAction" in sdl
    assert "ActionMutationResult" in sdl
