"""WaveAgent: batches open customer orders into balanced pick waves and assigns pickers."""

from __future__ import annotations

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.agents.schemas import WaveOutput
from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient


class WaveAgent(BaseAgent):
    """Specialist agent for pick wave batching, routing, and picker tour scheduling."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="WaveAgent",
            role="Pick Wave Routing & Batching Specialist",
            prompt_filename="wave.md",
            llm_client=llm_client,
            provider=provider,
        )

    def plan_first_waves(
        self,
        target_date: str,
        n_operators: int = 5,
        algorithm: str = "seed_savings",
    ) -> WaveOutput:
        """Batch initial waves of the day and assign operators."""
        res = registry.execute(
            "plan_waves",
            date=target_date,
            n_operators=n_operators,
            algorithm=algorithm,
        )
        data = res.get("data", [])
        assumptions = res.get("assumptions", [])

        tot_units = sum(w.get("n_units", 0) for w in data)
        tot_travel = sum(w.get("estimated_travel", 0.0) for w in data)
        tot_hours = sum(w.get("estimated_time_s", 0.0) for w in data) / 3600.0

        return WaveOutput(
            date=target_date,
            algorithm=algorithm,
            n_waves=len(data),
            total_units=tot_units,
            total_travel_units=round(tot_travel, 1),
            total_picking_hours=round(tot_hours, 2),
            waves_summary=data[:10],
            summary=res.get("summary", f"Planned {len(data)} waves on {target_date}."),
            assumptions=assumptions,
        )

