"""TDD tests for approveAction / rejectAction GraphQL mutations.

These tests build the schema THROUGH strawberry to catch missing type
annotations at schema-build time (the known bug class in this codebase).
"""

import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
from back.core.graphql.ResolverFactory import ResolverFactory
from back.objects.actions.service import ActionError


def test_mutation_sdl_has_approve_and_reject():
    mut = GraphQLSchemaBuilder._build_mutation(
        service_factory=lambda info: None, ctx_factory=lambda info, oid: None)

    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str: return "ok"

    sdl = strawberry.Schema(query=Query, mutation=mut).as_str()
    assert "approveAction" in sdl and "rejectAction" in sdl


def test_approve_resolver_calls_service():
    seen = {}

    class _Svc:
        def approve(self, aid, approver, ctx):
            seen.update(aid=aid, approver=approver)
            class R: action_id = aid; status = "APPLIED"; errors = []
            return R()

    class _Ctx: actor = "bob@x"

    r = ResolverFactory.make_approve_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1")
    assert out.status == "APPLIED" and seen["approver"] == "bob@x"


def test_approve_resolver_catches_actionerror():
    class _Svc:
        def approve(self, *a, **k): raise ActionError("4-eyes: ...")

    class _Ctx: actor = "alice@x"

    r = ResolverFactory.make_approve_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1")
    assert out.status == "ERROR" and out.errors and "4-eyes" in out.errors[0]
