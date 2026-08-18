"""BRIDGE-4: tool descriptions state *when to use* the tool, not only what
it returns, and a description change is a contract change - an unreviewed
wording edit must fail CI (TC-BRIDGE-4.3), so the descriptions are frozen
into tests/contract/fixtures/tool_descriptions.json and any edit to
server.py's description strings must update that fixture deliberately in
the same change.
"""

from __future__ import annotations

import json
from pathlib import Path

from diagnostic_mcp.server import TOOLSET_VERSION, build_registry

SNAPSHOT_PATH = Path(__file__).parent / "contract" / "fixtures" / "tool_descriptions.json"

WHEN_TO_USE_MARKERS = ("use this", "use ", "call this")


class TestBridge4Descriptions:
    def test_all_eight_descriptions_carry_when_to_use_guidance(self):
        registry = build_registry()
        for spec in registry:
            lowered = spec.description.lower()
            assert any(marker in lowered for marker in WHEN_TO_USE_MARKERS), (
                f"{spec.name} description has no when-to-use guidance"
            )

    def test_parameter_history_and_analytics_cross_reference_each_other(self):
        """TC-BRIDGE-4.2: get_parameter_history and get_analytics must each
        name the other. get_analytics itself ships in Work Item 2 proper
        (not yet implemented here), so only the get_parameter_history half
        of the pair can be asserted directly today - it is written now so
        get_analytics's own description only has to add the reciprocal
        reference, not invent the relationship from scratch (see
        docs/decisions.md)."""
        registry = build_registry()
        history = registry.get("get_parameter_history")
        assert "get_analytics" in history.description

    def test_descriptions_match_the_committed_snapshot(self):
        """TC-BRIDGE-4.3 [NEG]: an unreviewed description edit must fail
        this test (and therefore CI). To change a description
        deliberately, update tests/contract/fixtures/tool_descriptions.json
        in the same change."""
        registry = build_registry()
        current = {spec.name: spec.description for spec in registry}

        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert snapshot["toolset_version"] == TOOLSET_VERSION, (
            "TOOLSET_VERSION changed without updating the description snapshot "
            "(BRIDGE-6: a toolset version bump is itself contract material)"
        )
        assert current == snapshot["descriptions"]
