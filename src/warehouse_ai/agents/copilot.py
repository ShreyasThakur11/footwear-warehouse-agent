"""CopilotAgent: answers free-form supervisor queries citing model tool outputs."""

from __future__ import annotations

from typing import Any

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.llm.client import LLMClient


class CopilotAgent(BaseAgent):
    """Interactive supervisor assistant providing evidence-backed warehouse insights."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="CopilotAgent",
            role="Warehouse Operations Supervisor Copilot",
            prompt_filename="copilot.md",
            llm_client=llm_client,
            provider=provider,
        )

    def answer_query(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Answer free-form question with strict citation of tool calculation results."""
        result = self.run(user_instruction=query, context=context)
        return result.get("content", "I was unable to complete the analysis.")
