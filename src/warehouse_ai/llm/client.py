"""Provider-agnostic LLM client with tool calling and backoff retries.

Supports:
- "mock": Deterministic, offline, keyword/intent router for testing and local demos.
- "gemini": Google GenAI SDK (google.genai) with tool calling, retries, and token accounting.
- "anthropic": Anthropic SDK (if installed) or graceful fallback.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from warehouse_ai.config import load_config

# Load environment variables from .env
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message & Response Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """Represents an agent's request to execute an external tool."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMMessage:
    """Standardized chat message across providers."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not self.tool_calls:
            d.pop("tool_calls")
        if self.tool_call_id is None:
            d.pop("tool_call_id")
        if self.name is None:
            d.pop("name")
        return d


@dataclass
class LLMResponse:
    """Unified response object returned by all LLM clients."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    provider: str = "mock"
    model: str = "mock-model"
    latency_s: float = 0.0

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


# ---------------------------------------------------------------------------
# Base Client Abstract Class
# ---------------------------------------------------------------------------

class LLMClient(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, model: str | None = None, temperature: float = 0.1, max_tokens: int = 4096):
        self.model = model or "default"
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Execute a chat completion with optional tool declarations."""
        pass


# ---------------------------------------------------------------------------
# Mock LLM Client (Offline, Deterministic, Zero-Network)
# ---------------------------------------------------------------------------

class MockLLMClient(LLMClient):
    """Deterministic offline client that routes user intents to tool calls without an API key."""

    def __init__(self, model: str = "mock-v1", temperature: float = 0.0, max_tokens: int = 4096):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.provider = "mock"

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        t0 = time.perf_counter()

        # Check if the last message is a tool response: synthesize final answer
        last_msg = messages[-1] if messages else LLMMessage(role="user", content="")
        tool_responses = [m for m in messages if m.role == "tool"]

        if tool_responses and last_msg.role == "tool":
            # Summarize the tool outputs directly
            summaries = []
            for tr in tool_responses:
                try:
                    payload = json.loads(tr.content)
                    if isinstance(payload, dict) and "summary" in payload:
                        summaries.append(f"• {payload['summary']}")
                    elif isinstance(payload, dict) and "data" in payload:
                        summaries.append(f"• Tool {tr.name or 'result'} completed.")
                except Exception:
                    summaries.append(f"• Tool {tr.name} returned: {tr.content[:100]}...")

            answer_text = (
                "Based on the verified operational model outputs:\n\n"
                + "\n".join(summaries)
                + "\n\nAll recommendations adhere strictly to warehouse constraints and data records."
            )
            elapsed = time.perf_counter() - t0
            return LLMResponse(
                content=answer_text,
                tool_calls=[],
                usage={"prompt_tokens": len(str(messages)) // 4, "completion_tokens": len(answer_text) // 4, "total_tokens": (len(str(messages)) + len(answer_text)) // 4},
                provider="mock",
                model=self.model,
                latency_s=round(elapsed, 3),
            )

        # Inspect user prompt and available tool declarations
        user_text = ""
        for m in reversed(messages):
            if m.role in ("user", "system"):
                user_text += " " + m.content.lower()

        available_tools = {t.get("name") for t in (tools or [])}
        tool_calls: list[ToolCall] = []

        # Intent keyword matching
        if ("forecast" in user_text or "demand" in user_text or "volume" in user_text) and "get_daily_forecast" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_forecast", name="get_daily_forecast", arguments={"horizon_days": 14}))
        elif ("hourly" in user_text or "profile" in user_text) and "get_hourly_profile" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_hourly", name="get_hourly_profile", arguments={"weekday": 0}))
        elif ("headcount" in user_text or "staff" in user_text or "labor" in user_text or "operators" in user_text) and "recommend_headcount" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_staff", name="recommend_headcount", arguments={"workload_hours": 12.4}))
        elif ("replenish" in user_text or "stock" in user_text or "min/max" in user_text) and "get_replenishment_plan" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_replenish", name="get_replenishment_plan", arguments={"policy_name": "abc_xyz_optimized"}))
        elif ("slot" in user_text or "reslot" in user_text or "coi" in user_text) and "recommend_reslotting" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_slotting", name="recommend_reslotting", arguments={"top_n": 20}))
        elif ("wave" in user_text or "batch" in user_text) and "plan_waves" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_waves", name="plan_waves", arguments={"algorithm": "seed_savings", "n_operators": 5}))
        elif ("exception" in user_text or "anomaly" in user_text or "short pick" in user_text) and "list_exceptions" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_exceptions", name="list_exceptions", arguments={"limit": 20}))
        elif ("query" in user_text or "sql" in user_text or "data" in user_text) and "query_data" in available_tools:
            tool_calls.append(ToolCall(id="call_mock_query", name="query_data", arguments={"query": "SELECT * FROM daily LIMIT 5"}))
        elif tools:
            # Default to calling the first available tool if tools are provided
            first_tool = tools[0]["name"]
            tool_calls.append(ToolCall(id="call_mock_default", name=first_tool, arguments={}))

        content = None if tool_calls else "I have analyzed your request. No external tools were required."
        elapsed = time.perf_counter() - t0

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage={"prompt_tokens": len(user_text) // 4, "completion_tokens": 50, "total_tokens": len(user_text) // 4 + 50},
            provider="mock",
            model=self.model,
            latency_s=round(elapsed, 3),
        )


# ---------------------------------------------------------------------------
# Gemini LLM Client (Google GenAI)
# ---------------------------------------------------------------------------

class GeminiLLMClient(LLMClient):
    """Client for Google Gemini models via google.genai."""

    def __init__(self, model: str = "gemini-2.0-flash", temperature: float = 0.1, max_tokens: int = 4096):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.provider = "gemini"
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment or .env file.")

        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
        except ImportError as err:
            raise ImportError("google-genai package is not installed. Install via `pip install google-genai`.") from err

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        t0 = time.perf_counter()
        from google.genai import types

        # Build contents
        contents: list[types.Content] = []
        for m in messages:
            role = "user" if m.role in ("user", "system") else "model"
            parts = []
            if m.content:
                parts.append(types.Part.from_text(text=m.content))
            if m.tool_calls:
                for tc in m.tool_calls:
                    parts.append(types.Part.from_function_call(name=tc.name, args=tc.arguments))
            if m.role == "tool" and m.tool_call_id:
                try:
                    res_dict = json.loads(m.content) if isinstance(m.content, str) else m.content
                except Exception:
                    res_dict = {"output": m.content}
                parts.append(types.Part.from_function_response(name=m.name or "tool", response=res_dict))

            if parts:
                contents.append(types.Content(role=role, parts=parts))

        # Format tool definitions
        genai_tools = []
        if tools:
            func_decls = []
            for t in tools:
                func_decls.append(
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t.get("description", ""),
                        parameters=t.get("parameters"),
                    )
                )
            genai_tools.append(types.Tool(function_declarations=func_decls))

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            tools=genai_tools if genai_tools else None,
        )

        # Retry loop with exponential backoff
        max_retries = 3
        backoff = 1.0
        response = None

        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as e:
                logger.warning("Gemini API call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2.0

        elapsed = time.perf_counter() - t0

        # Parse output
        out_content = response.text if response and hasattr(response, "text") else None
        tool_calls: list[ToolCall] = []

        if response and response.function_calls:
            for idx, fc in enumerate(response.function_calls):
                tool_calls.append(
                    ToolCall(
                        id=f"call_{fc.name}_{idx}",
                        name=fc.name,
                        arguments=dict(fc.args) if hasattr(fc, "args") else {},
                    )
                )

        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if response and hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage["prompt_tokens"] = getattr(um, "prompt_token_count", 0) or 0
            usage["completion_tokens"] = getattr(um, "candidates_token_count", 0) or 0
            usage["total_tokens"] = getattr(um, "total_token_count", 0) or 0

        return LLMResponse(
            content=out_content,
            tool_calls=tool_calls,
            usage=usage,
            provider="gemini",
            model=self.model,
            latency_s=round(elapsed, 3),
        )


# ---------------------------------------------------------------------------
# Factory Function
# ---------------------------------------------------------------------------

class OpenAILLMClient(LLMClient):
    """Client for OpenAI models (GPT-4o, GPT-4o-mini, GPT-4-turbo) via REST API."""

    def __init__(self, model: str = "gpt-4o", temperature: float = 0.1, max_tokens: int = 4096):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.provider = "openai"
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment or .env file.")

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        import requests

        t0 = time.perf_counter()

        # Format messages
        openai_messages: list[dict[str, Any]] = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.role == "tool" and m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
                if m.name:
                    msg["name"] = m.name
            openai_messages.append(msg)

        # Format tools
        openai_tools = None
        if tools:
            openai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if openai_tools:
            payload["tools"] = openai_tools
            payload["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Retries with exponential backoff
        max_retries = 3
        backoff = 1.0
        data = None

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
                else:
                    logger.warning("OpenAI API returned %s: %s", resp.status_code, resp.text)
                    if attempt == max_retries - 1:
                        resp.raise_for_status()
            except Exception as e:
                logger.warning("OpenAI API call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    raise
            time.sleep(backoff)
            backoff *= 2.0

        elapsed = time.perf_counter() - t0

        if not data:
            raise RuntimeError("Failed to receive valid response from OpenAI API.")

        choice = data["choices"][0]
        msg = choice.get("message", {})
        out_content = msg.get("content")
        tool_calls: list[ToolCall] = []

        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                args = {}
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except Exception:
                    args = {"raw": func.get("arguments", "")}
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{func.get('name')}"),
                        name=func.get("name", ""),
                        arguments=args,
                    )
                )

        raw_usage = data.get("usage", {})
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens", 0),
            "completion_tokens": raw_usage.get("completion_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }

        return LLMResponse(
            content=out_content,
            tool_calls=tool_calls,
            usage=usage,
            provider="openai",
            model=self.model,
            latency_s=round(elapsed, 3),
        )


class AnthropicLLMClient(LLMClient):
    """Client for Anthropic Claude models (Claude 3.5 Sonnet, Haiku) via REST API."""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022", temperature: float = 0.1, max_tokens: int = 4096):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.provider = "anthropic"
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or .env file.")

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        import requests

        t0 = time.perf_counter()

        system_prompt = ""
        anthropic_messages: list[dict[str, Any]] = []

        for m in messages:
            if m.role == "system":
                system_prompt = m.content
            elif m.role in ("user", "assistant"):
                anthropic_messages.append({"role": m.role, "content": m.content or ""})
            elif m.role == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "tool_call",
                            "content": m.content,
                        }
                    ],
                })

        anthropic_tools = None
        if tools:
            anthropic_tools = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Retries with exponential backoff
        max_retries = 3
        backoff = 1.0
        data = None

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    break
                else:
                    logger.warning("Anthropic API returned %s: %s", resp.status_code, resp.text)
                    if attempt == max_retries - 1:
                        resp.raise_for_status()
            except Exception as e:
                logger.warning("Anthropic API call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt == max_retries - 1:
                    raise
            time.sleep(backoff)
            backoff *= 2.0

        elapsed = time.perf_counter() - t0

        if not data:
            raise RuntimeError("Failed to receive valid response from Anthropic API.")

        out_content_parts = []
        tool_calls: list[ToolCall] = []

        for item in data.get("content", []):
            if item.get("type") == "text":
                out_content_parts.append(item.get("text", ""))
            elif item.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=item.get("id", ""),
                        name=item.get("name", ""),
                        arguments=item.get("input", {}),
                    )
                )

        usage_raw = data.get("usage", {})
        usage = {
            "prompt_tokens": usage_raw.get("input_tokens", 0),
            "completion_tokens": usage_raw.get("output_tokens", 0),
            "total_tokens": usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
        }

        return LLMResponse(
            content="\n".join(out_content_parts) if out_content_parts else None,
            tool_calls=tool_calls,
            usage=usage,
            provider="anthropic",
            model=self.model,
            latency_s=round(elapsed, 3),
        )


def get_llm_client(
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> LLMClient:
    """Instantiate and return an LLM client based on config or explicit parameters."""
    cfg = load_config()
    chosen_provider = (provider or os.getenv("LLM_PROVIDER") or cfg.llm.provider).lower()
    chosen_model = model or cfg.llm.model
    chosen_temp = temperature if temperature is not None else cfg.llm.temperature
    chosen_max_tokens = max_tokens if max_tokens is not None else cfg.llm.max_tokens

    if chosen_provider == "mock":
        return MockLLMClient(model=chosen_model, temperature=chosen_temp, max_tokens=chosen_max_tokens)
    elif chosen_provider == "gemini":
        try:
            return GeminiLLMClient(model=chosen_model, temperature=chosen_temp, max_tokens=chosen_max_tokens)
        except Exception as e:
            logger.warning("Failed to initialize GeminiLLMClient (%s). Falling back to MockLLMClient.", e)
            return MockLLMClient(model="mock-fallback", temperature=0.0)
    elif chosen_provider in ("openai", "gpt"):
        try:
            m = chosen_model if ("gpt" in chosen_model or "o1" in chosen_model) else "gpt-4o"
            return OpenAILLMClient(model=m, temperature=chosen_temp, max_tokens=chosen_max_tokens)
        except Exception as e:
            logger.warning("Failed to initialize OpenAILLMClient (%s). Falling back to MockLLMClient.", e)
            return MockLLMClient(model="mock-fallback", temperature=0.0)
    elif chosen_provider in ("anthropic", "claude"):
        try:
            m = chosen_model if "claude" in chosen_model else "claude-3-5-sonnet-20241022"
            return AnthropicLLMClient(model=m, temperature=chosen_temp, max_tokens=chosen_max_tokens)
        except Exception as e:
            logger.warning("Failed to initialize AnthropicLLMClient (%s). Falling back to MockLLMClient.", e)
            return MockLLMClient(model="mock-fallback", temperature=0.0)
    else:
        logger.warning("Unsupported LLM provider '%s'. Defaulting to MockLLMClient.", chosen_provider)
        return MockLLMClient(model="mock-fallback", temperature=0.0)

