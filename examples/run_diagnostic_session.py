#!/usr/bin/env python
"""Generic-MCP-client demo agent.

Proves tools 1-8 are usable end to end by a reasoning model: connects to
the running Diagnostic MCP server exactly the way any MCP client would
(streamable HTTP, official `mcp` client library, no bridge-specific
integration code), converts the advertised tool schemas into
provider-neutral definitions, and runs a bounded tool-use loop with Claude
driving which tools to call. This is the shape of the M1 exit demo ("an
expert can run a full manual diagnostic session against real plant data
using a generic MCP client"), scaled to what W1 actually ships - it is
NOT Pulse's own agent harness (event-sourced sessions, SSE streaming,
compaction, a proper plant-brief assembler - all W2+, see docs/scope.md).

This script is deliberately outside diagnostic_mcp/: the bridge itself
has no model-provider dependency (EXT-4/PD-13). It is a *consumer* of the
bridge, playing the role Pulse's own agent harness will play later.

Usage:
    pip install -e ".[dev,llm-demo]"
    cp .env.example .env            # fill in ANTHROPIC_API_KEY
    set -a && source .env && set +a # or export the vars another way
    python -m diagnostic_mcp.server &   # start the bridge in one terminal
    python examples/run_diagnostic_session.py "Why is fx-mbr-01 struggling?"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from diagnostic_mcp.auth.service_principal import issue_service_token
from diagnostic_mcp.auth.user_context import issue_user_context_token
from diagnostic_mcp.providers.anthropic.provider import AnthropicProvider
from diagnostic_mcp.providers.base import ModelProvider, ToolCall, ToolDefinition

SYSTEM_PROMPT = (
    "You are a wastewater treatment diagnostic assistant with read-only access "
    "to one plant's live state through the tools provided. Ground every claim "
    "in a tool result - never state a numeric fact from memory (Hydris Pulse "
    "principle 2: grounded before generative; if a tool did not return a fact, "
    "the fact does not exist for reasoning purposes). Call list_factories first "
    "if you do not already know which factory_id to use. Work toward a root "
    "cause with citations to the specific tool calls that support it, then "
    "propose a stepped remediation plan. This is advisory only: never suggest "
    "actuating equipment directly - only recommend checks and actions for a "
    "human operator to carry out and verify (Hydris Pulse is a diagnostic aid, "
    "not a control system)."
)

DEFAULT_QUESTION = (
    "Something seems off at fx-mbr-01. Find out what's wrong, explain the "
    "likely root cause with evidence, and suggest what the plant should check "
    "first."
)

MAX_AGENT_TURNS = 8  # bounded for this demo; a real harness paces this via LOOP-1's budget


def _headers_for_demo_user() -> dict[str, str]:
    service_secret = os.environ["LITE_MCP_SERVICE_TOKEN_SECRET"]
    user_secret = os.environ["LITE_MCP_USER_CONTEXT_SECRET"]
    return {
        "authorization": f"Bearer {issue_service_token(service_secret)}",
        "x-pulse-user-context": issue_user_context_token(user_secret, "u-ops-alpha", "org-alpha"),
        "x-pulse-session-id": "sess-demo-agent-1",
    }


async def _mcp_tools_to_definitions(session: ClientSession) -> list[ToolDefinition]:
    listed = await session.list_tools()
    return [
        ToolDefinition(name=t.name, description=t.description or "", input_schema=t.inputSchema)
        for t in listed.tools
    ]


async def _execute_tool_call(session: ClientSession, call: ToolCall) -> str:
    try:
        outcome = await session.call_tool(call.name, call.arguments)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
        return f"ERROR: {exc}"
    if outcome.isError:
        return f"ERROR: {outcome.content}"
    return json.dumps(outcome.structuredContent)


async def run_session(question: str, mcp_url: str, provider: ModelProvider) -> None:
    headers = _headers_for_demo_user()

    async with httpx.AsyncClient(headers=headers) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await _mcp_tools_to_definitions(session)
                print(
                    f"Connected to {mcp_url}. {len(tools)} tools available: "
                    f"{', '.join(t.name for t in tools)}\n"
                )

                messages: list[dict] = [{"role": "user", "content": question}]
                print(f"USER: {question}\n")

                for _ in range(MAX_AGENT_TURNS):
                    turn = await provider.next_turn(
                        system=SYSTEM_PROMPT, messages=messages, tools=tools
                    )
                    if turn.text:
                        print(f"ASSISTANT: {turn.text}\n")
                    messages.append(turn.assistant_message)

                    if not turn.tool_calls:
                        break

                    results: list[tuple[ToolCall, str]] = []
                    for call in turn.tool_calls:
                        print(f"  -> {call.name}({json.dumps(call.arguments)})")
                        results.append((call, await _execute_tool_call(session, call)))
                    messages.append(provider.tool_result_message(results))
                else:
                    print(f"\n(stopped after {MAX_AGENT_TURNS} turns without a final answer)")

                print("--- session ended ---")


def main() -> None:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    mcp_url = os.environ.get("LITE_MCP_URL", "http://127.0.0.1:8765/mcp")
    asyncio.run(run_session(question, mcp_url, AnthropicProvider()))


if __name__ == "__main__":
    main()
