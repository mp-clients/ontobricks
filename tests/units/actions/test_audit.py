import uuid
from back.objects.actions.audit import AuditLog, EffectOutbox
from tests.units.actions.fakes import FakeCursor

def test_insert_proposed_writes_row_and_returns_uuid():
    cur = FakeCursor()
    aid = AuditLog().insert_proposed(
        cur, action_type="flag_customer_high_risk", domain="customers",
        object_type="Customer", object_id="C1", params={"severity": "high"},
        actor="jerry@moneypool.mx", actor_kind="user")
    assert isinstance(aid, uuid.UUID)
    assert "insert into action_log" in cur.executed[0].lower()
    assert "proposed" in " ".join(str(p) for p in cur.params[0]).lower()

def test_mark_updates_status():
    cur = FakeCursor()
    aid = uuid.uuid4()
    AuditLog().mark(cur, aid, "APPLIED", after={"riskFlag": {"severity": "high"}})
    assert "update action_log set status" in cur.executed[0].lower()

def test_enqueue_effect_inserts_pending():
    cur = FakeCursor()
    EffectOutbox().enqueue(cur, uuid.uuid4(), "noop_log", {"k": "v"})
    sql = cur.executed[0].lower()
    assert "insert into action_effects_outbox" in sql
    assert "pending" in " ".join(str(p) for p in cur.params[0]).lower()
