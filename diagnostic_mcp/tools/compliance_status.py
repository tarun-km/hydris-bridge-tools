"""Tool 8 of 8 (BRIDGE-1/3/4): permit limits versus recent effluent,
exceedances and conformance tier for one factory.

The final stop on the discovery-to-detail arc ([RSD] Part E's own framing
for the W1-8 tool set): find the factory, understand its shape, see its
current state, understand why, look at behaviour over time, see what
fired, check compliance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from diagnostic_mcp.models.common import ConformanceTier, DateWindow, Quantity, SignedDelta
from diagnostic_mcp.registry.pipeline import ToolContext
from diagnostic_mcp.services.fixtures import (
    COMPLIANCE_LIMITS,
    DATES_7,
    EFFLUENT_READINGS,
    get_plant_record_or_raise,
)

# Same margin semantics used for every parameter: recent_value strictly
# over the limit is an exceedance; inside 10% of the limit (but not over
# it) is a warning; otherwise compliant. One rule, applied uniformly, so
# overall_tier can be derived by taking the worst of the per-parameter
# tiers rather than a second, potentially inconsistent judgement call.
_TIER_ORDER: dict[ConformanceTier, int] = {"compliant": 0, "warning": 1, "exceedance": 2}


def _tier_for(recent_value: float, limit_value: float) -> ConformanceTier:
    if recent_value > limit_value:
        return "exceedance"
    if recent_value > 0.9 * limit_value:
        return "warning"
    return "compliant"


class GetComplianceStatusArgs(BaseModel):
    factory_id: str = Field(
        ..., min_length=1, description="Mandatory factory scope (BRIDGE-2 AC-1)."
    )


class ComplianceLimitModel(BaseModel):
    parameter_code: str
    limit: Quantity
    recent_value: Quantity
    margin: SignedDelta
    tier: ConformanceTier


class GetComplianceStatusResult(BaseModel):
    factory_id: str
    window: DateWindow
    limits: list[ComplianceLimitModel]
    overall_tier: ConformanceTier


async def handle_get_compliance_status(
    args: GetComplianceStatusArgs, context: ToolContext
) -> dict[str, Any]:
    get_plant_record_or_raise(args.factory_id)

    limit_records = COMPLIANCE_LIMITS.get(args.factory_id, [])
    limits: list[ComplianceLimitModel] = []
    for limit_record in limit_records:
        readings = EFFLUENT_READINGS.get((args.factory_id, limit_record.parameter_code), [])
        if not readings:
            # A declared permit limit with zero recorded effluent readings
            # is a data-consistency bug (the limit and reading fixtures
            # have drifted), not something to drop silently - a silent
            # `continue` here would understate overall_tier by quietly
            # excluding a parameter that might be the exceedance.
            raise LookupError(
                f"No effluent readings for parameter_code={limit_record.parameter_code!r} "
                f"on factory_id={args.factory_id!r}, despite a declared compliance limit."
            )
        recent_value = readings[-1][1]
        tier = _tier_for(recent_value, limit_record.limit_value)
        limits.append(
            ComplianceLimitModel(
                parameter_code=limit_record.parameter_code,
                limit=Quantity(value=limit_record.limit_value, unit=limit_record.unit),
                recent_value=Quantity(value=recent_value, unit=limit_record.unit),
                margin=SignedDelta(
                    value=round(limit_record.limit_value - recent_value, 2),
                    unit=limit_record.unit,
                    reference="permit_limit",
                ),
                tier=tier,
            )
        )

    overall_tier: ConformanceTier = max(
        (limit.tier for limit in limits), key=lambda t: _TIER_ORDER[t], default="compliant"
    )

    return GetComplianceStatusResult(
        factory_id=args.factory_id,
        window=DateWindow(start=DATES_7[0], end=DATES_7[-1]),
        limits=limits,
        overall_tier=overall_tier,
    ).model_dump()


async def get_compliance_status(factory_id: str) -> dict[str, Any]:
    """Permit limits versus recent effluent readings for one factory, with
    a pre-computed margin per parameter and an overall conformance tier.

    Use this to check regulatory standing directly, or once
    get_active_alerts or explain_score has surfaced a process issue that
    might be affecting effluent quality - an exceedance here that lines up
    in time with a fired alert or a degraded score is a strong signal they
    share a root cause rather than being coincidental. margin is signed
    (limit minus recent_value): positive is headroom, negative is by how
    much the limit was exceeded. For the effluent parameter's own values
    over a longer window instead of just the most recent reading, use
    get_parameter_history.

    Schema-only signature: FastMCP introspects this to build the
    `tools/list` entry (factory_id required, per BRIDGE-2 AC-1). Never
    actually invoked - real dispatch runs through registry/pipeline.py.
    """
    raise NotImplementedError("schema-only stub; see registry/pipeline.py")
