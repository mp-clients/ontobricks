import uuid
from back.objects.actions.base import OverlayEdit
from back.objects.actions.overlay_store import OverlayStore
from tests.units.actions.fakes import FakeConn, FakeCursor


def test_apply_edits_supersedes_then_inserts():
    cur = FakeCursor()
    store = OverlayStore(domain="customers")
    aid = uuid.uuid4()
    store.apply_edits(cur, aid, [OverlayEdit("Customer", "C1", "riskFlag", {"severity": "high"})])
    sql = " ".join(cur.executed).lower()
    assert "update ontology_overlay" in sql and "superseded" in sql
    assert "insert into ontology_overlay" in sql


def test_current_value_returns_active_row_value():
    cur = FakeCursor(rows=[({"severity": "high"},)])
    store = OverlayStore(domain="customers")
    val = store.current_value(cur, "Customer", "C1", "riskFlag")
    assert val == {"severity": "high"}
    assert "status = 'active'" in cur.executed[-1].lower()


def test_current_value_none_when_no_row():
    cur = FakeCursor(rows=[])
    store = OverlayStore(domain="customers")
    assert store.current_value(cur, "Customer", "C1", "riskFlag") is None


def test_apply_edits_supersede_precedes_insert():
    cur = FakeCursor()
    OverlayStore("customers").apply_edits(
        cur, uuid.uuid4(),
        [OverlayEdit("Customer", "C1", "riskFlag", {"severity": "high"})])
    assert "update" in cur.executed[0].lower()   # supersede first
    assert "insert" in cur.executed[1].lower()   # then insert


def test_revert_action_scopes_by_domain_and_action():
    cur = FakeCursor()
    aid = uuid.uuid4()
    OverlayStore("customers").revert_action(cur, aid)
    sql = cur.executed[-1].lower()
    assert "reverted" in sql
    assert "domain=%s" in sql and "action_id=%s" in sql
    assert "status='active'" in sql.replace(" ", "")
    assert cur.params[-1] == ("customers", str(aid))
