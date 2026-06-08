import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("LAKEBASE_TEST_CONNECT"),
    reason="requires live Lakebase (set LAKEBASE_TEST_CONNECT=1 + app env)",
)


def test_propose_approve_applies_and_reads_back():
    from back.objects.actions import build_action_service
    from back.objects.actions.base import ActionContext
    from back.objects.actions.overlay_store import OverlayStore
    from tests.integration.actions.conftest import test_connect  # provides connect()

    svc = build_action_service(test_connect)
    cid = f"itest-{uuid.uuid4().hex[:8]}"
    ctx = ActionContext(
        domain="customers",
        actor="itest",
        actor_kind="user",
        connect=test_connect,
    )
    r = svc.propose(
        "flag_customer_high_risk",
        cid,
        {"customer_id": cid, "severity": "high", "reason": "sanctions"},
        ctx,
    )
    assert r.status == "PROPOSED"
    r2 = svc.approve(r.action_id, "approver@x", ctx)
    assert r2.status == "APPLIED"
    with test_connect() as conn, conn.cursor() as cur:
        assert (
            OverlayStore("customers").current_value(
                cur, "Customer", cid, "riskFlag"
            )["severity"]
            == "high"
        )
