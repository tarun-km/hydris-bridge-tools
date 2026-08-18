"""BRIDGE-1: read-only toolset, enforced structurally at registration."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from diagnostic_mcp.registry.tool_registry import (
    MissingFactoryScope,
    NonReadOnlyToolRejected,
    ToolRegistry,
    ToolSpec,
    UnreviewedFactoryScopeExemption,
)
from diagnostic_mcp.server import build_registry
from scripts.check_no_write_imports import PACKAGE_ROOT, check_file, check_source

EXPECTED_TOOLS = {
    "list_factories",
    "get_plant_overview",
    "get_unit_detail",
    "get_current_scores",
    "explain_score",
    "get_parameter_history",
    "get_active_alerts",
    "get_compliance_status",
}


class _ArgsWithFactory(BaseModel):
    factory_id: str = Field(...)


class _ArgsWithoutFactory(BaseModel):
    note: str = Field(...)


async def _noop_handler(args: BaseModel, context) -> dict:
    return {}


async def _noop_schema_fn(factory_id: str) -> dict:
    raise NotImplementedError


class TestBridge1ReadOnly:
    def test_all_eight_tools_registered_and_read_only(self):
        registry = build_registry()
        assert {spec.name for spec in registry} == EXPECTED_TOOLS
        for spec in registry:
            assert spec.classification == "read_only"

    def test_tc_bridge_1_4_registration_rejects_non_read_only_tool(self):
        """TC-BRIDGE-1.4 [EDGE][NEG]: a synthetic write-classified tool must
        be rejected at *registration*, not merely at call time."""
        registry = ToolRegistry()
        bad_spec = ToolSpec(
            name="update_setpoint",
            description="synthetic negative-test tool - must never register",
            argument_model=_ArgsWithFactory,
            handler=_noop_handler,
            schema_fn=_noop_schema_fn,
            classification="write",  # type: ignore[arg-type]
        )

        with pytest.raises(NonReadOnlyToolRejected):
            registry.register(bad_spec)

        assert registry.get("update_setpoint") is None
        assert len(registry) == 0

    def test_bridge_2_ac_1_registration_requires_a_required_factory_id_field(self):
        """A tool whose argument model has no mandatory factory_id is
        rejected at registration too - BRIDGE-2 AC-1 enforced structurally,
        the same way BRIDGE-1 is - unless it opts out via
        requires_factory_scope=False (see O9, docs/decisions.md)."""
        registry = ToolRegistry()
        spec = ToolSpec(
            name="bad_tool",
            description="no factory scope declared",
            argument_model=_ArgsWithoutFactory,
            handler=_noop_handler,
            schema_fn=_noop_schema_fn,
        )

        with pytest.raises(MissingFactoryScope):
            registry.register(spec)

    def test_o9_exemption_is_explicit_opt_in_not_automatic(self):
        """Omitting factory_id without declaring requires_factory_scope=False
        must still be rejected - the exemption is opt-in per tool, never a
        side effect of forgetting the field."""
        registry = ToolRegistry()
        exempt_spec = ToolSpec(
            name="list_factories",
            description="deliberately exempt",
            argument_model=_ArgsWithoutFactory,
            handler=_noop_handler,
            schema_fn=_noop_schema_fn,
            requires_factory_scope=False,
        )
        registry.register(exempt_spec)  # must not raise: on the allowlist
        assert registry.get("list_factories") is not None

    def test_o9_exemption_is_not_available_to_unlisted_tools(self):
        """requires_factory_scope=False is only honoured for the one
        reviewed, allowlisted tool name (FACTORY_SCOPE_EXEMPT_TOOLS) - a
        different tool can't silently gain the same exemption just by
        setting the same flag on its own ToolSpec."""
        registry = ToolRegistry()
        spec = ToolSpec(
            name="get_something_else",
            description="not on the allowlist",
            argument_model=_ArgsWithoutFactory,
            handler=_noop_handler,
            schema_fn=_noop_schema_fn,
            requires_factory_scope=False,
        )
        with pytest.raises(UnreviewedFactoryScopeExemption):
            registry.register(spec)
        assert registry.get("get_something_else") is None

    def test_no_write_import_check_passes_on_the_real_tree(self):
        assert check_file.__module__  # sanity: import resolved
        violations = [v for path in PACKAGE_ROOT.rglob("*.py") for v in check_file(path)]
        assert violations == []

    def test_no_write_import_check_catches_a_synthetic_violation(self):
        """Stands in for TC-BRIDGE-1.2 ('register a synthetic update_setpoint
        tool on a test branch -> CI goes red') until this merges into the
        real Lite repo and the check can target Lite's actual write-service
        module names (see docs/scope.md)."""
        synthetic_source = "import lite.services.dosing_write_service\n"
        violations = check_source(synthetic_source, label="<synthetic>")
        assert len(violations) == 1
        assert "dosing_write_service" in violations[0]

        also_forbidden = "from lite.services.write import update_setpoint\n"
        violations = check_source(also_forbidden, label="<synthetic-2>")
        assert len(violations) == 1
