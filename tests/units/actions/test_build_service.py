import back.objects.actions as _actions
from back.objects.actions import build_action_service
from back.objects.actions.service import ActionService
from tests.units.actions.fakes import FakeConn


def test_build_action_service_ensures_schema_and_returns_service():
    # Reset the process-wide flag so ensure_schema always runs in this test.
    _actions._schema_ready = False

    conn = FakeConn()
    svc = build_action_service(lambda: conn.ctx())
    assert isinstance(svc, ActionService)
    # ensure_schema ran the DDL on first build
    assert any("create table" in s.lower() for s in conn.cursor_obj.executed)
