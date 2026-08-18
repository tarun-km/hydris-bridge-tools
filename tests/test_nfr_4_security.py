"""NFR-4: least-privilege service principal, independent user authorization."""

from __future__ import annotations

import pytest

from diagnostic_mcp.auth.errors import AuthenticationError, AuthorizationDenied
from diagnostic_mcp.auth.service_principal import (
    MINIMUM_READ_SCOPES,
    issue_service_token,
    verify_service_token,
)
from diagnostic_mcp.registry.pipeline import run_tool_call

from .conftest import SERVICE_SECRET, USER_SECRET, headers_for


class TestNFR4Security:
    def test_tc_nfr_4_1_scope_audit_zero_surplus(self):
        """TC-NFR-4.1: granted scopes vs. the minimum read set for all 15
        tools -> zero surplus, none of them a write scope."""
        token = issue_service_token(SERVICE_SECRET)
        identity = verify_service_token(token, SERVICE_SECRET)
        assert identity.scopes == MINIMUM_READ_SCOPES
        assert all(scope.startswith("lite.read:") for scope in identity.scopes)

    def test_write_scope_on_service_token_is_rejected(self):
        """NFR-4 AC-1/AC-3: a token minted with any non-read scope fails
        verification outright - the service principal cannot widen access
        even if something upstream mis-issues it."""
        write_scopes = frozenset({"lite.write:update_setpoint"})
        bad_token = issue_service_token(SERVICE_SECRET, scopes=write_scopes)
        with pytest.raises(AuthenticationError):
            verify_service_token(bad_token, SERVICE_SECRET)

    async def test_tc_nfr_4_2_cross_tenant_probe_denied_before_service_token_matters(
        self, registry, grants, audit_sink
    ):
        """TC-NFR-4.2 [NEG]: u-ops-beta (org-beta, granted fx-beta-01) probes
        fx-mbr-01 (org-alpha's factory) - denied even though the service
        token itself can read fx-mbr-01. Denial happens before that read
        capability is ever exercised, and the attempt is logged."""
        spec = registry.get("get_plant_overview")
        with pytest.raises(AuthorizationDenied):
            await run_tool_call(
                headers=headers_for("u-ops-beta", org_id="org-beta"),
                raw_arguments={"factory_id": "fx-mbr-01"},
                spec=spec,
                service_token_secret=SERVICE_SECRET,
                user_context_secret=USER_SECRET,
                grants=grants,
                audit_sink=audit_sink,
            )

        records = await audit_sink.query_by_session("sess-test-1")
        assert records[-1].user_id == "u-ops-beta"
        assert records[-1].factory_id == "fx-mbr-01"
        assert records[-1].outcome == "rejected"

    async def test_tc_nfr_4_2_holds_across_every_factory_scoped_tool_path(
        self, registry, grants, audit_sink
    ):
        """The cross-tenant probe must be denied through every bridge-tool
        path, not just one representative tool (TC-NFR-4.2's own wording:
        "every session entry point and bridge-tool path")."""
        for spec in registry:
            if spec.name == "list_factories":
                continue
            arguments = {"factory_id": "fx-mbr-01"}
            if spec.name == "get_unit_detail":
                arguments["unit_id"] = "u-mbr-01"
            if spec.name == "explain_score":
                arguments["unit_id"] = "u-mbr-01"
            if spec.name == "get_parameter_history":
                arguments.update(
                    unit_id="u-mbr-01", start_date="2026-08-01", end_date="2026-08-17"
                )
            with pytest.raises(AuthorizationDenied):
                await run_tool_call(
                    headers=headers_for("u-ops-beta", org_id="org-beta"),
                    raw_arguments=arguments,
                    spec=spec,
                    service_token_secret=SERVICE_SECRET,
                    user_context_secret=USER_SECRET,
                    grants=grants,
                    audit_sink=audit_sink,
                )

    async def test_tc_nfr_4_5_expired_service_token_fails_closed(
        self, registry, grants, audit_sink
    ):
        """TC-NFR-4.5 [EDGE]: expired or rotated service token -> fails
        closed, no fallback to a cached or broader credential."""
        expired_token = issue_service_token(SERVICE_SECRET, ttl_seconds=-10)
        spec = registry.get("get_plant_overview")
        with pytest.raises(AuthenticationError):
            await run_tool_call(
                headers=headers_for("u-ops-alpha", service_token_override=expired_token),
                raw_arguments={"factory_id": "fx-mbr-01"},
                spec=spec,
                service_token_secret=SERVICE_SECRET,
                user_context_secret=USER_SECRET,
                grants=grants,
                audit_sink=audit_sink,
            )
