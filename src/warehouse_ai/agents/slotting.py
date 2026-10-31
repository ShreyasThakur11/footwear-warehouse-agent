"""SlottingAgent: generates weekly SKU relocation and layout optimization proposals."""

from __future__ import annotations

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.agents.schemas import SlottingOutput
from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient


class SlottingAgent(BaseAgent):
    """Specialist agent for warehouse layout optimization and SKU re-slotting."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="SlottingAgent",
            role="Storage Layout & SKU Slotting Specialist",
            prompt_filename="slotting.md",
            llm_client=llm_client,
            provider=provider,
        )

    def optimize_slotting(self, top_n: int = 20) -> SlottingOutput:
        """Propose top ROI box relocations to forward pick face."""
        res = registry.execute("recommend_reslotting", top_n=top_n)
        moves = res.get("data", [])
        assumptions = res.get("assumptions", [])

        tot_savings = sum(m.get("expected_travel_saved_per_week", 0.0) for m in moves)

        return SlottingOutput(
            top_n_moves=len(moves),
            expected_weekly_travel_saved_m=round(tot_savings, 1),
            proposals=moves,
            summary=res.get("summary", f"Proposed top {len(moves)} re-slotting moves."),
            assumptions=assumptions,
        )

