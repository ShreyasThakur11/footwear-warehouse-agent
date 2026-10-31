"""ReplenishmentAgent: plans forward pick-face restocking from upper reserve racks."""

from __future__ import annotations

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.agents.schemas import ReplenishmentOutput
from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient


class ReplenishmentAgent(BaseAgent):
    """Specialist agent for multi-echelon inventory replenishment and stockout prevention."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="ReplenishmentAgent",
            role="Multi-Echelon Inventory & Replenishment Specialist",
            prompt_filename="replenishment.md",
            llm_client=llm_client,
            provider=provider,
        )

    def generate_plan(
        self,
        target_date: str,
        policy_name: str = "abc_xyz_optimized",
    ) -> ReplenishmentOutput:
        """Generate prioritized replenishment task proposals."""
        res = registry.execute(
            "get_replenishment_plan",
            policy_name=policy_name,
            review_date=target_date,
        )
        data = res.get("data", {}) or {}
        assumptions = res.get("assumptions", [])

        transfers = data.get("pick_face_transfers", [])
        pos = data.get("supplier_purchase_orders", [])
        transfer_units = data.get("total_transfer_units", 0.0)
        po_units = data.get("total_po_units", 0.0)

        tot_units = float(transfer_units + po_units)
        skus_count = len(transfers) + len(pos)

        # Select top priority tasks
        priority = (transfers + pos)[:15]

        return ReplenishmentOutput(
            review_date=target_date,
            policy_name=policy_name,
            total_replenishment_units=tot_units,
            skus_to_replenish=skus_count,
            priority_moves=priority,
            summary=res.get("summary", f"Replenishment scheduled for {target_date}."),
            assumptions=assumptions,
        )
