"""Tool 2 of 8 (BRIDGE-1/3/4): identity, industry, treatment train, unit
flow relationships and snapshot version for one factory.

This supersedes the Work Item 1 demonstration version of this tool (see
the W1 skeleton's docs/scope.md, which explicitly flagged its own
`get_plant_overview` as non-compliant with BRIDGE-3/4 and deferred the
real implementation here). The response now carries flow relationships
(D1/D2: Pulse must see the train's shape, not just a unit list) and a
reviewed when-to-use description.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import get_plant_record_or_raise


class GetPlantOverviewArgs(BaseModel):
    factory_id: str = Field(
        ...,
        min_length=1,
        description="The factory to look up. Mandatory factory scope (BRIDGE-2 AC-1).",
    )


class UnitSummaryModel(BaseModel):
    unit_id: str
    unit_type: str
    process_qualifiers: list[str]


class FlowEdgeModel(BaseModel):
    from_unit_id: str
    to_unit_id: str


class GetPlantOverviewResult(BaseModel):
    factory_id: str
    name: str
    industry: str
    units: list[UnitSummaryModel]
    flow: list[FlowEdgeModel]
    snapshot_version: str


async def handle_get_plant_overview(
    args: GetPlantOverviewArgs, context: ToolContext
) -> dict[str, Any]:
    record = get_plant_record_or_raise(args.factory_id)

    return GetPlantOverviewResult(
        factory_id=record.factory_id,
        name=record.name,
        industry=record.industry,
        units=[
            UnitSummaryModel(
                unit_id=u.unit_id,
                unit_type=u.unit_type,
                process_qualifiers=list(u.process_qualifiers),
            )
            for u in record.units
        ],
        flow=[
            FlowEdgeModel(from_unit_id=e.from_unit_id, to_unit_id=e.to_unit_id)
            for e in record.flow
        ],
        snapshot_version=record.snapshot_version,
    ).model_dump()


async def get_plant_overview(factory_id: str) -> dict[str, Any]:
    """Identity, industry, treatment-train units, unit flow relationships
    and snapshot version for one factory.

    Use this first for any factory you have not yet examined this
    session, right after list_factories - it is how you learn the
    factory's shape (what units exist and how they connect) before
    drilling into any one unit. For per-unit detail (geometry,
    instruments, per-parameter ranges) call get_unit_detail next, once
    you know which unit_id you care about. For the plant's current
    condition rather than its static shape, use get_current_scores or
    get_active_alerts instead.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
