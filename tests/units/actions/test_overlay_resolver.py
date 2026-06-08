import typing
from back.core.graphql.ResolverFactory import ResolverFactory


class _Cur:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def cursor(self): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Store:
    def __init__(self, val): self._val = val
    def current_value(self, cur, ot, oid, prop): return self._val


class _Obj:
    id = "C1"


def test_resolver_has_return_annotation():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"severity": "high"}), lambda: _Conn(), "Customer", "riskFlag")
    assert "return" in typing.get_type_hints(r)


def test_resolver_returns_value():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"severity": "high"}), lambda: _Conn(), "Customer", "riskFlag")
    assert r(_Obj())["severity"] == "high"


def test_resolver_none_when_no_id():
    r = ResolverFactory.make_overlay_field_resolver(_Store({"x": 1}), lambda: _Conn(), "Customer", "riskFlag")
    class NoId: pass
    assert r(NoId()) is None


def test_resolver_isolates_errors():
    def boom(): raise RuntimeError("db down")
    r = ResolverFactory.make_overlay_field_resolver(_Store({"x": 1}), boom, "Customer", "riskFlag")
    assert r(_Obj()) is None
