"""Boots the real streamable-HTTP server and calls it over the wire with
the official MCP client - proves the definition-of-done item ("MCP server
registered in-process..., streamable HTTP transport reachable, all eight
tools implemented") end to end, not just at the unit level, and that a
generic MCP client sees exactly the tools this toolset version advertises.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from diagnostic_mcp.auth.service_principal import issue_service_token
from diagnostic_mcp.auth.user_context import issue_user_context_token
from diagnostic_mcp.config import Settings
from diagnostic_mcp.server import build_app

from .conftest import SERVICE_SECRET, USER_SECRET

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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    settings = Settings(
        service_token_secret=SERVICE_SECRET,
        user_context_secret=USER_SECRET,
        audit_log_path=str(tmp_path / "audit.jsonl"),
        host="127.0.0.1",
        port=_free_port(),
    )
    app = build_app(settings).streamable_http_app()
    config = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start in time"

    try:
        yield f"http://{settings.host}:{settings.port}/mcp", settings
    finally:
        server.should_exit = True
        thread.join(timeout=5)


class TestServerIntegration:
    async def test_streamable_http_end_to_end(self, live_server):
        url, settings = live_server
        headers = {
            "authorization": f"Bearer {issue_service_token(settings.service_token_secret)}",
            "x-pulse-user-context": issue_user_context_token(
                settings.user_context_secret, "u-ops-alpha", "org-alpha"
            ),
            "x-pulse-session-id": "sess-e2e-1",
        }

        async with httpx.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} == EXPECTED_TOOLS

                    lf = next(t for t in tools.tools if t.name == "list_factories")
                    assert "factory_id" not in lf.inputSchema.get("properties", {})

                    for t in tools.tools:
                        if t.name == "list_factories":
                            continue
                        assert "factory_id" in t.inputSchema.get("required", []), t.name

                    granted = await session.call_tool(
                        "get_plant_overview", {"factory_id": "fx-mbr-01"}
                    )
                    assert granted.isError is False
                    assert granted.structuredContent["factory_id"] == "fx-mbr-01"

                    denied = await session.call_tool(
                        "get_plant_overview", {"factory_id": "fx-beta-01"}
                    )
                    assert denied.isError is True

                    listed = await session.call_tool("list_factories", {})
                    assert listed.isError is False
                    assert [f["factory_id"] for f in listed.structuredContent["factories"]] == [
                        "fx-mbr-01"
                    ]
