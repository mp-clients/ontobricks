"""The Transaction.decision overlay read-back field is attached when the
fraud ontology has a Transaction class. Built through strawberry."""
import back.objects.actions.types  # noqa: F401  (registers ReviewTransaction)
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder


def test_transaction_decision_field_present_in_sdl():
    classes = [{"name": "Transaction", "uri": "http://ex/fraud/Transaction",
                "dataProperties": [{"name": "amount", "uri": "http://ex/fraud/amount"}]}]
    props = []
    builder = GraphQLSchemaBuilder()
    result = builder.build_for_domain(
        classes, props, "http://ex/fraud/", "fraud",
        overlay_connect=lambda: None)          # connect never called at build time
    assert result is not None
    schema, _meta = result
    sdl = schema.as_str()
    assert "type Transaction" in sdl
    assert "decision" in sdl          # overlay-backed JSON field
