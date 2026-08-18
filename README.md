# hydris-bridge-tools

Hydris Pulse Bridge track, **Work Item 2**: the Diagnostic MCP server's
first eight tools (`list_factories` through `get_compliance_status`),
built directly on top of Work Item 1's skeleton
(`hydris-mcp-integration`). Discharges **BRIDGE-1** (read-only, tools 1-8
added), **BRIDGE-3** (LLM-oriented response shape) and **BRIDGE-4**
(when-to-use tool descriptions), and carries **BRIDGE-2/5/NFR-4** forward
unchanged in spirit from Work Item 1, with one documented exception (O9).

See [`docs/scope.md`](docs/scope.md) for exactly what is and isn't built
here, and [`docs/decisions.md`](docs/decisions.md) for the open-item
decisions this work item took a position on (the `list_factories`
factory-scope exemption, bounding thresholds, the deterministic scoring
engine, provider confinement), pending Nematullah's ratification.

## Architecture

- **Same two-identity auth, same per-call pipeline, same fail-closed
  audit** as Work Item 1 (`diagnostic_mcp/auth/`, `registry/pipeline.py`,
  `audit/`) - unchanged in enforcement, extended only so a
  factory-scope-exempt tool can still authorize itself from live grant
  state (see O9, `docs/decisions.md`).
- **Eight tools** (`diagnostic_mcp/tools/`), each a `(ArgsModel,
  handler, schema_fn)` triple registered into the same `ToolRegistry`
  Work Item 1 defined, sharing response-model building blocks
  (`diagnostic_mcp/models/common.py`: `Quantity`, `ZoneLabel`,
  `SignedDelta`, `BoundingDisclosure`, `RecordStatus`) so every tool's
  response is unit-bearing, zone-labelled and bounding-disclosed the same
  way.
- **A deterministic scoring engine** (`diagnostic_mcp/services/scoring.py`)
  over an in-memory fixture set (`services/fixtures.py`): two factories,
  a 30-day parameter history, reference bands, alerts and compliance
  limits, all deriving from one source of truth so scores, explanations
  and alerts can never disagree with each other (O11).
- **A provider-neutral LLM seam** (`diagnostic_mcp/providers/`) and a
  generic-MCP-client demo agent (`examples/run_diagnostic_session.py`)
  that proves the eight tools are usable end to end by a reasoning model -
  see "Try the LLM demo" below.

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # .venv/bin/pip on macOS/Linux
cp .env.example .env                        # then edit the two bridge secrets
```

Run the server:

```bash
set -a; source .env; set +a                 # or export the vars another way
python -m diagnostic_mcp.server
```

It listens on `streamable-http` at `http://127.0.0.1:8765/mcp` by default.

## Verify it end-to-end

```bash
pytest -v            # includes a real streamable-HTTP client/server round trip
ruff check .
mypy diagnostic_mcp tests examples
python scripts/check_no_write_imports.py
python scripts/check_provider_confinement.py
```

To call the running server manually with the official MCP client, mint a
service token and a user-context token against the same secrets the
server is running with:

```python
from diagnostic_mcp.auth.service_principal import issue_service_token
from diagnostic_mcp.auth.user_context import issue_user_context_token

service_token = issue_service_token("<LITE_MCP_SERVICE_TOKEN_SECRET>")
user_token = issue_user_context_token("<LITE_MCP_USER_CONTEXT_SECRET>", "u-ops-alpha", "org-alpha")
print(f"Authorization: Bearer {service_token}")
print(f"X-Pulse-User-Context: {user_token}")
```

Then call any of the eight tools with `factory_id="fx-mbr-01"` (granted to
`u-ops-alpha` - succeeds) or `factory_id="fx-beta-01"` (not granted -
denied, and both attempts land in `audit.jsonl`). `list_factories` takes
no `factory_id` at all (see O9) and returns only the factories the caller
holds a live grant for.

### The fixture story

`fx-mbr-01` (Alpha MBR Plant 01) carries a deliberate, deterministic
narrative across all eight tools: transmembrane pressure climbs and flux
declines over the last two weeks (a membrane-fouling arc), which
correlates with an effluent COD exceedance on the most recent day.
`get_current_scores`, `explain_score`, `get_parameter_history`,
`get_active_alerts` and `get_compliance_status` all read the same
underlying event from their own angle - useful for exercising a real
diagnostic session rather than five independent stories that happen to
share a `factory_id`. `fx-beta-01` (Beta Effluent Plant 01) stays
compliant throughout, with only a milder SVI trend approaching (not
crossing) a bulking watch threshold, as the "quiet" contrast case.

## Try the LLM demo

The MCP server itself has **no model-provider dependency** - this is
purely a consumer of it, proving the tools are usable by a reasoning
model end to end (the shape of the M1 exit demo: "an expert can run a
full manual diagnostic session against real plant data using a generic
MCP client").

```bash
.venv/Scripts/pip install -e ".[dev,llm-demo]"
# edit .env: set ANTHROPIC_API_KEY (get one at https://console.anthropic.com/settings/keys)
set -a; source .env; set +a
python -m diagnostic_mcp.server &            # terminal 1: the bridge
python examples/run_diagnostic_session.py "Why is fx-mbr-01 struggling?"   # terminal 2
```

`PULSE_LLM_MODEL` (default `claude-sonnet-5`) selects which Claude model
the demo agent uses. See [`docs/scope.md`](docs/scope.md#llm-connection-seam)
for what this seam is (and deliberately isn't - it is not Pulse's own
agent harness).

## Work Item 2 definition of done

| Item | Status |
|---|---|
| All eight tools implemented over the same read-service-shaped fixture layer | Done |
| Every tool takes a mandatory `factory_id` and goes through the Work Item 1 authorization path, except the one documented exemption (O9) | Done |
| Response models unit-bearing, zone-labelled, deltas pre-computed where comparison is the purpose | Done - `diagnostic_mcp/models/common.py` |
| Bounding implemented and disclosed on `get_parameter_history` | Done - O10, `docs/decisions.md` |
| BRIDGE-9 `record_status` on `get_parameter_history` | Done |
| When-to-use descriptions for all eight, with the `get_parameter_history`/`get_analytics` forward cross-reference | Done - `diagnostic_mcp/server.py` |
| Descriptions under contract snapshot | Done - `tests/contract/fixtures/tool_descriptions.json` |
| Golden request/response fixtures committed for each tool | Done - `tests/contract/fixtures/golden/` |
| Contract suite green against the fixture stub | Done - `tests/contract/test_golden_fixtures.py` |
| LLM connection seam with an env-var-only API key | Done - `diagnostic_mcp/providers/`, `.env.example` |
