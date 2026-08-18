"""Tool 1 of 8 (BRIDGE-1/3/4): factories visible to the caller.

The discovery entry point every other tool assumes has already run: every
other tool in the fifteen-tool surface requires a specific factory_id up
front (BRIDGE-2 AC-1), and this is the only way a caller - human or model,
with no prior integration code - discovers what factory_id values are
even valid for it.

The one deliberate exception to "every tool declares a mandatory factory
scope": see registry/tool_registry.py's `requires_factory_scope` and
docs/decisions.md ("O9") for the full reasoning. Its equivalent
authorization guarantee is enforced here, not skipped: results are always
filtered to the caller's own live grants (ToolContext.grants), fetched
fresh on every call exactly like every other tool's per-call check, and
the service token is never consulted for this decision either.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import get_plant_record


class ListFactoriesArgs(BaseModel):
    """No factory_id: list_factories runs before any one factory is
    chosen (see module docstring). The only tool in this surface with an
    empty argument model."""


class FactorySummary(BaseModel):
    factory_id: str
    name: str
    industry: str


class ListFactoriesResult(BaseModel):
    factories: list[FactorySummary]


async def handle_list_factories(args: ListFactoriesArgs, context: ToolContext) -> dict[str, Any]:
    granted = context.grants.granted_factories(context.user_id)
    factories: list[FactorySummary] = []
    for factory_id in sorted(granted):
        record = get_plant_record(factory_id)
        if record is None:
            # A grant with no backing fixture record is a data-consistency
            # bug (grant store and fixture store have drifted), not
            # something to raise over - it shouldn't hide every other
            # factory this caller can legitimately see.
            continue
        factories.append(
            FactorySummary(
                factory_id=record.factory_id, name=record.name, industry=record.industry
            )
        )
    return ListFactoriesResult(factories=factories).model_dump()


async def list_factories() -> dict[str, Any]:
    """Factories visible to the caller, filtered to their own live grants.

    Call this first, before any other tool: it is the only way to
    discover which factory_id values are valid for this caller, and every
    other tool in the fifteen-tool surface requires one (BRIDGE-2 AC-1).
    Call it once at the start of a session, or again only if you suspect
    grants changed mid-session - not on every turn.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry. Never actually invoked - real dispatch runs
    through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
