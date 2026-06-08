"""Kinetic Action layer — typed, validated, audited, reversible Actions
that mutate ontology state through a single ActionService seam.

Action Types are code-registered today (see ``registry``); the registry is
designed to later load definitions from ontology metadata (north-star B)
without changing ActionService, the overlay, the audit log, or effects.
"""

from typing import Any, Callable
from back.objects.actions.schema import ensure_schema
from back.objects.actions.registry import default_registry
from back.objects.actions.service import ActionService
import back.objects.actions.types  # noqa: F401  (registers action types)

_schema_ready = False


def build_action_service(connect: Callable[[], Any]) -> ActionService:
    """Return an ActionService bound to a Lakebase connection provider,
    ensuring the kinetic tables exist (once per process)."""
    global _schema_ready
    if not _schema_ready:
        ensure_schema(connect)
        _schema_ready = True
    return ActionService(registry=default_registry, connect=connect)
