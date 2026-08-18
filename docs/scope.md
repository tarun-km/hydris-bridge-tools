# Scope

This repo holds **Work Item 2** of the Bridge track's W1 scope (see the
Hydris Pulse Bridge Track W1 Engineering Documentation, Part E): tools 1
to 8 (`list_factories` through `get_compliance_status`), BRIDGE-1
(read-only, structurally), BRIDGE-3 (LLM-oriented response shape) and
BRIDGE-4 (when-to-use descriptions).

It is built as a direct continuation of Work Item 1's skeleton
(`hydris-mcp-integration`), not a from-scratch server: `diagnostic_mcp/`
here carries the same `auth/`, `audit/`, `registry/` and `services/`
architecture, extended only where Work Item 2 needed something new (see
below and `docs/decisions.md`). When this merges into the Lite monorepo
at `lite/diagnostic_mcp/`, Work Item 1 and Work Item 2's code become one
package in one PR sequence, so keeping them structurally identical here
is deliberate, not incidental.

## In scope (built here)

- **BRIDGE-1** - all eight tools are read-only, enforced structurally at
  registration (`diagnostic_mcp/registry/tool_registry.py`), backed by a
  CI static check (`scripts/check_no_write_imports.py`, unchanged from W1).
- **BRIDGE-3** - every numeric field carries a unit
  (`diagnostic_mcp/models/common.py::Quantity`/`SignedDelta`), every
  series point carries a zone label, `get_current_scores` and
  `get_compliance_status` pre-compute their deltas/margins, and
  `get_parameter_history` bounds and discloses truncation/summarisation
  (`diagnostic_mcp/tools/parameter_history.py`).
- **BRIDGE-4** - all eight descriptions carry when-to-use guidance
  (`diagnostic_mcp/server.py`), held under a contract snapshot
  (`tests/contract/fixtures/tool_descriptions.json`,
  `tests/test_bridge_4_descriptions.py`), with the `get_parameter_history`
  <-> `get_analytics` forward cross-reference written now even though
  `get_analytics` itself is a Work Item 2-proper (W2 window) tool not yet
  implemented here.
- **BRIDGE-9** - the `record_status` block on `get_parameter_history`
  (tool 6, the one W1-8 tool the source doc's own assertion matrix names),
  demonstrated via a parameter_code a unit genuinely does not report
  rather than a fabricated data gap - see `docs/decisions.md`.
- **BRIDGE-2/5/NFR-4** - reused from Work Item 1 unchanged in spirit,
  extended only for O9 (see below): every factory-scoped tool still goes
  through the identical per-call authorization and audit pipeline.
- **A working LLM connection seam** - `diagnostic_mcp/providers/` (a
  provider-neutral `ModelProvider` protocol plus one Anthropic
  implementation) and `examples/run_diagnostic_session.py`, a
  generic-MCP-client demo agent that proves tools 1-8 are usable end to
  end by a reasoning model - the shape of the M1 exit demo, not the whole
  of Pulse. See "LLM connection seam" below.

## Explicitly out of scope

- **Tools 9-15** (`get_recent_events` through `get_operations_context`),
  W2 proper. `get_parameter_history`'s description names `get_analytics`
  forward per BRIDGE-4's own cross-reference requirement, but no code for
  it exists here.
- **BRIDGE-11** (calibration currency, sensor health, origin, reference-
  vs-acquisition time). That is Work Item 3's gap-report deliverable,
  tracked in a separate repo/track. Nothing in this fixture set claims
  calibration or sensor-confidence metadata; `get_parameter_history`'s
  `record_status` block is BRIDGE-9 (populated vs not-recorded), a
  different requirement that happens to live on the same tool.
- **The real Lite service layer and scoring engines.**
  `diagnostic_mcp/services/fixtures.py` and `services/scoring.py` are
  in-memory stand-ins: two factories (`fx-mbr-01`, `fx-beta-01`) with a
  30-day deterministic parameter history, reference bands, a small
  zone-penalty scoring engine, alerts and compliance limits. When this
  package moves into the Lite monorepo, these two modules - and only
  these two - get replaced with real read-service and scoring-engine
  calls; nothing in `auth/`, `audit/`, `registry/`, `models/`, `tools/`
  or `providers/` should need to change.
- **The contract package as a separate pinned artifact.**
  [ARCH] Sec 4.4 calls for `packages/lite-bridge-contract` in the Pulse
  monorepo, published and versioned independently. There is no Pulse
  monorepo here, so the equivalent material (response models, golden
  fixtures, a description snapshot, a schema-conformance suite) lives in
  `tests/contract/` instead. The distinction that matters (frozen
  fixtures, a suite that fails on an unreviewed schema or description
  change) is preserved; only the packaging/versioning/publication
  mechanics are deferred to when a real Pulse monorepo exists to consume it.
- **BRIDGE-6 in its eventual real form.** The toolset version is a plain
  semver string (`diagnostic_mcp/server.py::TOOLSET_VERSION`, now
  `"0.2.0"`, bumped by hand for this additive change) - same skeleton-scale
  answer Work Item 1 gave to O5, extended rather than redesigned.
- **Pulse's own agent harness, event-sourced sessions, SSE.** All W2+
  (ADR-002/006/009). `examples/run_diagnostic_session.py` runs one bounded
  tool-use loop to prove the tools are usable, not a session model.
- **TLS termination, the real "Lite build fails on a write-service
  import" CI check, BRIDGE-7 cross-repo CI wiring.** Unchanged from Work
  Item 1's own scope note - still infrastructure/cross-repo concerns
  outside a single Python package.

## O9: `list_factories`' factory-scope exemption

BRIDGE-2 AC-1 requires every tool to declare a mandatory factory-scope
argument, and the Work Item 1 skeleton flagged its own tension with
`list_factories` (whose entire purpose is enumeration *before* a factory
is chosen) without resolving it, deferring to "whoever designs
`list_factories`" - Work Item 2, i.e. this repo. See `docs/decisions.md`,
O9, for the resolution: an explicit, per-tool `requires_factory_scope`
flag on `ToolSpec`, defaulting to `True` (preserving W1's behaviour for
every other tool) and set to `False` only for `list_factories`, whose
results are always filtered to the caller's own live grants
(`GrantStore.granted_factories`) rather than exempted from authorization
altogether.

## LLM connection seam

The bridge server itself (`diagnostic_mcp/`) has zero model-provider
dependency - nothing in it imports `anthropic` or any other SDK, and
`scripts/check_provider_confinement.py` enforces that in CI the same way
`check_no_write_imports.py` enforces BRIDGE-1. The seam exists so a
reasoning model can be swapped later (PD-13/EXT-4) without touching the
bridge:

- `diagnostic_mcp/providers/base.py` - the `ModelProvider` protocol.
- `diagnostic_mcp/providers/anthropic/provider.py` - the one
  implementation shipped here, reading `ANTHROPIC_API_KEY` (and
  optionally `PULSE_LLM_MODEL`) from the environment only - see
  `.env.example`. Never hardcoded, never read from a file in the repo.
- `examples/run_diagnostic_session.py` - a generic-MCP-client demo agent
  (official `mcp` client library, no bridge-specific integration code)
  that runs a bounded Claude tool-use loop against a live server. This is
  deliberately small: it is not Pulse's own agent harness (PD-02/ADR-006:
  no third-party agent framework either, so it talks to the Anthropic SDK
  directly), just enough to prove the M1 exit demo's shape - "an expert
  can run a full manual diagnostic session against real plant data using
  a generic MCP client" - against the eight tools this repo actually ships.
