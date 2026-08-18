"""Builds the Diagnostic MCP server.

FastMCP is used only for `tools/list` schema advertisement (`add_tool`
with a schema-only stub per tool, see tools/*.py). All actual dispatch for
`tools/call` goes through one override registered directly on the
underlying low-level server, which runs every call through
registry/pipeline.py - the single place BRIDGE-2, BRIDGE-5 and NFR-4 are
enforced. This split exists so the safety-critical logic never depends on
FastMCP's own per-tool argument binding (see docs/decisions.md, inherited
unchanged from the Work Item 1 skeleton).

Designed to be dropped into lite/diagnostic_mcp/ in the Lite monorepo -
see docs/scope.md for exactly what changes at that point.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from diagnostic_mcp.audit.sink import AuditSink, FileAuditSink
from diagnostic_mcp.config import Settings
from diagnostic_mcp.registry.pipeline import run_tool_call
from diagnostic_mcp.registry.tool_registry import ToolRegistry, ToolSpec
from diagnostic_mcp.services.grants import GrantStore, seeded_grant_store
from diagnostic_mcp.tools.active_alerts import (
    GetActiveAlertsArgs,
    get_active_alerts,
    handle_get_active_alerts,
)
from diagnostic_mcp.tools.compliance_status import (
    GetComplianceStatusArgs,
    get_compliance_status,
    handle_get_compliance_status,
)
from diagnostic_mcp.tools.current_scores import (
    GetCurrentScoresArgs,
    get_current_scores,
    handle_get_current_scores,
)
from diagnostic_mcp.tools.explain_score import (
    GetExplainScoreArgs,
    explain_score,
    handle_explain_score,
)
from diagnostic_mcp.tools.list_factories import (
    ListFactoriesArgs,
    handle_list_factories,
    list_factories,
)
from diagnostic_mcp.tools.parameter_history import (
    GetParameterHistoryArgs,
    get_parameter_history,
    handle_get_parameter_history,
)
from diagnostic_mcp.tools.plant_overview import (
    GetPlantOverviewArgs,
    get_plant_overview,
    handle_get_plant_overview,
)
from diagnostic_mcp.tools.unit_detail import (
    GetUnitDetailArgs,
    get_unit_detail,
    handle_get_unit_detail,
)

logger = logging.getLogger("diagnostic_mcp.server")

# BRIDGE-6: the toolset version. Bumped from Work Item 1's 0.1.0 for an
# additive change - tools 1-8 (BRIDGE-1/3/4) added, nothing removed or
# reshaped for the one tool (get_plant_overview) both work items touch.
# See docs/decisions.md, O5.
TOOLSET_VERSION = "0.2.0"


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    # O9: the one tool exempt from the mandatory single-factory-scope
    # gate - see registry/tool_registry.py and docs/decisions.md.
    registry.register(
        ToolSpec(
            name="list_factories",
            description=(
                "Factories visible to the caller, filtered to their own live "
                "grants. Call this first, before any other tool: it is the "
                "only way to discover which factory_id values are valid for "
                "this caller, and every other tool in the fifteen-tool "
                "surface requires one (BRIDGE-2 AC-1). Call it once at the "
                "start of a session, or again only if you suspect grants "
                "changed - not on every turn."
            ),
            argument_model=ListFactoriesArgs,
            handler=handle_list_factories,
            schema_fn=list_factories,
            requires_factory_scope=False,
        )
    )
    registry.register(
        ToolSpec(
            name="get_plant_overview",
            description=(
                "Identity, industry, treatment-train units, unit flow "
                "relationships and snapshot version for one factory. Use "
                "this first for any factory you have not yet examined this "
                "session, right after list_factories - it is how you learn "
                "the factory's shape before drilling into any one unit. For "
                "per-unit detail call get_unit_detail next. For current "
                "condition rather than static shape, use get_current_scores "
                "or get_active_alerts instead."
            ),
            argument_model=GetPlantOverviewArgs,
            handler=handle_get_plant_overview,
            schema_fn=get_plant_overview,
        )
    )
    registry.register(
        ToolSpec(
            name="get_unit_detail",
            description=(
                "Unit type, process qualifiers, geometry, instrument "
                "registry and per-parameter reference bands (normal/watch/"
                "alarm thresholds) for one unit. Use this after "
                "get_plant_overview, once you know which unit_id you care "
                "about, to learn what \"normal\" means for each parameter "
                "before looking at its current or historical values - these "
                "are the exact bands get_current_scores, explain_score and "
                "get_parameter_history use to assign a zone label. For "
                "current condition use get_current_scores or explain_score; "
                "for behaviour over time use get_parameter_history."
            ),
            argument_model=GetUnitDetailArgs,
            handler=handle_get_unit_detail,
            schema_fn=get_unit_detail,
        )
    )
    registry.register(
        ToolSpec(
            name="get_current_scores",
            description=(
                "Daily per-unit health scores for one factory: which engine "
                "scored each unit, the worst-performing parameter behind "
                "each score, and the pre-computed change since the previous "
                "day. Use this to see the plant's current condition at a "
                "glance and find which unit needs attention first "
                "(worst_unit_id/worst_engine). It shows *that* a unit is "
                "underperforming, not the step-by-step why - call "
                "explain_score next with that unit_id for the deterministic "
                "breakdown. For the parameter's own values over time use "
                "get_parameter_history."
            ),
            argument_model=GetCurrentScoresArgs,
            handler=handle_get_current_scores,
            schema_fn=get_current_scores,
        )
    )
    registry.register(
        ToolSpec(
            name="explain_score",
            description=(
                "Deterministic, parameter-by-parameter breakdown of why one "
                "unit's health score is what it is: every contributing "
                "parameter, its zone, the penalty it added, and a one-line "
                "rationale per step. Call this after get_current_scores has "
                "told you a unit scored poorly, when you need the why "
                "instead of just the number. For that parameter's actual "
                "values over time rather than just its zone at this one "
                "instant, use get_parameter_history next."
            ),
            argument_model=GetExplainScoreArgs,
            handler=handle_explain_score,
            schema_fn=explain_score,
        )
    )
    registry.register(
        ToolSpec(
            name="get_parameter_history",
            description=(
                "Timestamped values with zone labels for one or more "
                "measured or derived parameters on one unit, over an "
                "explicit date window. Use this when you need the actual "
                "values themselves - to see exactly when a parameter "
                "crossed a zone boundary, or to eyeball an excursion "
                "get_current_scores or get_active_alerts pointed you at. "
                "For aggregate trend statistics, variability, correlations, "
                "or removal-efficiency summaries over a window, prefer "
                "get_analytics instead (a Work Item 2 tool; use "
                "get_parameter_history in the meantime) - it is the right "
                "choice when you want a summary of the trend rather than "
                "the points that make it up. A parameter_code this unit "
                "does not report comes back honestly unpopulated "
                "(BRIDGE-9), never a silent zero. Windows over 21 days are "
                "summarised into weekly buckets, and any bounding applied "
                "is disclosed in the `bounding` field, never silent."
            ),
            argument_model=GetParameterHistoryArgs,
            handler=handle_get_parameter_history,
            schema_fn=get_parameter_history,
        )
    )
    registry.register(
        ToolSpec(
            name="get_active_alerts",
            description=(
                "Alerts fired by Lite's rule engine for one factory, with "
                "the rule name, severity, the triggering parameter and "
                "unit, and Lite's own deterministic root-cause hint. Use "
                "this to see what Lite's rules have already flagged before "
                "starting a diagnostic session - often the fastest route to "
                "the same parameter get_current_scores' worst_parameter or "
                "explain_score's steps point at, approached from the "
                "opposite direction. The root_cause_hint is a starting "
                "hypothesis to weigh, not a verified conclusion. For "
                "operational context in the same window (dosing changes, "
                "downtime, sludge operations) use get_recent_events (a Work "
                "Item 2 tool) once available."
            ),
            argument_model=GetActiveAlertsArgs,
            handler=handle_get_active_alerts,
            schema_fn=get_active_alerts,
        )
    )
    registry.register(
        ToolSpec(
            name="get_compliance_status",
            description=(
                "Permit limits versus recent effluent readings for one "
                "factory, with a pre-computed margin per parameter and an "
                "overall conformance tier. Use this to check regulatory "
                "standing directly, or once get_active_alerts or "
                "explain_score has surfaced a process issue that might be "
                "affecting effluent quality - an exceedance lining up in "
                "time with a fired alert or a degraded score is a strong "
                "signal they share a root cause. margin is signed (limit "
                "minus recent_value): positive is headroom, negative is by "
                "how much the limit was exceeded. For the effluent "
                "parameter's own values over a longer window use "
                "get_parameter_history."
            ),
            argument_model=GetComplianceStatusArgs,
            handler=handle_get_compliance_status,
            schema_fn=get_compliance_status,
        )
    )

    return registry


def build_app(
    settings: Settings,
    *,
    registry: ToolRegistry | None = None,
    grants: GrantStore | None = None,
    audit_sink: AuditSink | None = None,
) -> FastMCP:
    registry = registry if registry is not None else build_registry()
    grants = grants if grants is not None else seeded_grant_store()
    audit_sink = audit_sink if audit_sink is not None else FileAuditSink(settings.audit_log_path)

    mcp = FastMCP(
        "hydris-pulse-diagnostic-mcp",
        instructions=f"Hydris Pulse Diagnostic MCP server (toolset v{TOOLSET_VERSION}).",
        host=settings.host,
        port=settings.port,
    )

    for spec in registry:
        mcp.add_tool(
            spec.schema_fn,
            name=spec.name,
            description=spec.description,
            annotations=ToolAnnotations(readOnlyHint=True),
        )

    async def dispatch(tool_name: str, arguments: dict) -> dict:
        spec = registry.get(tool_name)
        if spec is None:
            raise LookupError(f"Unknown tool: {tool_name!r}")

        request_context = mcp._mcp_server.request_context
        raw_request = request_context.request if request_context is not None else None
        headers = {k.lower(): v for k, v in raw_request.headers.items()} if raw_request else {}

        return await run_tool_call(
            headers=headers,
            raw_arguments=arguments,
            spec=spec,
            service_token_secret=settings.service_token_secret,
            user_context_secret=settings.user_context_secret,
            grants=grants,
            audit_sink=audit_sink,
        )

    # Overrides the CallToolRequest handler FastMCP registered for itself at
    # construction time, so every call - whichever tool - goes through the
    # single pipeline above. tools/list is untouched: it still reflects each
    # tool's real schema via the ToolManager populated by add_tool() above.
    mcp._mcp_server.call_tool(validate_input=False)(dispatch)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    mcp = build_app(settings)
    logger.info("Diagnostic MCP server starting on %s:%s", settings.host, settings.port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
