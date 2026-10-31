"""Unit tests for workforce staffing optimization model."""

from __future__ import annotations

import pytest

from warehouse_ai.config import StaffingConfig
from warehouse_ai.models.staffing import (
    recommend_headcount,
    solve_staffing_milp,
)


def test_solve_staffing_milp_tiny_instance():
    # Setup config: 1 permanent operator, 7.5h shift, 1.0 productive ratio, 0% absenteeism
    # Net capacity of permanent = 7.5h
    # Needed workload = 20.0h
    # Net workload = 12.5h
    # Temp worker provides 7.5h each
    # Optimal temp workers = ceil(12.5 / 7.5) = 2 temp workers
    cfg = StaffingConfig(
        permanent_operators=1,
        shift_hours=7.5,
        productive_ratio=1.0,
        absenteeism_rate=0.0,
        daily_wage_rate=150.0,
        permanent_daily_rate=180.0,
        overtime_hourly_rate=35.0,
        cutoff_hour=17,
    )
    n_temp, overtime, slack = solve_staffing_milp(workload_hours=20.0, config=cfg)
    assert n_temp == 2
    assert overtime == 0.0
    # Total capacity = 1 * 7.5 + 2 * 7.5 = 22.5h -> slack = 2.5h
    assert pytest.approx(slack, rel=1e-2) == 2.5


def test_solve_staffing_milp_zero_workload():
    cfg = StaffingConfig()
    n_temp, overtime, slack = solve_staffing_milp(workload_hours=0.0, config=cfg)
    assert n_temp == 0
    assert overtime == 0.0
    assert slack == 0.0


def test_recommend_headcount_api():
    cfg = StaffingConfig(
        permanent_operators=2,
        shift_hours=7.5,
        productive_ratio=0.85,
        absenteeism_rate=0.05,
    )
    rec = recommend_headcount(
        date="2023-06-15",
        target_quantile="P50",
        workload_hours=25.0,
        config=cfg,
    )
    assert rec.permanent_headcount == 2
    assert rec.recommended_temp_headcount > 0
    assert rec.total_headcount == rec.permanent_headcount + rec.recommended_temp_headcount
    assert rec.utilization > 0.0
    assert rec.utilization <= 1.05
    assert "dispatch before the 17:00 outbound cutoff" in rec.explanation
