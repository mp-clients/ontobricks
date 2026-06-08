"""TDD tests for GraphQLSchemaBuilder._add_overlay_fields.

Builds THROUGH strawberry to catch annotation/typing bugs that direct calls miss.
"""
import strawberry
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder


class _Cur:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def cursor(self): return _Cur()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_add_overlay_fields_attaches_buildable_json_field():
    Customer = type("Customer", (), {"__annotations__": {"id": strawberry.ID}, "id": ""})
    py_classes = {"Customer": Customer}
    GraphQLSchemaBuilder._add_overlay_fields(
        py_classes, {"Customer": {"riskFlag"}}, "customers", lambda: _Conn())
    gql = strawberry.type(Customer)

    @strawberry.type
    class Query:
        @strawberry.field
        def customer(self) -> gql:  # type: ignore
            return gql(id="C1")

    sdl = strawberry.Schema(query=Query).as_str()
    assert "riskFlag" in sdl


def test_add_overlay_fields_skips_unknown_type():
    py_classes = {"Customer": type("Customer", (), {"__annotations__": {"id": strawberry.ID}, "id": ""})}
    GraphQLSchemaBuilder._add_overlay_fields(py_classes, {"Account": {"frozen"}}, "customers", lambda: _Conn())
    assert not hasattr(py_classes["Customer"], "frozen")
