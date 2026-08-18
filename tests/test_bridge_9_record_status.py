"""BRIDGE-9: populated=False marks a genuine blind spot, distinct from
populated=True plus an empty result (a real, usable absence). Only tool 6
(get_parameter_history) is in the W1-8 surface, per [RSD]'s own
record_status assertion matrix (tools 6, 9, 10, 13, 14, 15).
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


class TestBridge9RecordStatus:
    async def test_populated_true_for_a_parameter_the_unit_actually_reports(
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
                "parameter_codes": ["tmp"],
                "start_date": "2026-08-01",
                "end_date": "2026-08-17",
            },
        )
        record_status = result["series"][0]["record_status"]
        assert record_status["populated"] is True
        assert record_status["records_in_window"] == 17
        assert record_status["records_in_window"] == len(result["series"][0]["points"])

    async def test_populated_false_for_a_parameter_this_unit_does_not_report(
        self, registry, grants, audit_sink
    ):
        """tmp belongs to u-mbr-01, not u-eq-01 - asking u-eq-01 for it is a
        genuine "this unit does not log this" case, not a coincidental
        zero-row result."""
        result = await _call(
            registry,
            grants,
            audit_sink,
            "get_parameter_history",
            {
                "factory_id": "fx-mbr-01",
                "unit_id": "u-eq-01",
                "parameter_codes": ["tmp"],
                "start_date": "2026-08-01",
                "end_date": "2026-08-17",
            },
        )
        record_status = result["series"][0]["record_status"]
        assert record_status["populated"] is False
        assert record_status["records_in_window"] == 0
        assert result["series"][0]["points"] == []
