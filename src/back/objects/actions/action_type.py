from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Tuple, Type
from pydantic import BaseModel
from back.objects.actions.base import ActionContext, ApprovalPolicy, OverlayEdit


class ActionType(ABC):
    """Declarative definition of one kind of Action.

    Subclasses set the class attributes and implement validate/apply/effects.
    The registry stores instances; future work can synthesize ActionType
    instances from ontology metadata (north-star B) with no consumer changes.
    """
    id: str
    object_type: str
    approval_policy: ApprovalPolicy
    params_model: Type[BaseModel]
    # Property names this Action writes on `object_type`, exposed as
    # overlay-backed read-back fields on the GraphQL type. Default empty.
    overlay_fields: List[str] = []

    @abstractmethod
    def validate(self, ctx: ActionContext, params: BaseModel) -> List[str]:
        """Return a list of human-readable precondition errors ([] = ok)."""

    @abstractmethod
    def apply(self, ctx: ActionContext, params: BaseModel) -> List[OverlayEdit]:
        """Return the overlay edits this action applies (no I/O here)."""

    @abstractmethod
    def effects(self, params: BaseModel) -> List[Tuple[str, dict]]:
        """Return (effect_name, payload) pairs to enqueue post-commit."""
