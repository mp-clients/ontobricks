import json
from agents.tools.actions import ACTION_TOOL_DEFINITIONS, ACTION_TOOL_HANDLERS


def test_tool_definition_exposes_review_withdrawal():
    names = [d["function"]["name"] for d in ACTION_TOOL_DEFINITIONS]
    assert "propose_review_withdrawal" in names


def test_handler_returns_json_with_action_id(monkeypatch):
    class _Res:
        action_id = "11111111-1111-1111-1111-111111111111"; status = "PROPOSED"; errors = []

    class _Svc:
        def propose(self, *a, **k): return _Res()

    monkeypatch.setattr("agents.tools.actions._build_service", lambda ctx: _Svc())
    from agents.tools.context import ToolContext
    ctx = ToolContext(host="h", token="t", domain_name="fraud", actor="agent:dtwin")
    out = ACTION_TOOL_HANDLERS["propose_review_withdrawal"](
        ctx, withdrawal_id="W1", recommendation="reject", rationale="velocity spike")
    payload = json.loads(out)
    assert payload["status"] == "PROPOSED" and payload["action_id"]
