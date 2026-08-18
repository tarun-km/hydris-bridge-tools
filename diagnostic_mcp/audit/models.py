"""BRIDGE-5: one audit record per call, whatever the outcome."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

Outcome = Literal["success", "rejected", "error"]


class AuditRecord(BaseModel):
    """The six mandated fields (BRIDGE-5 statement) are pulse_session_id,
    user_id, factory_id, tool_name, arguments and latency_ms. outcome rides
    alongside as the field AC-2 requires on every rejected call.

    user_id / factory_id may be None: an authentication failure can occur
    before either identity is resolved, and factory_id is None on
    principle for factory-scope-exempt tools (list_factories) even on
    success - the record must still be written (BRIDGE-5 AC-2) rather than
    skipped for lack of a value.
    """

    pulse_session_id: str
    user_id: str | None
    factory_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    outcome: Outcome
    latency_ms: float
    timestamp: float = Field(default_factory=time.time)
    detail: str | None = None
