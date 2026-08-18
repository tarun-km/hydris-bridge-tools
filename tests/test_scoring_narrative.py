"""Functional correctness of the deterministic fixture narrative, not just
schema shape: the same underlying fouling event on fx-mbr-01 must read
consistently across get_current_scores, explain_score, get_active_alerts
and get_compliance_status, per [PRD] D1/D2 - grounded in one live plant
state, not four independent stories that happen to share a factory_id.
"""

from __future__ import annotations

from diagnostic_mcp.models.common import zone_for
from diagnostic_mcp.registry.pipeline import run_tool_call
from diagnostic_mcp.services.fixtures import ALERTS, get_band

from .conftest import SERVICE_SECRET, USER_SECRET, headers_for


async def _call(registry, grants, audit_sink, tool_name, arguments, user_id="u-ops-alpha"):
    spec = registry.get(tool_name)
    return await run_tool_call(
        headers=headers_for(user_id),
        raw_arguments=arguments,
        spec=spec,
        service_token_secret=SERVICE_SECRET,
        user_context_secret=USER_SECRET,
        grants=grants,
        audit_sink=audit_sink,
    )


class TestFoulingNarrativeCoherence:
    async def test_worst_unit_is_the_membrane_bioreactor(self, registry, grants, audit_sink):
        scores = await _call(
            registry, grants, audit_sink, "get_current_scores", {"factory_id": "fx-mbr-01"}
        )
        assert scores["worst_unit_id"] == "u-mbr-01"
        assert scores["worst_engine"] == "membrane_performance_engine"

    async def test_explain_score_agrees_with_get_current_scores(self, registry, grants, audit_sink):
        scores = await _call(
            registry, grants, audit_sink, "get_current_scores", {"factory_id": "fx-mbr-01"}
        )
        mbr_unit = next(u for u in scores["units"] if u["unit_id"] == "u-mbr-01")

        explanation = await _call(
            registry,
            grants,
            audit_sink,
            "explain_score",
            {"factory_id": "fx-mbr-01", "unit_id": "u-mbr-01"},
        )
        assert explanation["health_score"]["value"] == mbr_unit["health_score"]["value"]
        assert explanation["worst_parameter"] == mbr_unit["worst_parameter"]

    async def test_tmp_and_flux_are_both_in_watch_zone_on_the_latest_day(
        self, registry, grants, audit_sink
    ):
        history = await _call(
            registry,
            grants,
            audit_sink,
            "get_parameter_history",
            {
                "factory_id": "fx-mbr-01",
                "unit_id": "u-mbr-01",
                "parameter_codes": ["tmp", "flux"],
                "start_date": "2026-08-17",
                "end_date": "2026-08-17",
            },
        )
        by_code = {s["parameter_code"]: s for s in history["series"]}
        assert by_code["tmp"]["points"][-1]["zone"] == "watch"
        assert by_code["flux"]["points"][-1]["zone"] == "watch"

    async def test_active_alerts_include_both_tmp_and_cod_rules(self, registry, grants, audit_sink):
        alerts = await _call(
            registry, grants, audit_sink, "get_active_alerts", {"factory_id": "fx-mbr-01"}
        )
        rule_names = {a["rule_name"] for a in alerts["alerts"]}
        assert rule_names == {"TMP_RISING_RULE", "COD_LIMIT_EXCEEDANCE_RULE"}

    async def test_compliance_exceedance_lines_up_with_the_cod_alert(
        self, registry, grants, audit_sink
    ):
        compliance = await _call(
            registry, grants, audit_sink, "get_compliance_status", {"factory_id": "fx-mbr-01"}
        )
        alerts = await _call(
            registry, grants, audit_sink, "get_active_alerts", {"factory_id": "fx-mbr-01"}
        )
        cod_limit = next(
            limit for limit in compliance["limits"] if limit["parameter_code"] == "cod"
        )
        cod_alert = next(a for a in alerts["alerts"] if a["parameter_code"] == "cod")

        assert compliance["overall_tier"] == "exceedance"
        assert cod_limit["tier"] == "exceedance"
        assert cod_limit["recent_value"]["value"] == cod_alert["trigger_value"]["value"]

    async def test_beta_plant_stays_compliant_with_only_a_watch_tier_svi_signal(
        self, registry, grants, audit_sink
    ):
        compliance = await _call(
            registry,
            grants,
            audit_sink,
            "get_compliance_status",
            {"factory_id": "fx-beta-01"},
            user_id="u-ops-beta",
        )
        alerts = await _call(
            registry,
            grants,
            audit_sink,
            "get_active_alerts",
            {"factory_id": "fx-beta-01"},
            user_id="u-ops-beta",
        )
        assert compliance["overall_tier"] == "compliant"
        assert {a["severity"] for a in alerts["alerts"]} == {"warning"}


class TestAlertZoneConsistency:
    """Regression guard for a class of bug a review caught: an alert
    firing on a date/value that get_parameter_history would classify as
    "normal" contradicts the alert's own severity and undermines the
    "same underlying data, viewed from different tools" guarantee this
    fixture set is built around (see docs/decisions.md, O11). Every alert
    whose parameter_code resolves to a real band must have its
    trigger_value actually fall outside "normal" at fired_at.
    """

    def test_every_resolvable_alert_trigger_value_is_outside_normal_zone(self):
        for factory_id, records in ALERTS.items():
            for record in records:
                if record.parameter_code is None:
                    continue
                band = get_band(record.parameter_code)
                if band is None:
                    continue  # e.g. "cod": a compliance parameter, not a banded one
                assert record.trigger_value is not None
                zone = zone_for(record.trigger_value, band)
                assert zone != "normal", (
                    f"{factory_id}/{record.alert_id} fired with {record.parameter_code}="
                    f"{record.trigger_value} which classifies as 'normal', not a real "
                    "watch/alarm breach"
                )
