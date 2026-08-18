"""The model-provider seam (PD-13, EXT-4).

Nothing in diagnostic_mcp/ outside this package may import a concrete
provider SDK - the bridge itself has no model dependency at all; only a
consumer of the bridge (examples/run_diagnostic_session.py, and later
Pulse's own agent harness) does. See providers/base.py for the protocol
and providers/anthropic/ for the one concrete implementation this repo
ships.
"""
