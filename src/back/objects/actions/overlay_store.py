from __future__ import annotations

import json
import uuid
from typing import Any, List, Optional

from back.objects.actions.base import OverlayEdit


class OverlayStore:
    """Authoritative property-edit overlay (Lakebase).

    All methods take an open cursor so they compose inside the
    ActionService transaction. No connection management here.
    """

    def __init__(self, domain: str) -> None:
        self.domain = domain

    def apply_edits(self, cur: Any, action_id: uuid.UUID, edits: List[OverlayEdit]) -> None:
        for e in edits:
            cur.execute(
                "UPDATE ontology_overlay SET status='SUPERSEDED', valid_to=now() "
                "WHERE domain=%s AND object_type=%s AND object_id=%s "
                "AND property=%s AND status='ACTIVE'",
                (self.domain, e.object_type, e.object_id, e.property),
            )
            cur.execute(
                "INSERT INTO ontology_overlay "
                "(domain, object_type, object_id, property, value, action_id, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')",
                (self.domain, e.object_type, e.object_id, e.property,
                 json.dumps(e.value), str(action_id)),
            )

    def current_value(self, cur: Any, object_type: str, object_id: str,
                      prop: str) -> Optional[dict]:
        cur.execute(
            "SELECT value FROM ontology_overlay "
            "WHERE domain=%s AND object_type=%s AND object_id=%s "
            "AND property=%s AND status = 'ACTIVE' "
            "ORDER BY valid_from DESC LIMIT 1",
            (self.domain, object_type, object_id, prop),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def revert_action(self, cur: Any, action_id: uuid.UUID) -> None:
        cur.execute(
            "UPDATE ontology_overlay SET status='REVERTED', valid_to=now() "
            "WHERE domain=%s AND action_id=%s AND status='ACTIVE'",
            (self.domain, str(action_id)),
        )
