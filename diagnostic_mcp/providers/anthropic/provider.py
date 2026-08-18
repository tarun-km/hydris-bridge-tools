"""The one module in this repo allowed to import the `anthropic` SDK
(EXT-4/PD-13's provider-confinement rule - a real Pulse deployment backs
this with a CI lint rule failing the build on a provider import anywhere
else; see docs/scope.md for why that lint rule isn't wired up here).

Reads its API key from the ANTHROPIC_API_KEY environment variable only -
never hardcoded, never read from a file checked into the repo, exactly
like the bridge's own secrets (config.py). Get a key at
https://console.anthropic.com/settings/keys and put it in .env (see
.env.example) or export it directly.

Nothing in diagnostic_mcp/ (the MCP server itself) imports this module -
the bridge has no model dependency at all. Only
examples/run_diagnostic_session.py, the generic-MCP-client demo agent,
does, standing in for what will eventually be Pulse's own agent harness
(PD-02/ADR-006: no third-party agent framework, so this talks to the
Anthropic SDK directly rather than through LangChain or similar).
"""

from __future__ import annotations

import os
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from diagnostic_mcp.providers.base import ModelTurn, ToolCall, ToolDefinition

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider:
    """Implements the ModelProvider protocol (providers/base.py) against
    the Anthropic Messages API."""

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill "
                "it in, or export it directly - see README.md's LLM demo section. "
                "The MCP server itself never needs this; only the demo agent does."
            )
        self._client = AsyncAnthropic(api_key=resolved_key)
        self._model = model or os.environ.get("PULSE_LLM_MODEL", DEFAULT_MODEL)

    async def next_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> ModelTurn:
        # `messages` is a plain provider-neutral dict shape (ModelProvider,
        # providers/base.py) by design - cast rather than retype the
        # protocol around one provider's stricter TypedDict.
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=cast(list[MessageParam], messages),
            tools=[
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ],
        )
        dumped = response.model_dump()
        text_parts = [block.text for block in response.content if block.type == "text"]
        tool_calls = tuple(
            ToolCall(id=block.id, name=block.name, arguments=block.input)
            for block in response.content
            if block.type == "tool_use"
        )
        return ModelTurn(
            assistant_message={"role": "assistant", "content": dumped["content"]},
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
        )

    def tool_result_message(self, results: list[tuple[ToolCall, str]]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": content}
                for call, content in results
            ],
        }
