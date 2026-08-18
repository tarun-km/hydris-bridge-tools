"""Tool 3 of 8 (BRIDGE-1/3/4): unit type, process qualifiers, geometry,
instruments and per-parameter reference bands for one unit.

The bands returned here are the exact same ParameterBand records
get_current_scores, explain_score and get_parameter_history use to
classify a raw value into a zone (services/fixtures.py::PARAMETER_BANDS)
- so a caller can see *why* a zone label means what it means, not just
that it was assigned.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import InstrumentSummary, ParameterBand, Quantity
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import get_band, get_unit_record_or_raise


class GetUnitDetailArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )
    unit_id: str = Field(..., min_length=1, description="The unit within that factory to look up.")


class UnitGeometryModel(BaseModel):
    volume: Quantity | None
    membrane_area: Quantity | None = None


class GetUnitDetailResult(BaseModel):
    factory_id: str
    unit_id: str
    unit_type: str
    process_qualifiers: list[str]
    geometry: UnitGeometryModel
    instruments: list[InstrumentSummary]
    parameter_bands: list[ParameterBand]


async def handle_get_unit_detail(args: GetUnitDetailArgs, context: ToolContext) -> dict[str, Any]:
    unit = get_unit_record_or_raise(args.factory_id, args.unit_id)

    geometry = UnitGeometryModel(
        volume=Quantity(value=unit.geometry.volume_m3, unit="m3")
        if unit.geometry.volume_m3 is not None
        else None,
        membrane_area=Quantity(value=unit.geometry.membrane_area_m2, unit="m2")
        if unit.geometry.membrane_area_m2 is not None
        else None,
    )
    instruments = [
        InstrumentSummary(
            instrument_id=i.instrument_id,
            parameter_code=i.parameter_code,
            measurement_type=i.measurement_type,
        )
        for i in unit.instruments
    ]
    bands = [get_band(code) for code in unit.parameter_codes]

    return GetUnitDetailResult(
        factory_id=args.factory_id,
        unit_id=unit.unit_id,
        unit_type=unit.unit_type,
        process_qualifiers=list(unit.process_qualifiers),
        geometry=geometry,
        instruments=instruments,
        parameter_bands=[b for b in bands if b is not None],
    ).model_dump()


async def get_unit_detail(factory_id: str, unit_id: str) -> dict[str, Any]:
    """Unit type, process qualifiers, geometry, instrument registry and
    per-parameter reference bands (normal/watch/alarm thresholds) for one
    unit.

    Use this after get_plant_overview, once you know which unit_id you
    care about, to learn what "normal" means for each parameter that unit
    reports before you look at its current or historical values - the
    bands here are exactly what get_current_scores, explain_score and
    get_parameter_history use to assign a zone label, so reading this
    first makes those zone labels legible rather than opaque. For the
    unit's current condition use get_current_scores or explain_score; for
    its behaviour over time use get_parameter_history.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
