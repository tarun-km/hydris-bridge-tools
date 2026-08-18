"""Tool 7 of 8 (BRIDGE-1/3/4): alerts, fired rules and deterministic
root-cause hints for one factory.

The root-cause hints here are Lite's own rule-engine output - deterministic
and pre-existing, not the diagnostic reasoning Pulse itself performs. They
are a starting hypothesis, not a conclusion (see [PRD] Part A: Lite tells
a plant *what* is wrong, never *why* - Pulse's job starts here, it doesn't
end here).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import AlertSeverity, Quantity
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import FIXTURE_TODAY, get_alerts, get_plant_record_or_raise


class GetActiveAlertsArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )
    include_resolved: bool = Field(
        False,
        description="Include resolved alerts as well as active ones. Defaults to active only.",
    )


class AlertModel(BaseModel):
    alert_id: str
    unit_id: str | None
    parameter_code: str | None
    rule_name: str
    severity: AlertSeverity
    fired_at: str
    status: str
    root_cause_hint: str
    trigger_value: Quantity | None


class GetActiveAlertsResult(BaseModel):
    factory_id: str
    as_of: str
    alerts: list[AlertModel]


async def handle_get_active_alerts(
    args: GetActiveAlertsArgs, context: ToolContext
) -> dict[str, Any]:
    get_plant_record_or_raise(args.factory_id)

    records = get_alerts(args.factory_id)
    if not args.include_resolved:
        records = [r for r in records if r.status == "active"]

    alerts = [
        AlertModel(
            alert_id=r.alert_id,
            unit_id=r.unit_id,
            parameter_code=r.parameter_code,
            rule_name=r.rule_name,
            severity=r.severity,
            fired_at=r.fired_at,
            status=r.status,
            root_cause_hint=r.root_cause_hint,
            trigger_value=(
                Quantity(value=r.trigger_value, unit=r.trigger_unit)
                if r.trigger_value is not None and r.trigger_unit is not None
                else None
            ),
        )
        for r in records
    ]

    return GetActiveAlertsResult(
        factory_id=args.factory_id,
        as_of=FIXTURE_TODAY.isoformat(),
        alerts=alerts,
    ).model_dump()


async def get_active_alerts(
    factory_id: str, include_resolved: bool = False
) -> dict[str, Any]:
    """Alerts fired by Lite's rule engine for one factory, with the rule
    name, severity, the parameter and unit that triggered it, and Lite's
    own deterministic root-cause hint.

    Use this to find out what Lite's rules have already flagged before
    starting a diagnostic session - it is frequently the fastest way to
    the same parameter get_current_scores' worst_parameter or
    explain_score's steps point at, from the opposite direction (a fired
    rule rather than a low score). The root_cause_hint is Lite's own
    deterministic guess, a starting hypothesis to weigh, not a verified
    conclusion. For operational context around the same time window
    (dosing changes, downtime, sludge operations), use get_recent_events
    (a Work Item 2 tool) once available.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
