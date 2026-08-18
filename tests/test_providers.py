"""The ModelProvider seam (PD-13/EXT-4). No network calls here - the
Anthropic-backed tests only cover construction/error paths, never a real
API request, and are skipped entirely if the optional llm-demo extra
(`pip install -e ".[llm-demo]"`) is not installed, since the bridge itself
never depends on it.
"""

from __future__ import annotations

import pytest

from diagnostic_mcp.providers.base import ModelTurn, ToolCall, ToolDefinition

anthropic_provider = pytest.importorskip("diagnostic_mcp.providers.anthropic.provider")


class TestModelProviderShapes:
    def test_tool_definition_is_provider_neutral(self):
        tool = ToolDefinition(name="get_plant_overview", description="...", input_schema={})
        assert tool.name == "get_plant_overview"

    def test_model_turn_carries_text_and_tool_calls(self):
        call = ToolCall(id="call-1", name="list_factories", arguments={})
        turn = ModelTurn(
            assistant_message={"role": "assistant", "content": []},
            text="checking factories",
            tool_calls=(call,),
            stop_reason="tool_use",
        )
        assert turn.tool_calls[0].name == "list_factories"


class TestAnthropicProviderConstruction:
    def test_missing_api_key_raises_clear_error(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            anthropic_provider.AnthropicProvider(api_key=None)

    def test_explicit_api_key_and_default_model(self, monkeypatch):
        monkeypatch.delenv("PULSE_LLM_MODEL", raising=False)
        provider = anthropic_provider.AnthropicProvider(api_key="sk-ant-test-construction-only")
        assert provider._model == anthropic_provider.DEFAULT_MODEL

    def test_model_override_via_env_var(self, monkeypatch):
        monkeypatch.setenv("PULSE_LLM_MODEL", "claude-opus-5")
        provider = anthropic_provider.AnthropicProvider(api_key="sk-ant-test-construction-only")
        assert provider._model == "claude-opus-5"
