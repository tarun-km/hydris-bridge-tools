"""Shared BRIDGE-3 response-model building blocks.

BRIDGE-3's statement is concrete: units on every numeric field, zone
labels on series data, pre-computed deltas where comparison is the
purpose, and disclosed bounding wherever the underlying data volume is
unbounded. These types exist so every tool in tools/ builds its response
out of the same vocabulary instead of re-deciding the shape per tool -
the consistency itself is part of what makes the shape "LLM-oriented"
(the model spends its reasoning on the plant, not on re-learning a new
schema idiom for every call, per docs/scope.md's framing of BRIDGE-3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Three-tier zone vocabulary used for every parameter reading, in bands
# (get_unit_detail) and in time series (get_parameter_history). Kept
# distinct from compliance's "conformance tier" (models/common.py ::
# ConformanceTier) and from alert "severity" - three different domains
# that happen to have a similar shape.
ZoneLabel = Literal["normal", "watch", "alarm"]

ConformanceTier = Literal["compliant", "warning", "exceedance"]

AlertSeverity = Literal["info", "warning", "critical"]

ParameterType = Literal["measured", "derived"]

MeasurementType = Literal["online_sensor", "lab_analysis", "derived"]


class Quantity(BaseModel):
    """A single numeric value paired with its unit (BRIDGE-3 AC-1: no
    numeric field is ever unitless). Used even for dimensionless indices
    (health scores, pH) by giving them an explicit unit label such as
    "index_0_100" or "pH" - the point is that a consumer never has to
    infer what scale a bare number lives on.
    """

    value: float
    unit: str


class SignedDelta(BaseModel):
    """A pre-computed comparison (BRIDGE-3 AC-1: deltas pre-computed where
    comparison is the tool's purpose). `value` is signed: positive means
    an increase versus the reference point named in `reference`.
    """

    value: float
    unit: str
    reference: str


class DateWindow(BaseModel):
    start: str
    end: str


class BoundingDisclosure(BaseModel):
    """BRIDGE-3 AC-2: any tool whose underlying data volume is unbounded
    must return a bounded response and disclose the bounding applied in a
    response field - a silently truncated result is indistinguishable
    from a genuinely short one, and BRIDGE-3's own rationale is that this
    is precisely the failure mode that produces a confidently wrong trend
    read.
    """

    applied: bool
    resolution: Literal["raw", "daily_summary", "weekly_summary"] = "raw"
    requested_window: DateWindow
    returned_window: DateWindow
    returned_points: int
    max_points_per_series: int
    reason: str | None = None


class RecordStatus(BaseModel):
    """BRIDGE-9: `populated=False` marks a category as a blind spot in this
    plant's actual logging behaviour - an empty result then carries no
    information about whether events occurred. `populated=True` with an
    empty result is a real, usable absence: the plant logs this category
    and nothing happened. The flag must come from logging behaviour, not
    from "the query returned zero rows" (see docs/decisions.md).
    """

    category: str
    populated: bool
    records_in_window: int
    window: DateWindow


class ParameterBand(BaseModel):
    """The reference thresholds a raw value is classified against to
    produce a ZoneLabel. Bounds are inclusive on the side named; a None
    bound means that side is unconstrained (e.g. TMP has no meaningful
    lower alarm).
    """

    parameter_code: str
    unit: str
    normal_min: float | None = None
    normal_max: float | None = None
    watch_min: float | None = None
    watch_max: float | None = None
    alarm_min: float | None = None
    alarm_max: float | None = None


def zone_for(value: float, band: ParameterBand) -> ZoneLabel:
    """Deterministic zone classification - the same band always yields the
    same zone for the same value, which is what lets get_current_scores,
    explain_score and get_active_alerts agree with each other and with
    get_parameter_history without recomputing anything.
    """
    if band.alarm_min is not None and value < band.alarm_min:
        return "alarm"
    if band.alarm_max is not None and value > band.alarm_max:
        return "alarm"
    if band.watch_min is not None and value < band.watch_min:
        return "watch"
    if band.watch_max is not None and value > band.watch_max:
        return "watch"
    return "normal"


class InstrumentSummary(BaseModel):
    instrument_id: str
    parameter_code: str
    measurement_type: MeasurementType
