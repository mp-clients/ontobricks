from __future__ import annotations
from typing import Dict
from back.objects.actions.action_type import ActionType


class ActionRegistry:
    """In-memory registry of ActionType instances, keyed by id."""

    def __init__(self) -> None:
        self._types: Dict[str, ActionType] = {}

    def register(self, action_type: ActionType) -> None:
        """Add *action_type* to the registry; raises ValueError if its id is already taken."""
        if action_type.id in self._types:
            raise ValueError(f"Action type already registered: {action_type.id}")
        self._types[action_type.id] = action_type

    def get(self, type_id: str) -> ActionType:
        """Return the ActionType for *type_id*; raises KeyError if not found."""
        if type_id not in self._types:
            raise KeyError(f"Unknown action type: {type_id}")
        return self._types[type_id]

    def ids(self) -> list[str]:
        """Return a sorted list of all registered action type IDs."""
        return sorted(self._types)


# Process-wide default registry. Action type modules register here on import.
default_registry = ActionRegistry()
