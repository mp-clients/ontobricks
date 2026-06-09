"""Build-through-strawberry tests for reviewWithdrawal + overrideAction."""
import strawberry
from back.core.graphql.ResolverFactory import ResolverFactory
from back.objects.actions.service import ActionError


def test_review_resolver_proposes():
    seen = {}

    class _Svc:
        def propose(self, type_id, object_id, params, ctx):
            seen.update(type_id=type_id, object_id=object_id, params=params)
            class R: action_id = "A1"; status = "PROPOSED"; errors = []
            return R()

    class _Ctx: actor = "agent@x"

    r = ResolverFactory.make_review_withdrawal_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, withdrawal_id="W1", recommendation="reject", rationale="spike")
    assert out.status == "PROPOSED"
    assert seen["type_id"] == "review_withdrawal" and seen["object_id"] == "W1"
    assert seen["params"]["recommendation"] == "reject"


def test_override_resolver_calls_service():
    seen = {}

    class _Svc:
        def override(self, aid, approver, decision, reason, ctx):
            seen.update(aid=aid, approver=approver, decision=decision, reason=reason)
            class R: action_id = aid; status = "OVERRIDDEN"; errors = []
            return R()

    class _Ctx: actor = "human@x"

    r = ResolverFactory.make_override_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1", decision="approve", reason="known customer")
    assert out.status == "OVERRIDDEN"
    assert seen["approver"] == "human@x" and seen["decision"] == "approve"
    assert seen["reason"] == "known customer"


def test_override_resolver_catches_actionerror():
    class _Svc:
        def override(self, *a, **k): raise ActionError("cannot override action in status APPLIED")

    class _Ctx: actor = "human@x"

    r = ResolverFactory.make_override_resolver(
        service_factory=lambda info: _Svc(), ctx_factory=lambda info, oid: _Ctx())
    out = r(info=None, action_id="A1", decision="approve", reason="x")
    assert out.status == "ERROR" and out.errors and "override" in out.errors[0]


def test_mutation_sdl_has_review_and_override():
    from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder
    import strawberry

    mut = GraphQLSchemaBuilder._build_mutation(
        service_factory=lambda info: None, ctx_factory=lambda info, oid: None)

    @strawberry.type
    class Query:
        @strawberry.field
        def ping(self) -> str: return "ok"

    sdl = strawberry.Schema(query=Query, mutation=mut).as_str()
    assert "reviewWithdrawal" in sdl
    assert "overrideAction" in sdl
    # slice-3 governance fields remain
    assert "approveAction" in sdl and "rejectAction" in sdl
