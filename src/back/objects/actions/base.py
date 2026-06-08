from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"
    FAILED = "FAILED"


class ApprovalPolicy(str, Enum):
    AUTO = "AUTO"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


@dataclass(frozen=True)
class OverlayEdit:
    """One property edit an Action applies to an object."""
    object_type: str
    object_id: str
    property: str
    value: Dict[str, Any]


@dataclass
class ActionContext:
    """Runtime context for an Action invocation.

    ``connect`` returns a context manager yielding a live Lakebase
    connection (the registry pool's ``connection`` in production, a fake
    in tests).
    """
    domain: str
    actor: str
    actor_kind: str  # 'user' | 'agent'
    connect: Callable[[], Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
