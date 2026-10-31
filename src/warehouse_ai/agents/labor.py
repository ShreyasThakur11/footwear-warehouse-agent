"""LaborAgent: solves daily workforce sizing, shift capacity, and overtime risk."""

from __future__ import annotations

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.agents.schemas import LaborOutput
from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient


class LaborAgent(BaseAgent):
    """Specialist agent for workforce staffing, capacity planning, and labor cost optimization."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="LaborAgent",
            role="Workforce Staffing & Industrial Engineering Specialist",
            prompt_filename="labor.md",
            llm_client=llm_client,
            provider=provider,
        )

    def optimize_staffing(
        self,
        target_date: str,
        units: float,
        lines: float,
        orders: float,
        replenishment_hours: float = 0.0,
    ) -> LaborOutput:
        """Calculate workload hours and solve optimal headcount roster."""
        # 1. Estimate workload hours
        workload_res = registry.execute(
            "estimate_workload_hours",
            units=int(units),
            lines=int(lines),
            orders=int(orders),
        )
        base_hours = workload_res.get("data", {}).get("estimated_labor_hours", 12.4)
        total_workload = base_hours + replenishment_hours

        # 2. Recommend headcount via MILP
        staff_res = registry.execute(
            "recommend_headcount",
            workload_hours=total_workload,
            date=target_date,
        )
        data = staff_res.get("data", {})
        assumptions = staff_res.get("assumptions", [])

        perm = data.get("permanent_headcount", 2)
        temp = data.get("recommended_temp_headcount", 0)
        tot = data.get("total_headcount", perm + temp)
        sched_h = data.get("scheduled_hours", tot * 7.5)
        util = data.get("utilization", total_workload / max(1.0, sched_h))
        cost = data.get("estimated_daily_cost", perm * 180.0 + temp * 150.0)
        risk = data.get("shortfall_risk", "LOW")
        expl = data.get("explanation", staff_res.get("summary", "Headcount sized to complete picking before 17:00 cutoff."))

        return LaborOutput(
            date=target_date,
            required_workload_hours=round(total_workload, 2),
            permanent_headcount=perm,
            temp_headcount=temp,
            total_headcount=tot,
            scheduled_hours=round(sched_h, 1),
            expected_utilization=round(util, 3),
            estimated_daily_cost_cad=round(cost, 2),
            shortfall_risk=risk,
            recommendation=expl,
            assumptions=assumptions,
        )

