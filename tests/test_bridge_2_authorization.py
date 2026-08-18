"""BRIDGE-2: explicit factory scope, per-call authorization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from diagnostic_mcp.auth.errors import AuthorizationDenied
from diagnostic_mcp.registry.pipeline import run_tool_call

from .conftest import SERVICE_SECRET, USER_SECRET, headers_for


async def _call(registry, grants, audit_sink, factory_id, arguments=None, user_id="u-ops-alpha"):
    spec = registry.get("get_plant_overview")
    return await run_tool_call(
        headers=headers_for(user_id),
        raw_arguments=arguments if arguments is not None else {"factory_id": factory_id},
        spec=spec,
        service_token_secret=SERVICE_SECRET,
        user_context_secret=USER_SECRET,
        grants=grants,
        audit_sink=audit_sink,
    )


class TestBridge2Authorization:
    async def test_tc_bridge_2_1_missing_factory_id_rejected_and_audited(
        self, registry, grants, audit_sink
    ):
        """TC-BRIDGE-2.1: call without a factory argument -> rejected."""
        with pytest.raises(ValidationError):
            await _call(registry, grants, audit_sink, factory_id=None, arguments={})

        records = await audit_sink.query_by_session("sess-test-1")
        assert records[-1].outcome == "rejected"
        assert "bad_arguments" in (records[-1].detail or "")

    async def test_tc_bridge_2_1_holds_for_every_factory_scoped_tool(
        self, registry, grants, audit_sink
    ):
        """Schema-level rejection for every tool that declares a factory
        scope - list_factories is the one documented exception (O9), so it
        is excluded here rather than silently expected to behave the same."""
        for spec in registry:
            if spec.name == "list_factories":
                continue
            with pytest.raises(ValidationError):
                await run_tool_call(
                    headers=headers_for("u-ops-alpha"),
                    raw_arguments={},
                    spec=spec,
                    service_token_secret=SERVICE_SECRET,
                    user_context_secret=USER_SECRET,
                    grants=grants,
                    audit_sink=audit_sink,
                )

    async def test_tc_bridge_2_2_cross_tenant_denied_without_leak(
        self, registry, grants, audit_sink
    ):
        """TC-BRIDGE-2.2 [NEG]: u-ops-alpha (granted fx-mbr-01 only) probes a
        factory it does not hold -> generic denial, indistinguishable from a
        probe against a factory id that does not exist at all (open item O3).
        """
        with pytest.raises(AuthorizationDenied) as granted_elsewhere:
            await _call(registry, grants, audit_sink, "fx-beta-01")

        with pytest.raises(AuthorizationDenied) as truly_unknown:
            await _call(registry, grants, audit_sink, "fx-does-not-exist")

        assert str(granted_elsewhere.value) == str(truly_unknown.value)

        records = await audit_sink.query_by_session("sess-test-1")
        assert len(records) == 2
        assert all(r.outcome == "rejected" for r in records)
        assert all(r.detail == "authorization_denied" for r in records)

    async def test_tc_bridge_2_3_revocation_takes_effect_on_next_call(
        self, registry, grants, audit_sink
    ):
        """TC-BRIDGE-2.3 [EDGE]: revoke mid-session -> the very next call
        fails. No caching outlives a revocation (open item O1)."""
        result = await _call(registry, grants, audit_sink, "fx-mbr-01")
        assert result["factory_id"] == "fx-mbr-01"

        grants.revoke("u-ops-alpha", "fx-mbr-01")

        with pytest.raises(AuthorizationDenied):
            await _call(registry, grants, audit_sink, "fx-mbr-01")

    async def test_o9_list_factories_never_widens_via_service_token(
        self, registry, grants, audit_sink
    ):
        """list_factories is exempt from the single-factory-scope gate, but
        it must still filter strictly to the caller's own live grants - it
        must never fall back to "everything the service token can read"."""
        spec = registry.get("list_factories")
        result = await run_tool_call(
            headers=headers_for("u-ops-alpha"),
            raw_arguments={},
            spec=spec,
            service_token_secret=SERVICE_SECRET,
            user_context_secret=USER_SECRET,
            grants=grants,
            audit_sink=audit_sink,
        )
        factory_ids = {f["factory_id"] for f in result["factories"]}
        # not fx-beta-01, even though the service token itself can read it
        assert factory_ids == {"fx-mbr-01"}

        grants.revoke("u-ops-alpha", "fx-mbr-01")
        result = await run_tool_call(
            headers=headers_for("u-ops-alpha"),
            raw_arguments={},
            spec=spec,
            service_token_secret=SERVICE_SECRET,
            user_context_secret=USER_SECRET,
            grants=grants,
            audit_sink=audit_sink,
        )
        assert result["factories"] == []
