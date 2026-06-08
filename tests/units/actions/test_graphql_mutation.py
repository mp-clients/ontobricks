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
