"""Deterministic scoring engine, standing in for Lite's real scoring
engines (see docs/scope.md and [PRD] Sec 3.1's "deterministic explanation
of why a score is what it is"). Computes a per-unit health score purely as
a function of the reference bands and parameter series in
services/fixtures.py, so get_current_scores, explain_score and
get_active_alerts can never disagree with each other about the same
underlying data - there is exactly one place a zone becomes a penalty
becomes a score, and it is this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from diagnostic_mcp.models.common import ZoneLabel, zone_for
from diagnostic_mcp.services.fixtures import (
    UNIT_ENGINE,
    get_band,
    get_parameter_series,
    get_unit_record,
)

ENGINE_VERSION = "zone_penalty_engine_v1"

# Deterministic point penalty per zone. Same table, every unit, every
# parameter - the "engine" that differs per unit type (see UNIT_ENGINE) is
# a labelling/attribution concept, not a different scoring formula.
ZONE_PENALTY: dict[ZoneLabel, float] = {"normal": 0.0, "watch": 15.0, "alarm": 35.0}


@dataclass(frozen=True)
class ParameterScoreContribution:
    parameter_code: str
    latest_value: float
    unit: str
    zone: ZoneLabel
    penalty: float


@dataclass(frozen=True)
class UnitScoreResult:
    unit_id: str
    unit_type: str
    engine: str
    as_of: str
    health_score: float
    contributions: tuple[ParameterScoreContribution, ...]
    worst_parameter: str | None


def _value_as_of(series: list[tuple[str, float]], as_of: str) -> float | None:
    """The most recent reading on or before `as_of` - never a future
    reading, so a caller asking "what did we know as of day N" gets
    exactly that."""
    candidates = [(d, v) for d, v in series if d <= as_of]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[0])[1]


def score_unit(factory_id: str, unit_id: str, as_of: str) -> UnitScoreResult | None:
    unit = get_unit_record(factory_id, unit_id)
    if unit is None:
        return None

    contributions: list[ParameterScoreContribution] = []
    for parameter_code in unit.parameter_codes:
        series = get_parameter_series(factory_id, unit_id, parameter_code)
        band = get_band(parameter_code)
        if series is None or band is None:
            continue
        value = _value_as_of(series, as_of)
        if value is None:
            continue
        zone = zone_for(value, band)
        contributions.append(
            ParameterScoreContribution(
                parameter_code=parameter_code,
                latest_value=value,
                unit=band.unit,
                zone=zone,
                penalty=ZONE_PENALTY[zone],
            )
        )

    total_penalty = sum(c.penalty for c in contributions)
    health_score = max(0.0, 100.0 - total_penalty)
    worst = max(contributions, key=lambda c: (c.penalty, c.parameter_code), default=None)

    return UnitScoreResult(
        unit_id=unit.unit_id,
        unit_type=unit.unit_type,
        engine=UNIT_ENGINE.get(unit.unit_type, "generic_scoring_engine"),
        as_of=as_of,
        health_score=health_score,
        contributions=tuple(contributions),
        worst_parameter=worst.parameter_code if worst is not None and worst.penalty > 0 else None,
    )
