"""Tool 6 of 8 (BRIDGE-1/3/4/9): time series with zone labels for
measured and derived parameters on one unit.

Three BRIDGE-3/BRIDGE-9 obligations converge on this one tool more than
any other in the W1-8 surface, because it is the one whose underlying
data volume is genuinely unbounded in a real deployment:

1. Every point carries its unit and a zone label (BRIDGE-3 AC-1).
2. Windows longer than MAX_RAW_WINDOW_DAYS are summarised into weekly
   buckets rather than returned raw, and any clipping to the data this
   fixture set actually holds is disclosed in `bounding`, never silently
   truncated (BRIDGE-3 AC-2).
3. A requested parameter_code this unit does not report comes back with
   `record_status.populated=False` - a real, honest "not recorded",
   never indistinguishable from a populated-but-empty series (BRIDGE-9).

See docs/decisions.md for why get_analytics (forthcoming, W2) is the
tool named in the cross-reference below rather than left for W2 to add
unilaterally - TC-BRIDGE-4.2 requires the reference in both directions,
and get_analytics doesn't exist yet to write its own half.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import (
    BoundingDisclosure,
    DateWindow,
    ParameterType,
    RecordStatus,
    ZoneLabel,
    zone_for,
)
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import (
    EARLIEST_DATE,
    FIXTURE_TODAY,
    PARAMETER_TYPE,
    get_band,
    get_parameter_series,
    get_unit_record_or_raise,
)

MAX_RAW_WINDOW_DAYS = 21


class GetParameterHistoryArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )
    unit_id: str = Field(..., min_length=1, description="The unit to fetch parameter history for.")
    start_date: str = Field(..., description="ISO date (YYYY-MM-DD), inclusive.")
    end_date: str = Field(..., description="ISO date (YYYY-MM-DD), inclusive.")
    parameter_codes: list[str] | None = Field(
        None,
        description=(
            "Specific parameter codes to fetch; omit for every parameter this "
            "unit reports (see get_unit_detail)."
        ),
    )


class ParameterPointModel(BaseModel):
    timestamp: str
    value: float
    unit: str
    zone: ZoneLabel


class ParameterSeriesModel(BaseModel):
    parameter_code: str
    parameter_type: ParameterType
    points: list[ParameterPointModel]
    record_status: RecordStatus


class GetParameterHistoryResult(BaseModel):
    factory_id: str
    unit_id: str
    series: list[ParameterSeriesModel]
    bounding: BoundingDisclosure


def _clip_window(start_date: str, end_date: str) -> tuple[date, date, date, date, bool]:
    requested_start = date.fromisoformat(start_date)
    requested_end = date.fromisoformat(end_date)
    if requested_end < requested_start:
        requested_start, requested_end = requested_end, requested_start

    effective_start = max(requested_start, EARLIEST_DATE)
    effective_end = min(requested_end, FIXTURE_TODAY)
    if effective_start > effective_end:
        effective_start = effective_end = FIXTURE_TODAY

    clipped = effective_start != requested_start or effective_end != requested_end
    return requested_start, requested_end, effective_start, effective_end, clipped


def _bucket_weekly(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    buckets: list[list[float]] = []
    bucket_dates: list[str] = []
    for i, (d, v) in enumerate(pairs):
        idx = i // 7
        if idx == len(buckets):
            buckets.append([])
            bucket_dates.append(d)
        buckets[idx].append(v)
        bucket_dates[idx] = d
    return [(bucket_dates[i], round(sum(vals) / len(vals), 2)) for i, vals in enumerate(buckets)]


def _bounding_reason(
    clipped: bool,
    resolution: str,
    requested_start: date,
    requested_end: date,
    effective_start: date,
    effective_end: date,
) -> str | None:
    parts: list[str] = []
    if clipped:
        parts.append(
            f"Requested window {requested_start.isoformat()} to {requested_end.isoformat()} "
            f"exceeds the data this fixture set holds; returned "
            f"{effective_start.isoformat()} to {effective_end.isoformat()} instead."
        )
    if resolution != "raw":
        parts.append(
            f"Window spans more than {MAX_RAW_WINDOW_DAYS} days; points were summarised into "
            f"{resolution.replace('_', ' ')} buckets instead of returned as raw daily readings."
        )
    return " ".join(parts) if parts else None


async def handle_get_parameter_history(
    args: GetParameterHistoryArgs, context: ToolContext
) -> dict[str, Any]:
    unit = get_unit_record_or_raise(args.factory_id, args.unit_id)

    requested_start, requested_end, effective_start, effective_end, clipped = _clip_window(
        args.start_date, args.end_date
    )
    window_days = (effective_end - effective_start).days + 1
    resolution: Literal["raw", "weekly_summary"] = (
        "raw" if window_days <= MAX_RAW_WINDOW_DAYS else "weekly_summary"
    )

    codes = args.parameter_codes if args.parameter_codes is not None else list(unit.parameter_codes)

    series_models: list[ParameterSeriesModel] = []
    total_points = 0
    for code in codes:
        band = get_band(code)
        populated = code in unit.parameter_codes
        raw_series = (
            get_parameter_series(args.factory_id, unit.unit_id, code) if populated else None
        )
        in_window = [
            (d, v)
            for d, v in (raw_series or [])
            if effective_start.isoformat() <= d <= effective_end.isoformat()
        ]

        display_pairs = _bucket_weekly(in_window) if resolution == "weekly_summary" else in_window

        points = (
            [
                ParameterPointModel(timestamp=d, value=v, unit=band.unit, zone=zone_for(v, band))
                for d, v in display_pairs
            ]
            if band is not None
            else []
        )
        total_points += len(points)

        series_models.append(
            ParameterSeriesModel(
                parameter_code=code,
                parameter_type=PARAMETER_TYPE.get(code, "measured"),
                points=points,
                record_status=RecordStatus(
                    category=code,
                    populated=populated,
                    records_in_window=len(in_window),
                    window=DateWindow(
                        start=effective_start.isoformat(), end=effective_end.isoformat()
                    ),
                ),
            )
        )

    bounding = BoundingDisclosure(
        applied=clipped or resolution != "raw",
        resolution=resolution,
        requested_window=DateWindow(
            start=requested_start.isoformat(), end=requested_end.isoformat()
        ),
        returned_window=DateWindow(
            start=effective_start.isoformat(), end=effective_end.isoformat()
        ),
        returned_points=total_points,
        max_points_per_series=MAX_RAW_WINDOW_DAYS,
        reason=_bounding_reason(
            clipped, resolution, requested_start, requested_end, effective_start, effective_end
        ),
    )

    return GetParameterHistoryResult(
        factory_id=args.factory_id,
        unit_id=unit.unit_id,
        series=series_models,
        bounding=bounding,
    ).model_dump()


async def get_parameter_history(
    factory_id: str,
    unit_id: str,
    start_date: str,
    end_date: str,
    parameter_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Timestamped values with zone labels for one or more measured or
    derived parameters on one unit, over an explicit date window.

    Use this when you need the actual values themselves - to see exactly
    when a parameter crossed a zone boundary, to eyeball a specific
    excursion get_current_scores or get_active_alerts pointed you at, or
    to compare measured against derived parameters directly. For
    aggregate trend statistics, variability, correlations, or removal-
    efficiency summaries over a window, prefer get_analytics instead (a
    Work Item 2 tool; use get_parameter_history in the meantime and
    switch once get_analytics ships) - it is the right choice when you
    want a summary of the trend rather than the points that make it up.

    Requesting a parameter_code this unit does not actually report (check
    get_unit_detail first if unsure) returns an honestly empty,
    `record_status.populated=false` series rather than a silent zero
    (BRIDGE-9) - that is a real "not recorded", not "recorded as none".
    Windows longer than 21 days are summarised into weekly buckets rather
    than returned raw, and any clipping to the data actually held is
    disclosed in the `bounding` field, never silently truncated
    (BRIDGE-3 AC-2).

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
