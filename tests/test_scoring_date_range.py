"""Regression guard for a review finding: get_current_scores and
explain_score used to silently report health_score=100 (a perfect score)
for an as_of_date outside the range this fixture set actually holds data
for, since zero contributions collapsed to zero penalty. Both tools now
validate as_of_date via services/fixtures.py::resolve_as_of and reject an
out-of-range date explicitly rather than reporting a fabricated "healthy"
result - the same "never assume good data" principle BRIDGE-9 already
applies to get_parameter_history's record_status.
"""

from __future__ import annotations

import pytest

from diagnostic_mcp.registry.pipeline import run_tool_call
from diagnostic_mcp.services.fixtures import EARLIEST_DATE, FIXTURE_TODAY, resolve_as_of

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


class TestResolveAsOf:
    def test_none_defaults_to_fixture_today(self):
        assert resolve_as_of(None) == FIXTURE_TODAY.isoformat()

    def test_in_range_date_passes_through(self):
        assert resolve_as_of(EARLIEST_DATE.isoformat()) == EARLIEST_DATE.isoformat()

    def test_before_earliest_date_raises(self):
        with pytest.raises(ValueError, match="outside the range"):
            resolve_as_of("2020-01-01")

    def test_after_today_raises(self):
        with pytest.raises(ValueError, match="outside the range"):
            resolve_as_of("2099-01-01")


class TestScoringToolsRejectOutOfRangeDates:
    async def test_get_current_scores_rejects_date_before_earliest(
        self, registry, grants, audit_sink
    ):
        with pytest.raises(ValueError, match="outside the range"):
            await _call(
                registry,
                grants,
                audit_sink,
                "get_current_scores",
                {"factory_id": "fx-mbr-01", "as_of_date": "2020-01-01"},
            )

    async def test_explain_score_rejects_date_before_earliest(self, registry, grants, audit_sink):
        with pytest.raises(ValueError, match="outside the range"):
            await _call(
                registry,
                grants,
                audit_sink,
                "explain_score",
                {"factory_id": "fx-mbr-01", "unit_id": "u-mbr-01", "as_of_date": "2020-01-01"},
            )

    async def test_rejected_date_is_still_audited_as_an_error(self, registry, grants, audit_sink):
        with pytest.raises(ValueError):
            await _call(
                registry,
                grants,
                audit_sink,
                "get_current_scores",
                {"factory_id": "fx-mbr-01", "as_of_date": "2020-01-01"},
            )
        records = await audit_sink.query_by_session("sess-test-1")
        assert records[-1].outcome == "error"
