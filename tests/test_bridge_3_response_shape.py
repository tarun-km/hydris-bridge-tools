"""BRIDGE-3: units on every numeric field, zone labels on series data,
pre-computed deltas where comparison is the purpose, and disclosed
bounding wherever the underlying data volume is unbounded.
"""

from __future__ import annotations

from diagnostic_mcp.registry.pipeline import run_tool_call

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


def _assert_quantity(q):
    assert set(q.keys()) >= {"value", "unit"}
    assert isinstance(q["value"], int | float)
    assert isinstance(q["unit"], str) and q["unit"]


class TestBridge3ResponseShape:
    async def test_get_current_scores_units_and_deltas(self, registry, grants, audit_sink):
        result = await _call(
            registry, grants, audit_sink, "get_current_scores", {"factory_id": "fx-mbr-01"}
        )
        assert result["units"], "expected at least one scored unit"
        for unit in result["units"]:
            _assert_quantity(unit["health_score"])
            delta = unit["health_score_delta"]
            assert set(delta.keys()) >= {"value", "unit", "reference"}
            for contribution in unit["contributions"]:
                _assert_quantity(contribution["latest_value"])
                _assert_quantity(contribution["penalty"])
                assert contribution["zone"] in {"normal", "watch", "alarm"}

    async def test_get_unit_detail_bands_and_instruments_have_units(
        self, registry, grants, audit_sink
    ):
        result = await _call(
            registry,
            grants,
            audit_sink,
            "get_unit_detail",
            {"factory_id": "fx-mbr-01", "unit_id": "u-mbr-01"},
        )
        assert result["parameter_bands"]
        for band in result["parameter_bands"]:
            assert band["unit"]
        if result["geometry"]["volume"] is not None:
            _assert_quantity(result["geometry"]["volume"])

    async def test_get_parameter_history_points_have_units_and_zones(
        self, registry, grants, audit_sink
    ):
        result = await _call(
            registry,
            grants,
            audit_sink,
            "get_parameter_history",
            {
                "factory_id": "fx-mbr-01",
                "unit_id": "u-mbr-01",
                "start_date": "2026-08-01",
                "end_date": "2026-08-17",
            },
        )
        assert result["series"]
        for series in result["series"]:
            for point in series["points"]:
                assert point["unit"]
                assert point["zone"] in {"normal", "watch", "alarm"}

    async def test_get_parameter_history_bounding_disclosed_on_oversized_window(
        self, registry, grants, audit_sink
    ):
        result = await _call(
            registry,
            grants,
            audit_sink,
            "get_parameter_history",
            {
                "factory_id": "fx-mbr-01",
                "unit_id": "u-mbr-01",
                "start_date": "2025-01-01",
                "end_date": "2026-08-17",
            },
        )
        assert result["bounding"]["applied"] is True
        assert result["bounding"]["reason"]

    async def test_get_parameter_history_small_window_not_bounded(
        self, registry, grants, audit_sink
    ):
        result = await _call(
            registry,
            grants,
            audit_sink,
            "get_parameter_history",
            {
                "factory_id": "fx-mbr-01",
                "unit_id": "u-mbr-01",
                "start_date": "2026-08-10",
                "end_date": "2026-08-17",
            },
        )
        assert result["bounding"]["applied"] is False
        assert result["bounding"]["resolution"] == "raw"

    async def test_get_compliance_status_margin_precomputed(self, registry, grants, audit_sink):
        result = await _call(
            registry, grants, audit_sink, "get_compliance_status", {"factory_id": "fx-mbr-01"}
        )
        assert result["overall_tier"] == "exceedance"
        for limit in result["limits"]:
            _assert_quantity(limit["limit"])
            _assert_quantity(limit["recent_value"])
            assert set(limit["margin"].keys()) >= {"value", "unit", "reference"}
            expected_margin = round(limit["limit"]["value"] - limit["recent_value"]["value"], 2)
            assert limit["margin"]["value"] == expected_margin

    async def test_get_active_alerts_trigger_values_have_units(self, registry, grants, audit_sink):
        result = await _call(
            registry, grants, audit_sink, "get_active_alerts", {"factory_id": "fx-mbr-01"}
        )
        assert result["alerts"]
        for alert in result["alerts"]:
            if alert["trigger_value"] is not None:
                _assert_quantity(alert["trigger_value"])
            assert alert["severity"] in {"info", "warning", "critical"}
