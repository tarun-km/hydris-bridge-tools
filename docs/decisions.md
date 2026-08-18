# Bridge track decisions - Work Item 2

Work Item 1's `docs/decisions.md` recorded O1, O2, O3 and O5 as
skeleton-scale answers to open items the W1 doc left for the Bridge track
to decide, "not a ruling", pending Nematullah's ratification. This
document continues that numbering (O6-O10) for the decisions Work Item 2
had to take a position on to make tools 1-8 buildable and testable. Same
caveat applies: these are proposals, not rulings.

## O9 - `list_factories`' factory-scope exemption (BRIDGE-2 AC-1)

**The tension.** BRIDGE-2 AC-1 requires every tool schema to declare a
mandatory `factory_id`, and the registry rejects registration of anything
that doesn't (`MissingFactoryScope`). `list_factories`' whole purpose -
"factories visible to the caller" - is to run *before* any one factory is
known, so it structurally cannot declare a single factory scope. The W1
doc's own `docs/decisions.md` flagged this without resolving it,
naming it a problem for whoever designs `list_factories`.

**Decision.** `ToolSpec` (`diagnostic_mcp/registry/tool_registry.py`)
gains a `requires_factory_scope: bool = True` field. The registration
gate only enforces `MissingFactoryScope` when this is `True`. It is set
to `False` for exactly one tool, `list_factories`, and nowhere else -
and a pre-commit review correctly flagged that "nowhere else" was, in
the first pass, enforced only by convention (nothing stopped a second
tool from setting the same flag). `ToolRegistry.register` now checks the
tool's name against an explicit `FACTORY_SCOPE_EXEMPT_TOOLS` allowlist
(currently `{"list_factories"}`) and raises
`UnreviewedFactoryScopeExemption` for anything else that tries to opt
out - extending the allowlist is itself the review gate for a future
exemption, not a side effect of setting a flag on a `ToolSpec`.

The equivalent authorization guarantee is enforced in
`registry/pipeline.py::run_tool_call`: when `requires_factory_scope` is
`False`, the pipeline skips the single-factory grant check (there is no
factory to check) but still resolves the calling user's identity and
passes it, plus a *read-only* view of live grant state, to the handler
via a new `ToolContext` object. `ToolContext.grants` is typed as
`services/grants.py::ReadOnlyGrants` (a `Protocol` exposing only
`is_authorized`/`granted_factories`), not the mutable `GrantStore` -
another pre-commit review finding: handing every one of the eight
handlers (seven of them strictly read-only, BRIDGE-1) the store's public
`grant`/`revoke` methods was a foot-gun nothing caught. `list_factories`'
handler (`diagnostic_mcp/tools/list_factories.py`) is the only handler
that reads `context.grants` - it calls `granted_factories(user_id)`, the
same live, uncached lookup `is_authorized()` uses (O1's answer, inherited
unchanged), and filters its result to exactly that set. The service token
is never consulted for this decision, so it can never widen access -
`tests/test_bridge_2_authorization.py::test_o9_list_factories_never_widens_via_service_token`
asserts this directly (a user granted only `fx-mbr-01` never sees
`fx-beta-01` in the list, even though the service token itself can read
both).

**Why not exempt it from authorization entirely, or give it a sentinel
`factory_id` like `"*"`?** A sentinel scope would be theatre - there is no
factory being checked, so a fake argument only obscures that. Exempting
it from authorization entirely would violate the one invariant that
matters more than the mandatory-argument mechanics: *the service token
never widens access*. Filtering to live grants inside the handler is the
smallest change that keeps that invariant true for all eight tools
without exception, while still letting `list_factories`' shape match its
actual purpose.

**Consequence for the handler signature.** Since `list_factories` needed
`user_id` and `grants` inside its handler, and `ToolSpec.handler` is one
shared type across all eight tools, every handler now takes
`(args, context: ToolContext)` rather than W1's `(args)` alone. The other
seven tools all ignore `context` today - this is forward-provisioning for
the seam O9 needed, not a promise every future tool will use it, but
it means a future tool that needs the caller's identity (for a
per-user audit annotation, say) doesn't need another signature change.

## O10 - `get_parameter_history` bounding thresholds (BRIDGE-3 AC-2)

**Decision.** Windows up to 21 days return raw daily points. Windows
longer than 21 days are downsampled into weekly-average buckets
(`resolution="weekly_summary"`), and any request whose window falls
partly or wholly before this fixture set's earliest date
(`services/fixtures.py::EARLIEST_DATE`, 30 days before `FIXTURE_TODAY`)
is clipped to the data actually held. Both cases set
`bounding.applied=True` with a `reason` explaining which happened, per
BRIDGE-3 AC-2's "discloses the bounding applied" - never a silent
truncation.

**Why 21 days, not the whole 30-day fixture window.** A caller
investigating a specific excursion (the TMP/flux fouling arc, say) needs
day-level resolution to see exactly when a parameter crossed a zone
boundary - BRIDGE-3's own rationale for disclosure is that a model
reasoning over a summarised series can reach a confidently wrong read of
trend shape. Twenty-one days covers three weeks of daily detail, enough
for any single event in this fixture set; a caller asking for the full
month gets weekly buckets instead, which is the right tradeoff for "give
me the shape of the last month" rather than "show me exactly when this
happened."

## O11 - the scoring engine is deterministic and derived, not hand-authored per tool

**Decision.** `get_current_scores`, `explain_score` and
`get_active_alerts` do not carry independent hand-authored scores/alerts
that happen to agree with each other. `services/scoring.py::score_unit`
is the single function that reads `services/fixtures.py`'s reference
bands and parameter series and produces a health score, a worst parameter
and a per-parameter zone/penalty breakdown; `get_current_scores` and
`explain_score` both call it directly. `get_active_alerts`' fixture
records are authored against the same underlying series (its
`trigger_value`s are read from `PARAMETER_SERIES` at the fixture's own
alert-firing date, not retyped by hand) so the fixture data can't drift
from the scores that reference it.

**Why.** [PRD]'s own framing - "a deterministic explanation of why a
score is what it is" - fails quietly if the explanation and the score can
independently drift, which is exactly what happens when they're
maintained as separate hand-typed fixtures. Deriving both from one
function makes disagreement a code bug rather than a fixture-authoring
slip, and it's what `tests/test_scoring_narrative.py` actually checks
(e.g. `explain_score`'s `health_score` must equal `get_current_scores`'
value for the same unit, not just "look similar").

**Correction found in pre-commit review.** The first pass of this
guarantee still had two gaps, both closed before commit:

1. The `al-mbr-tmp-01` and `al-beta-svi-01` alert fixtures
   (`services/fixtures.py`) were originally stamped one to two days
   *before* their parameter actually crossed into the zone their severity
   implied - e.g. the TMP alert fired at a reading of 29.6 kPa, which is
   still "normal" (`watch_max=30`), one day before the real crossing at
   31.4 kPa. `get_active_alerts` and `get_parameter_history` disagreed
   about the same date/parameter. Fixed by moving both alerts to the
   first date/value that actually classifies into their claimed zone;
   `tests/test_scoring_narrative.py::TestAlertZoneConsistency` now
   asserts every alert's `trigger_value` classifies outside "normal"
   for its `parameter_code`'s band, so this can't silently regress.
2. `get_current_scores`/`explain_score` never validated `as_of_date`
   against the range this fixture set actually holds data for
   (`EARLIEST_DATE`..`FIXTURE_TODAY`). A date before `EARLIEST_DATE`
   produced zero contributions, which `score_unit` turned into a
   fabricated `health_score=100.0` - indistinguishable from a genuinely
   healthy plant, the exact "assume good data" failure BRIDGE-9 exists to
   prevent elsewhere in this codebase. Fixed with
   `services/fixtures.py::resolve_as_of`, which both tools now call
   instead of a bare `args.as_of_date or FIXTURE_TODAY.isoformat()`; an
   out-of-range date now raises `ValueError` rather than reporting a
   perfect score. See `tests/test_scoring_date_range.py`.

## O13 - a cancelled call still gets an audit record (BRIDGE-5)

**Decision.** `registry/pipeline.py::run_tool_call`'s handler-invocation
try/except catches `BaseException`, not `Exception`. Found in pre-commit
review: `asyncio.CancelledError` has derived from `BaseException` (not
`Exception`) since Python 3.8, so a call cancelled mid-handler - a client
disconnect, a transport timeout - previously propagated straight out of
`run_tool_call` without ever reaching `emit("error", ...)`, silently
violating BRIDGE-5's "no silent drops" guarantee for exactly the outcome
it's meant to cover. The bare `raise` after `emit` still preserves
cancellation semantics for the caller. See
`tests/test_bridge_5_audit_logging.py::test_cancelled_call_still_gets_an_audit_record`.

## Shared lookup helpers (reuse cleanup found in pre-commit review)

`services/fixtures.py::get_plant_record_or_raise` and
`get_unit_record_or_raise` replace seven near-identical hand-copied
`if record is None: raise LookupError(...)` blocks across
`plant_overview.py`, `unit_detail.py`, `current_scores.py`,
`explain_score.py`, `active_alerts.py`, `compliance_status.py` and
`parameter_history.py`. Same behaviour, one place to get the message
right. `compliance_status.py`'s handler also stopped silently
`continue`-ing past a declared compliance limit with no matching
`EFFLUENT_READINGS` entry (unreachable with today's two fixture
factories, but a silent drop there would have understated
`overall_tier` with no disclosure) - it now raises the same class of
data-consistency `LookupError` the other tools use.

## O12 - LLM provider confinement enforced the same way as BRIDGE-1

**Decision.** `scripts/check_provider_confinement.py` fails the build if
any module under `diagnostic_mcp/` outside `diagnostic_mcp/providers/`
imports a provider SDK (currently `anthropic`), mirroring
`check_no_write_imports.py`'s approach for BRIDGE-1. `tests/test_provider_confinement.py`
covers it the same way `test_bridge_1_readonly.py` covers the write-import
gate.

**Why.** PD-13/EXT-4 states the reasoning model must be independently
swappable and that "no domain logic may depend on a specific provider."
The bridge itself already satisfies this trivially (it has zero model
dependency), but the demo agent
(`examples/run_diagnostic_session.py`) and the `providers/anthropic/`
module are new surface area added in this work item, and a structural
check costs little more than the no-write-import gate already did while
keeping the guarantee enforced rather than just documented.

## Toolset version bump (BRIDGE-6)

`TOOLSET_VERSION` moves from Work Item 1's `"0.1.0"` to `"0.2.0"` -
additive (seven new tools; the one tool both work items touch,
`get_plant_overview`, gained fields but nothing was removed or reshaped
in an incompatible way). Per BRIDGE-6's own rule, an additive change
bumps minor/patch, not major. The description snapshot fixture
(`tests/contract/fixtures/tool_descriptions.json`) records the version it
was frozen against and the test suite fails if they drift apart
(`tests/test_bridge_4_descriptions.py`), so a version bump and a
description change are both forced to be reviewed together rather than
silently diverging.
