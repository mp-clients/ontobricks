from back.objects.actions.schema import ensure_schema
from tests.units.actions.fakes import FakeConn

def test_ensure_schema_runs_ddl_idempotently():
    conn = FakeConn()
    ensure_schema(lambda: conn.ctx())
    executed = " ".join(conn.cursor_obj.executed).lower()
    assert "create table if not exists action_log" in executed
    assert "create table if not exists ontology_overlay" in executed
    assert "create table if not exists action_effects_outbox" in executed
