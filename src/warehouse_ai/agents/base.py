"""Base agent architecture with autonomous tool calling and structured execution loop."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class BaseAgent:
    """Base class for autonomous warehouse reasoning agents."""

    def __init__(
        self,
        name: str,
        role: str,
        prompt_filename: str,
        llm_client: LLMClient | None = None,
        provider: str | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.prompt_path = _PROMPTS_DIR / prompt_filename
        self.system_prompt = self._load_prompt()
        self.llm_client = llm_client or get_llm_client(provider=provider)
        self.tools = registry.get_for_agent(self.name)
        self.tool_schemas = registry.get_schemas_for_agent(self.name)

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return (
            f"You are {self.name}, the {self.role}.\n"
            "Rule: never invent numbers; only use numbers returned by tools; state assumptions."
        )

    def run(self, user_instruction: str, context: dict[str, Any] | None = None, max_turns: int = 5) -> dict[str, Any]:
        """Execute autonomous tool-reasoning loop until final response is generated."""
        prompt_content = user_instruction
        if context:
            prompt_content += f"\n\nOperational Context:\n{json.dumps(context, indent=2, default=str)}"

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=prompt_content),
        ]

        logger.info("[%s] Initiating reasoning cycle with %d tools...", self.name, len(self.tools))

        last_tool_outputs: dict[str, Any] = {}

        for turn in range(max_turns):
            response = self.llm_client.chat(messages=messages, tools=self.tool_schemas)

            if not response.has_tool_calls():
                logger.info("[%s] Reasoning cycle complete after turn %d.", self.name, turn + 1)
                return {
                    "content": response.content,
                    "tool_outputs": last_tool_outputs,
                    "agent": self.name,
                }

            # Execute tool calls
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
            )

            for tc in response.tool_calls:
                logger.info("[%s] Calling tool '%s' with args: %s", self.name, tc.name, tc.arguments)
                result = registry.execute(tc.name, **tc.arguments)
                last_tool_outputs[tc.name] = result

                messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(result, default=str),
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        # Fallback if loop exceeded max turns
        return {
            "content": "Reasoning cycle reached turn limit.",
            "tool_outputs": last_tool_outputs,
            "agent": self.name,
        }

