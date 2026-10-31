"""Unit tests for src/warehouse_ai/llm/client.py — Mock and Provider-agnostic LLM client."""

from __future__ import annotations

import json

from warehouse_ai.llm.client import (
    LLMMessage,
    MockLLMClient,
    ToolCall,
    get_llm_client,
)


def test_mock_client_direct_text():
    client = MockLLMClient()
    messages = [LLMMessage(role="user", content="Hello, warehouse assistant.")]
    res = client.chat(messages=messages)
    assert res.content is not None
    assert len(res.tool_calls) == 0
    assert res.provider == "mock"


def test_mock_client_tool_routing():
    client = MockLLMClient()
    tools = [
        {"name": "get_daily_forecast", "description": "Forecast demand"},
        {"name": "recommend_headcount", "description": "Staffing"},
    ]

    # Forecast intent
    messages = [LLMMessage(role="user", content="What is tomorrow's demand forecast?")]
    res = client.chat(messages=messages, tools=tools)
    assert res.has_tool_calls()
    assert res.tool_calls[0].name == "get_daily_forecast"

    # Staffing intent
    messages2 = [LLMMessage(role="user", content="What is the recommended labor headcount?")]
    res2 = client.chat(messages=messages2, tools=tools)
    assert res2.has_tool_calls()
    assert res2.tool_calls[0].name == "recommend_headcount"


def test_mock_client_multi_turn_tool_response():
    client = MockLLMClient()
    tool_output = json.dumps({"data": {"units": 1500}, "summary": "Forecast predicts 1,500 units tomorrow.", "assumptions": ["P50 estimate"]})

    messages = [
        LLMMessage(role="user", content="What is tomorrow's forecast?"),
        LLMMessage(role="assistant", content=None, tool_calls=[ToolCall(id="call_1", name="get_daily_forecast", arguments={})]),
        LLMMessage(role="tool", content=tool_output, tool_call_id="call_1", name="get_daily_forecast"),
    ]

    res = client.chat(messages=messages)
    assert res.content is not None
    assert "Forecast predicts 1,500 units tomorrow" in res.content
    assert len(res.tool_calls) == 0


def test_get_llm_client_factory():
    client = get_llm_client(provider="mock")
    assert isinstance(client, MockLLMClient)
    assert client.provider == "mock"


def test_get_llm_client_openai_and_anthropic_fallback_without_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Should gracefully fall back to MockLLMClient when keys are absent
    c_openai = get_llm_client(provider="openai")
    assert isinstance(c_openai, MockLLMClient)

    c_anthropic = get_llm_client(provider="anthropic")
    assert isinstance(c_anthropic, MockLLMClient)

