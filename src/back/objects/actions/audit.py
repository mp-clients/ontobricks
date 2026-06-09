from __future__ import annotations
import json
import uuid
from typing import Any, Optional


class AuditLog:
    """Immutable-ish action_log writer (status transitions are updates)."""

    def insert_proposed(self, cur: Any, *, action_type: str, domain: str,
                        object_type: str, object_id: str, params: dict,
                        actor: str, actor_kind: str,
                        parent_action_id: Optional[uuid.UUID] = None) -> uuid.UUID:
        """Insert a new action_log row with status PROPOSED and return its UUID."""
        aid = uuid.uuid4()
        cur.execute(
            "INSERT INTO action_log (action_id, action_type, domain, object_type, "
            "object_id, params, actor, actor_kind, status, parent_action_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (str(aid), action_type, domain, object_type, object_id,
             json.dumps(params), actor, actor_kind, "PROPOSED",
             str(parent_action_id) if parent_action_id else None),
        )
        return aid

    def mark(self, cur: Any, action_id: uuid.UUID, status: str, *,
             approved_by: Optional[str] = None, before: Optional[dict] = None,
             after: Optional[dict] = None) -> None:
        """Transition an action_log row to *status*, optionally recording provenance."""
        cur.execute(
            "UPDATE action_log SET status=%s, approved_by=COALESCE(%s, approved_by), "
            "before=COALESCE(%s, before), after=COALESCE(%s, after), "
            "applied_at=CASE WHEN %s='APPLIED' THEN now() ELSE applied_at END "
            "WHERE action_id=%s",
            (status, approved_by,
             json.dumps(before) if before is not None else None,
             json.dumps(after) if after is not None else None,
             status, str(action_id)),
        )

    def get(self, cur: Any, action_id: uuid.UUID) -> Optional[dict]:
        """Fetch a single action_log row by UUID, or None if not found."""
        cur.execute(
            "SELECT action_type, domain, object_type, object_id, params, status, actor "
            "FROM action_log WHERE action_id=%s", (str(action_id),))
        row = cur.fetchone()
        if not row:
            return None
        return {"action_type": row[0], "domain": row[1], "object_type": row[2],
                "object_id": row[3], "params": row[4], "status": row[5], "actor": row[6]}


class EffectOutbox:
    """Pending external effects (seam; no live connector in this slice)."""

    def enqueue(self, cur: Any, action_id: uuid.UUID, name: str, payload: dict) -> None:
        """Insert a PENDING outbox row for a named effect with its JSON payload."""
        cur.execute(
            "INSERT INTO action_effects_outbox "
            "(effect_id, action_id, effect_name, payload, status) "
            "VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), str(action_id), name, json.dumps(payload), "PENDING"),
        )

    def claim_pending(self, cur: Any, limit: int = 20) -> list[dict]:
        """Return up to *limit* PENDING outbox rows ordered by next_attempt_at."""
        cur.execute(
            "SELECT effect_id, action_id, effect_name, payload FROM action_effects_outbox "
            "WHERE status='PENDING' AND next_attempt_at <= now() "
            "ORDER BY next_attempt_at LIMIT %s", (limit,))
        return [{"effect_id": r[0], "action_id": r[1], "effect_name": r[2],
                 "payload": r[3]} for r in cur.fetchall()]

    def mark(self, cur: Any, effect_id: Any, status: str, error: Optional[str] = None) -> None:
        """Update an outbox row's status and increment its attempt counter."""
        cur.execute(
            "UPDATE action_effects_outbox SET status=%s, attempts=attempts+1, "
            "last_error=%s WHERE effect_id=%s",
            (status, error, str(effect_id)),
        )
