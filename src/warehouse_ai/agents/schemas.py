"""Pydantic data schemas for agent outputs and shared orchestration state."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ForecastOutput(BaseModel):
    """Structured output from ForecastAgent."""

    date: str
    horizon_days: int = 14
    expected_units_p50: float
    p10_units: float
    p90_units: float
    expected_lines: float
    expected_orders: float
    key_drivers: list[str] = Field(default_factory=list)
    summary: str
    assumptions: list[str] = Field(default_factory=list)


class LaborOutput(BaseModel):
    """Structured output from LaborAgent."""

    date: str
    required_workload_hours: float
    permanent_headcount: int
    temp_headcount: int
    total_headcount: int
    scheduled_hours: float
    expected_utilization: float
    estimated_daily_cost_cad: float
    shortfall_risk: str
    recommendation: str
    assumptions: list[str] = Field(default_factory=list)


class ReplenishmentOutput(BaseModel):
    """Structured output from ReplenishmentAgent."""

    review_date: str
    policy_name: str = "abc_xyz_optimized"
    total_replenishment_units: float
    skus_to_replenish: int
    priority_moves: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    assumptions: list[str] = Field(default_factory=list)


class SlottingOutput(BaseModel):
    """Structured output from SlottingAgent."""

    top_n_moves: int
    expected_weekly_travel_saved_m: float
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    assumptions: list[str] = Field(default_factory=list)


class WaveOutput(BaseModel):
    """Structured output from WaveAgent."""

    date: str
    algorithm: str = "seed_savings"
    n_waves: int
    total_units: int
    total_travel_units: float
    total_picking_hours: float
    waves_summary: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    assumptions: list[str] = Field(default_factory=list)


class ExceptionOutput(BaseModel):
    """Structured output from ExceptionAgent."""

    total_exceptions: int
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    critical_exceptions: list[dict[str, Any]] = Field(default_factory=list)
    triage_summary: str
    assumptions: list[str] = Field(default_factory=list)


class DailyPlanState(BaseModel):
    """Shared state object passed through LangGraph agentic workflow nodes."""

    run_date: str
    provider: str = "mock"
    is_weekly: bool = False
    forecast: Optional[ForecastOutput] = None
    labor: Optional[LaborOutput] = None
    replenishment: Optional[ReplenishmentOutput] = None
    slotting: Optional[SlottingOutput] = None
    waves: Optional[WaveOutput] = None
    exceptions: Optional[ExceptionOutput] = None
    conflict_resolution: Optional[dict[str, Any]] = None
    governance_status: str = "PENDING"
    governance_notes: list[str] = Field(default_factory=list)
    final_plan: Optional[dict[str, Any]] = None
    errors: list[str] = Field(default_factory=list)
