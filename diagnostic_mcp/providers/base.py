"""The ModelProvider protocol - PD-13's seam: "reasoning model... each
independently swappable. No domain logic may depend on a specific
provider." Anthropic is the one implementation in this repo
(providers/anthropic/provider.py), but nothing that calls a
ModelProvider needs to know that; a second provider would only ever add
a new module here, never touch examples/run_diagnostic_session.py or
diagnostic_mcp/ itself.

Deliberately thin: this is the seam a demo agent needs to run a bounded
tool-use loop against a generic MCP client, not a general-purpose LLM
abstraction. Real Pulse's own agent harness (ADR-006, PD-02: no
third-party agent framework) will have considerably more machinery
(event-sourced sessions, compaction, streaming) sitting on top of
whatever this protocol becomes at that point - this is the W1-scale
seam, not the final one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-neutral tool shape, built from whatever a generic MCP
    client's `tools/list` returned (see examples/run_diagnostic_session.py)
    - never authored by hand against one provider's wire format."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    """One assistant turn. `assistant_message` is the provider's own wire
    shape for "what the assistant said", appended verbatim to the running
    message list by the caller - keeping it opaque here is what lets a
    second provider have a completely different message shape without
    this protocol changing. `text` and `tool_calls` are the
    provider-neutral view a caller actually reasons over.
    """

    assistant_message: dict[str, Any]
    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str


class ModelProvider(Protocol):
    async def next_turn(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
    ) -> ModelTurn:
        """Send the running conversation plus the tool catalogue, get back
        one assistant turn (text and/or tool calls to execute)."""
        ...

    def tool_result_message(self, results: list[tuple[ToolCall, str]]) -> dict[str, Any]:
        """Build the next message carrying tool results, in whatever wire
        shape this provider expects - appended to `messages` the same way
        `assistant_message` was."""
        ...
