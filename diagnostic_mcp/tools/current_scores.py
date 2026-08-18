"""Tool 4 of 8 (BRIDGE-1/3/4): daily per-unit health scores, worst-
performing engines and parameters, for one factory.

Scores come from services/scoring.py, the same deterministic engine
explain_score walks step by step - the two tools can never disagree about
what a unit's score is, only about how much detail is shown.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import Quantity, SignedDelta, ZoneLabel
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import (
    EARLIEST_DATE,
    get_plant_record_or_raise,
    resolve_as_of,
)
from diagnostic_mcp.services.scoring import score_unit


class GetCurrentScoresArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )
    as_of_date: str | None = Field(
        None,
        description=(
            "ISO date (YYYY-MM-DD) to score as of; defaults to the latest "
            "date this fixture set holds."
        ),
    )


class ParameterContributionModel(BaseModel):
    parameter_code: str
    latest_value: Quantity
    zone: ZoneLabel
    penalty: Quantity


class UnitScoreModel(BaseModel):
    unit_id: str
    unit_type: str
    engine: str
    health_score: Quantity
    health_score_delta: SignedDelta
    worst_parameter: str | None
    contributions: list[ParameterContributionModel]


class GetCurrentScoresResult(BaseModel):
    factory_id: str
    as_of: str
    units: list[UnitScoreModel]
    worst_unit_id: str | None
    worst_engine: str | None


async def handle_get_current_scores(
    args: GetCurrentScoresArgs, context: ToolContext
) -> dict[str, Any]:
    record = get_plant_record_or_raise(args.factory_id)

    as_of = resolve_as_of(args.as_of_date)
    as_of_date = date.fromisoformat(as_of)
    previous_date = as_of_date - timedelta(days=1)
    # This fixture set's history starts at EARLIEST_DATE; a score requested
    # for that first day has no prior day to compare against, so the delta
    # is reported as zero against itself rather than fabricating a
    # comparison point that was never observed.
    previous = previous_date.isoformat() if previous_date >= EARLIEST_DATE else as_of

    unit_scores: list[UnitScoreModel] = []
    for unit in record.units:
        current = score_unit(args.factory_id, unit.unit_id, as_of)
        if current is None:
            continue
        prior = score_unit(args.factory_id, unit.unit_id, previous)
        prior_score = prior.health_score if prior is not None else current.health_score

        unit_scores.append(
            UnitScoreModel(
                unit_id=current.unit_id,
                unit_type=current.unit_type,
                engine=current.engine,
                health_score=Quantity(value=current.health_score, unit="index_0_100"),
                health_score_delta=SignedDelta(
                    value=round(current.health_score - prior_score, 1),
                    unit="index_0_100",
                    reference="previous_day",
                ),
                worst_parameter=current.worst_parameter,
                contributions=[
                    ParameterContributionModel(
                        parameter_code=c.parameter_code,
                        latest_value=Quantity(value=c.latest_value, unit=c.unit),
                        zone=c.zone,
                        penalty=Quantity(value=c.penalty, unit="index_0_100"),
                    )
                    for c in current.contributions
                ],
            )
        )

    worst = min(unit_scores, key=lambda u: u.health_score.value, default=None)

    return GetCurrentScoresResult(
        factory_id=args.factory_id,
        as_of=as_of,
        units=unit_scores,
        worst_unit_id=worst.unit_id if worst is not None else None,
        worst_engine=worst.engine if worst is not None else None,
    ).model_dump()


async def get_current_scores(factory_id: str, as_of_date: str | None = None) -> dict[str, Any]:
    """Daily per-unit health scores for one factory: which engine scored
    each unit, the worst-performing parameter behind each score, and the
    pre-computed change since the previous day.

    Use this to get the plant's current condition at a glance, and to find
    which unit and parameter need attention first (worst_unit_id /
    worst_engine). It tells you *that* a unit is underperforming and by
    how much it changed; it does not explain the "why" step by step - for
    a deterministic breakdown of exactly which parameters and zones
    produced a given unit's score, call explain_score next with that
    unit_id. For the parameter's own values over time rather than just its
    current zone, use get_parameter_history.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
