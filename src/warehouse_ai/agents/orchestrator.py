"""LangGraph-powered multi-agent daily planning orchestrator.

Coordinates autonomous specialist agents across the daily operational cycle:
    load_data
       ↓
    ForecastAgent
       ↓
    LaborAgent
       ↓
    ReplenishmentAgent
       ↓
    WaveAgent
       ↓
    (SlottingAgent - weekly cycle)
       ↓
    ExceptionAgent
       ↓
    conflict_check (re-balance labor if replenishment clashes with peak picking)
       ↓
    governance_gate
       ↓
    DailyPlan output
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from warehouse_ai.agents.exception import ExceptionAgent
from warehouse_ai.agents.forecast import ForecastAgent
from warehouse_ai.agents.labor import LaborAgent
from warehouse_ai.agents.replenishment import ReplenishmentAgent
from warehouse_ai.agents.schemas import DailyPlanState
from warehouse_ai.agents.slotting import SlottingAgent
from warehouse_ai.agents.wave import WaveAgent
from warehouse_ai.llm.client import get_llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node Functions
# ---------------------------------------------------------------------------

def load_data_node(state: DailyPlanState) -> dict[str, Any]:
    """Validate target execution date and initialize orchestration context."""
    logger.info("Initializing Daily Cycle orchestration for %s (provider=%s)...", state.run_date, state.provider)
    return {
        "governance_status": "IN_PROGRESS",
        "governance_notes": [f"Daily cycle initialized for operational date {state.run_date}."],
    }


def forecast_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute ForecastAgent volume projection."""
    client = get_llm_client(provider=state.provider)
    agent = ForecastAgent(llm_client=client)
    out = agent.forecast_for_date(target_date=state.run_date, horizon_days=14)
    return {"forecast": out}


def labor_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute LaborAgent initial headcount sizing."""
    client = get_llm_client(provider=state.provider)
    agent = LaborAgent(llm_client=client)

    units = state.forecast.expected_units_p50 if state.forecast else 1250.0
    lines = state.forecast.expected_lines if state.forecast else 672.0
    orders = state.forecast.expected_orders if state.forecast else 178.0

    out = agent.optimize_staffing(
        target_date=state.run_date,
        units=units,
        lines=lines,
        orders=orders,
        replenishment_hours=0.0,
    )
    return {"labor": out}


def replenishment_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute ReplenishmentAgent pick-face restocking plan."""
    client = get_llm_client(provider=state.provider)
    agent = ReplenishmentAgent(llm_client=client)
    out = agent.generate_plan(target_date=state.run_date, policy_name="abc_xyz_optimized")
    return {"replenishment": out}


def wave_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute WaveAgent morning order batching and picker assignment."""
    client = get_llm_client(provider=state.provider)
    agent = WaveAgent(llm_client=client)
    n_ops = state.labor.total_headcount if state.labor else 5
    out = agent.plan_first_waves(target_date=state.run_date, n_operators=n_ops, algorithm="seed_savings")
    return {"waves": out}


def slotting_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute SlottingAgent weekly layout re-slotting proposals."""
    if not state.is_weekly:
        return {}
    client = get_llm_client(provider=state.provider)
    agent = SlottingAgent(llm_client=client)
    out = agent.optimize_slotting(top_n=20)
    return {"slotting": out}


def exception_node(state: DailyPlanState) -> dict[str, Any]:
    """Execute ExceptionAgent operational anomaly triage."""
    client = get_llm_client(provider=state.provider)
    agent = ExceptionAgent(llm_client=client)
    out = agent.triage_exceptions(target_date=state.run_date)
    return {"exceptions": out}


def conflict_check_node(state: DailyPlanState) -> dict[str, Any]:
    """Check for operational labor conflicts between peak picking and replenishment."""
    notes: list[str] = list(state.governance_notes)
    replenish_units = state.replenishment.total_replenishment_units if state.replenishment else 0.0

    # Rule: If replenishment > 200 units, forklift moves consume labor (estimated 15s per unit move = 0.0042 h/unit)
    conflict_detected = replenish_units > 200.0
    extra_labor_hours = round(replenish_units * 0.0042, 2) if conflict_detected else 0.0

    resolution = {
        "conflict_detected": conflict_detected,
        "replenishment_units": replenish_units,
        "extra_replenishment_hours": extra_labor_hours,
        "action": "Schedule replenishment during off-peak window (12:30–14:00) or add flex staffing.",
    }

    if conflict_detected:
        notes.append(
            f"Labor Conflict Detected: {replenish_units:,.0f} replenishment units require {extra_labor_hours:.2f}h. "
            "Re-running LaborAgent with combined picking + replenishment workload."
        )
        # Re-solve labor with replenishment hours included
        client = get_llm_client(provider=state.provider)
        agent = LaborAgent(llm_client=client)
        units = state.forecast.expected_units_p50 if state.forecast else 1250.0
        lines = state.forecast.expected_lines if state.forecast else 672.0
        orders = state.forecast.expected_orders if state.forecast else 178.0

        updated_labor = agent.optimize_staffing(
            target_date=state.run_date,
            units=units,
            lines=lines,
            orders=orders,
            replenishment_hours=extra_labor_hours,
        )
        return {
            "conflict_resolution": resolution,
            "labor": updated_labor,
            "governance_notes": notes,
        }

    notes.append("No labor conflicts detected; picking and replenishment workloads balanced.")
    return {
        "conflict_resolution": resolution,
        "governance_notes": notes,
    }


def governance_gate_node(state: DailyPlanState) -> dict[str, Any]:
    """Validate all model constraints and approve plan output."""
    notes: list[str] = list(state.governance_notes)

    # Check shortfall risk and exceptions
    high_exceptions = state.exceptions.high_severity_count if state.exceptions else 0
    shortfall = state.labor.shortfall_risk if state.labor else "LOW"

    if shortfall == "HIGH" or high_exceptions > 10:
        status = "REQUIRES_SUPERVISOR_OVERRIDE"
        notes.append(
            f"Governance Alert: Shortfall risk is {shortfall} with {high_exceptions} high-severity exceptions. "
            "Supervisor sign-off required prior to shift release."
        )
    else:
        status = "APPROVED"
        notes.append("All operational safety gates passed. Plan approved for floor execution.")

    # Assemble comprehensive final plan
    final_plan = {
        "date": state.run_date,
        "status": status,
        "forecast": state.forecast.model_dump() if state.forecast else None,
        "labor": state.labor.model_dump() if state.labor else None,
        "replenishment": state.replenishment.model_dump() if state.replenishment else None,
        "waves": state.waves.model_dump() if state.waves else None,
        "slotting": state.slotting.model_dump() if state.slotting else None,
        "exceptions": state.exceptions.model_dump() if state.exceptions else None,
        "conflict_resolution": state.conflict_resolution,
    }

    return {
        "governance_status": status,
        "governance_notes": notes,
        "final_plan": final_plan,
    }


# ---------------------------------------------------------------------------
# Graph Builder
# ---------------------------------------------------------------------------

def build_daily_cycle_graph(is_weekly: bool = False) -> Any:
    """Build and compile the LangGraph StateGraph for the warehouse operational cycle."""
    builder = StateGraph(DailyPlanState)

    # Add Nodes
    builder.add_node("load_data", load_data_node)
    builder.add_node("forecast_agent", forecast_node)
    builder.add_node("labor_agent", labor_node)
    builder.add_node("replenishment_agent", replenishment_node)
    builder.add_node("wave_agent", wave_node)
    builder.add_node("slotting_agent", slotting_node)
    builder.add_node("exception_agent", exception_node)
    builder.add_node("conflict_check", conflict_check_node)
    builder.add_node("governance_gate", governance_gate_node)

    # Add Edges (Linear sequential DAG with conditional weekly branch)
    builder.add_edge(START, "load_data")
    builder.add_edge("load_data", "forecast_agent")
    builder.add_edge("forecast_agent", "labor_agent")
    builder.add_edge("labor_agent", "replenishment_agent")
    builder.add_edge("replenishment_agent", "wave_agent")

    if is_weekly:
        builder.add_edge("wave_agent", "slotting_agent")
        builder.add_edge("slotting_agent", "exception_agent")
    else:
        builder.add_edge("wave_agent", "exception_agent")

    builder.add_edge("exception_agent", "conflict_check")
    builder.add_edge("conflict_check", "governance_gate")
    builder.add_edge("governance_gate", END)

    return builder.compile()


def run_daily_cycle(
    target_date: str,
    provider: str = "mock",
    is_weekly: bool = False,
) -> DailyPlanState:
    """Execute end-to-end multi-agent daily planning cycle for the specified date."""
    graph = build_daily_cycle_graph(is_weekly=is_weekly)
    initial_state = DailyPlanState(
        run_date=target_date,
        provider=provider,
        is_weekly=is_weekly,
    )
    result_dict = graph.invoke(initial_state)
    return DailyPlanState(**result_dict)

