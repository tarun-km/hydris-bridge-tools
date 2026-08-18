"""EXT-4/PD-13: the reasoning model is a swappable provider confined to
diagnostic_mcp/providers/. Mirrors test_bridge_1_readonly.py's approach
for the no-write-import gate.
"""

from __future__ import annotations

from scripts.check_provider_confinement import check_source, find_violations


class TestProviderConfinement:
    def test_no_provider_import_outside_providers_on_the_real_tree(self):
        assert find_violations() == []

    def test_check_catches_a_synthetic_violation(self):
        synthetic_source = "import anthropic\n"
        violations = check_source(synthetic_source, label="<synthetic>")
        assert len(violations) == 1
        assert "anthropic" in violations[0]

        also_forbidden = "from anthropic import AsyncAnthropic\n"
        violations = check_source(also_forbidden, label="<synthetic-2>")
        assert len(violations) == 1
