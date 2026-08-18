"""Tool 5 of 8 (BRIDGE-1/3/4): deterministic, parameter-by-parameter
breakdown of why one unit's health score is what it is.

Walks the exact same parameters, bands and penalties
get_current_scores/services/scoring.py used to produce the score - the
two tools can never disagree, only differ in how much of the "why" is
shown.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import ParameterBand, Quantity, ZoneLabel
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import get_band, get_unit_record_or_raise, resolve_as_of
from diagnostic_mcp.services.scoring import score_unit


class GetExplainScoreArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )
    unit_id: str = Field(..., min_length=1, description="The unit whose score to explain.")
    as_of_date: str | None = Field(
        None,
        description="ISO date to explain as of; defaults to the latest date this fixture holds.",
    )


class ScoreBreakdownStep(BaseModel):
    parameter_code: str
    latest_value: Quantity
    zone: ZoneLabel
    band: ParameterBand
    penalty: Quantity
    rationale: str


class ExplainScoreResult(BaseModel):
    factory_id: str
    unit_id: str
    as_of: str
    engine: str
    baseline_score: Quantity
    health_score: Quantity
    worst_parameter: str | None
    steps: list[ScoreBreakdownStep]


def _rationale(parameter_code: str, value: float, unit: str, zone: ZoneLabel) -> str:
    if zone == "normal":
        return f"{parameter_code} is {value} {unit}, within its normal band; no penalty."
    if zone == "watch":
        return (
            f"{parameter_code} is {value} {unit}, outside its normal band and inside "
            "its watch band; a watch-tier penalty was applied."
        )
    return (
        f"{parameter_code} is {value} {unit}, inside its alarm band; an alarm-tier "
        "penalty was applied, the heaviest tier this engine assigns."
    )


async def handle_explain_score(args: GetExplainScoreArgs, context: ToolContext) -> dict[str, Any]:
    get_unit_record_or_raise(args.factory_id, args.unit_id)

    as_of = resolve_as_of(args.as_of_date)
    result = score_unit(args.factory_id, args.unit_id, as_of)
    if result is None:
        raise LookupError(f"No score available for unit {args.unit_id!r} as of {as_of!r}.")

    steps: list[ScoreBreakdownStep] = []
    for c in result.contributions:
        band = get_band(c.parameter_code)
        if band is None:
            continue
        steps.append(
            ScoreBreakdownStep(
                parameter_code=c.parameter_code,
                latest_value=Quantity(value=c.latest_value, unit=c.unit),
                zone=c.zone,
                band=band,
                penalty=Quantity(value=c.penalty, unit="index_0_100"),
                rationale=_rationale(c.parameter_code, c.latest_value, c.unit, c.zone),
            )
        )

    return ExplainScoreResult(
        factory_id=args.factory_id,
        unit_id=args.unit_id,
        as_of=as_of,
        engine=result.engine,
        baseline_score=Quantity(value=100.0, unit="index_0_100"),
        health_score=Quantity(value=result.health_score, unit="index_0_100"),
        worst_parameter=result.worst_parameter,
        steps=steps,
    ).model_dump()


async def explain_score(
    factory_id: str, unit_id: str, as_of_date: str | None = None
) -> dict[str, Any]:
    """Deterministic, parameter-by-parameter breakdown of why one unit's
    health score is what it is: every contributing parameter, the zone it
    was in, the penalty it added, and a one-line rationale per step.

    Call this after get_current_scores has told you *that* a unit scored
    poorly, when you need the "why" instead of just the number - the
    baseline is always 100 (index_0_100), and each step shows exactly how
    much was deducted and for which parameter, using the same bands
    get_unit_detail describes. For that parameter's actual values over
    time, rather than just its zone at this one instant, use
    get_parameter_history next.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
