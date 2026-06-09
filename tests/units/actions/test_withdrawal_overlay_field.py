"""The Withdrawal.decision overlay read-back field is attached when the
fraud ontology has a Withdrawal class. Built through strawberry."""
import back.objects.actions.types  # noqa: F401  (registers ReviewWithdrawal)
from back.core.graphql.GraphQLSchemaBuilder import GraphQLSchemaBuilder


def test_withdrawal_decision_field_present_in_sdl():
    classes = [{"name": "Withdrawal", "uri": "http://ex/fraud/Withdrawal",
                "dataProperties": [{"name": "amount", "uri": "http://ex/fraud/amount"}]}]
    props = []
    builder = GraphQLSchemaBuilder()
    result = builder.build_for_domain(
        classes, props, "http://ex/fraud/", "fraud",
        overlay_connect=lambda: None)          # connect never called at build time
    assert result is not None
    schema, _meta = result
    sdl = schema.as_str()
    assert "type Withdrawal" in sdl
    assert "decision" in sdl          # overlay-backed JSON field
