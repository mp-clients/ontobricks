import uuid
from back.objects.actions.effects import Effect, EffectRunner, NoopLogEffect
from tests.units.actions.fakes import FakeConn, FakeCursor


def test_noop_log_effect_runs_ok():
    NoopLogEffect().run({"action_id": str(uuid.uuid4())})  # must not raise


def test_runner_marks_done_on_success():
    cur = FakeCursor(rows=[("eff-1", "act-1", "noop_log", {"x": 1})])
    conn = FakeConn(); conn.cursor_obj = cur
    runner = EffectRunner(connect=lambda: conn.ctx(),
                          effects={"noop_log": NoopLogEffect()})
    runner.run_pending()
    flat = " ".join(str(p) for p in cur.params)
    assert "done" in flat.lower()


def test_runner_marks_failed_when_effect_raises():
    class Boom(Effect):
        name = "boom"
        def run(self, payload): raise RuntimeError("nope")
    cur = FakeCursor(rows=[("eff-2", "act-2", "boom", {})])
    conn = FakeConn(); conn.cursor_obj = cur
    runner = EffectRunner(connect=lambda: conn.ctx(), effects={"boom": Boom()})
    runner.run_pending()
    flat = " ".join(str(p) for p in cur.params)
    assert "failed" in flat.lower()
