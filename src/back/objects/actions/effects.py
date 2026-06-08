from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict
from back.core.logging import get_logger
from back.objects.actions.audit import EffectOutbox

logger = get_logger(__name__)


class Effect(ABC):
    """A pluggable outbound effect (Delta sync, SAP connector, notify…).

    This slice ships only NoopLogEffect; real connectors register later
    with no change to ActionService or the outbox."""
    name: str

    @abstractmethod
    def run(self, payload: Dict[str, Any]) -> None:
        ...


class NoopLogEffect(Effect):
    name = "noop_log"

    def run(self, payload: Dict[str, Any]) -> None:
        logger.info("noop_log effect fired: %s", payload)


class EffectRunner:
    """Drains the outbox and runs effects. Failures are isolated to the
    outbox row and never roll back the committed Action."""

    def __init__(self, connect: Callable[[], Any], effects: Dict[str, Effect]):
        self._connect = connect
        self._effects = effects
        self._outbox = EffectOutbox()

    def run_pending(self) -> None:
        """Claim and run all PENDING outbox effects; mark each DONE or FAILED."""
        with self._connect() as conn, conn.cursor() as cur:
            pending = self._outbox.claim_pending(cur)
            for row in pending:
                effect = self._effects.get(row["effect_name"])
                try:
                    if effect is None:
                        raise KeyError(f"no effect registered: {row['effect_name']}")
                    effect.run(row["payload"])
                    self._outbox.mark(cur, row["effect_id"], "DONE")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("effect %s failed: %s", row["effect_name"], exc)
                    self._outbox.mark(cur, row["effect_id"], "FAILED", error=str(exc))
