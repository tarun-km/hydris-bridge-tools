"""BRIDGE-3 AC-3 / Work Item 2 DoD: "Golden request/response fixtures
committed for each tool" and "Contract suite green against the fixture
stub". Each fixture in fixtures/golden/<tool>.json freezes one real
request and its full response; this suite replays the request through the
same pipeline every other test uses and asserts an exact match, so an
accidental change to fixture data, scoring, or response shape is caught
here rather than only in a hand-inspected diff.

To change a golden fixture deliberately, regenerate it (see
docs/scope.md) and review the diff like any other contract change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from diagnostic_mcp.registry.pipeline import run_tool_call

from ..conftest import SERVICE_SECRET, USER_SECRET, headers_for

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))


@pytest.mark.parametrize("golden_path", GOLDEN_FILES, ids=lambda p: p.stem)
async def test_golden_fixture_replays_exactly(golden_path, registry, grants, audit_sink):
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    tool_name = golden_path.stem
    spec = registry.get(tool_name)
    assert spec is not None, f"{tool_name} is no longer registered"

    result = await run_tool_call(
        headers=headers_for(payload["request"]["user_id"], session_id="sess-golden-1"),
        raw_arguments=payload["request"]["arguments"],
        spec=spec,
        service_token_secret=SERVICE_SECRET,
        user_context_secret=USER_SECRET,
        grants=grants,
        audit_sink=audit_sink,
    )

    assert result == payload["response"]


def test_every_tool_has_a_golden_fixture(registry):
    fixture_names = {p.stem for p in GOLDEN_FILES}
    registered_names = {spec.name for spec in registry}
    assert fixture_names == registered_names
