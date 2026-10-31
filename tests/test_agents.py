"""Unit tests for LangGraph multi-agent daily planning cycle and specialist agents."""

from __future__ import annotations

from warehouse_ai.agents.copilot import CopilotAgent
from warehouse_ai.agents.exception import ExceptionAgent
from warehouse_ai.agents.forecast import ForecastAgent
from warehouse_ai.agents.labor import LaborAgent
from warehouse_ai.agents.orchestrator import run_daily_cycle
from warehouse_ai.agents.replenishment import ReplenishmentAgent
from warehouse_ai.agents.slotting import SlottingAgent
from warehouse_ai.agents.wave import WaveAgent


def test_forecast_agent():
    agent = ForecastAgent()
    out = agent.forecast_for_date("2023-09-15", horizon_days=7)
    assert out.date == "2023-09-15"
    assert out.horizon_days == 7
    assert out.expected_units_p50 > 0
    assert len(out.key_drivers) > 0


def test_labor_agent():
    agent = LaborAgent()
    out = agent.optimize_staffing(target_date="2023-09-15", units=1200, lines=600, orders=170)
    assert out.date == "2023-09-15"
    assert out.total_headcount >= 2
    assert out.required_workload_hours > 0
    assert out.estimated_daily_cost_cad > 0


def test_replenishment_agent():
    agent = ReplenishmentAgent()
    out = agent.generate_plan(target_date="2023-09-15")
    assert out.review_date == "2023-09-15"
    assert out.skus_to_replenish >= 0
    assert out.policy_name == "abc_xyz_optimized"


def test_slotting_agent():
    agent = SlottingAgent()
    out = agent.optimize_slotting(top_n=10)
    assert out.top_n_moves <= 10
    assert out.expected_weekly_travel_saved_m >= 0


def test_wave_agent():
    agent = WaveAgent()
    out = agent.plan_first_waves(target_date="2023-09-15", n_operators=4)
    assert out.date == "2023-09-15"
    assert out.n_waves > 0
    assert out.total_units > 0


def test_exception_agent():
    agent = ExceptionAgent()
    out = agent.triage_exceptions(target_date="2023-09-15")
    assert out.total_exceptions >= 0


def test_copilot_agent():
    agent = CopilotAgent()
    response = agent.answer_query("What is the demand forecast for tomorrow?")
    assert len(response) > 0


def test_full_daily_cycle_orchestration():
    state = run_daily_cycle(target_date="2023-09-15", provider="mock", is_weekly=False)
    assert state.forecast is not None
    assert state.labor is not None
    assert state.replenishment is not None
    assert state.waves is not None
    assert state.exceptions is not None
    assert state.slotting is None  # Daily cycle omits slotting
    assert state.governance_status in ("APPROVED", "REQUIRES_SUPERVISOR_OVERRIDE")
    assert state.final_plan is not None
    assert state.final_plan["date"] == "2023-09-15"


def test_full_weekly_cycle_orchestration():
    state = run_daily_cycle(target_date="2023-09-15", provider="mock", is_weekly=True)
    assert state.slotting is not None  # Weekly cycle includes slotting
    assert state.slotting.top_n_moves > 0
    assert state.final_plan is not None
    assert state.final_plan["slotting"] is not None
