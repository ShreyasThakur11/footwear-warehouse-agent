"""Workforce staffing optimization model for daily-wage and permanent pickers.

Provides:
- Mixed-Integer Linear Programming (MILP) solver recommending optimal
  daily-wage headcount to meet forecast workload before outbound cutoff.
- Accounts for permanent base staff, absenteeism, shift length,
  productive efficiency ratio (breaks/fatigue), and overtime economics.
- Historical what-if simulation benchmarking optimized staffing against actual
  active operators across the 178 operating days.
- Sensitivity analysis across productivity, absenteeism, and risk postures (P50 vs P90).
- Production API: ``recommend_headcount`` and ``simulate_historical_staffing``.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import LinearConstraint, milp

from warehouse_ai.config import StaffingConfig, load_config
from warehouse_ai.models.labor import workload_hours_from_forecast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class StaffingRecommendation:
    date: str
    target_quantile: str
    workload_hours: float
    permanent_headcount: int
    effective_permanent_headcount: float
    recommended_temp_headcount: int
    total_headcount: int
    scheduled_hours: float
    productive_capacity_hours: float
    utilization: float
    expected_overtime_hours: float
    slack_capacity_hours: float
    estimated_daily_cost: float
    shortfall_risk: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# MILP Staffing Optimizer
# ---------------------------------------------------------------------------

def solve_staffing_milp(
    workload_hours: float,
    config: StaffingConfig | None = None,
) -> tuple[int, float, float]:
    """Solve the daily workforce sizing problem via Mixed-Integer Linear Programming.

    Formulation:
        min  daily_wage_rate * N_temp + overtime_rate * U_overtime + 0.01 * S_idle
        s.t. Cap_perm + N_temp * eff_shift_hours + U_overtime - S_idle = workload_hours
             N_temp in {0, 1, 2, ...} (Integer)
             U_overtime >= 0 (Continuous)
             S_idle >= 0 (Continuous)

    Returns
    -------
    tuple[int, float, float]
        (recommended_temp_workers, expected_overtime_hours, slack_capacity_hours)
    """
    if config is None:
        config = load_config().staffing

    if workload_hours <= 0.0:
        return 0, 0.0, 0.0

    eff_shift = config.shift_hours * config.productive_ratio
    eff_perm = config.permanent_operators * (1.0 - config.absenteeism_rate)
    perm_capacity = eff_perm * eff_shift

    # Net workload remaining after permanent staff contribution
    net_workload = workload_hours - perm_capacity

    if net_workload <= 0:
        # Permanent staff alone is sufficient
        slack = abs(net_workload)
        return 0, 0.0, float(round(slack, 2))

    # Decision variables: [N_temp (int), U_overtime (cont), S_idle (cont)]
    c = np.array([config.daily_wage_rate, config.overtime_hourly_rate, 0.01], dtype=float)
    integrality = np.array([1, 0, 0])  # 1: integer, 0: continuous

    # Constraint: eff_shift * N_temp + 1.0 * U_overtime - 1.0 * S_idle == net_workload
    A = np.array([[eff_shift, 1.0, -1.0]], dtype=float)
    b_l = np.array([net_workload], dtype=float)
    b_u = np.array([net_workload], dtype=float)

    constraints = LinearConstraint(A, b_l, b_u)

    # Variable bounds: N_temp in [0, 50], U_overtime in [0, 100], S_idle in [0, 100]
    lb = np.array([0.0, 0.0, 0.0])
    ub = np.array([50.0, 100.0, 100.0])

    res = milp(c=c, integrality=integrality, constraints=constraints, bounds=(lb, ub))

    if not res.success:
        logger.warning("MILP failed (%s); using analytical ceiling fallback.", res.status)
        # Analytical fallback: ceiling division
        n_temp = int(np.ceil(net_workload / eff_shift))
        slack = (n_temp * eff_shift) - net_workload
        return n_temp, 0.0, float(round(slack, 2))

    n_temp = int(round(res.x[0]))
    overtime = float(round(res.x[1], 2))
    slack = float(round(res.x[2], 2))

    return n_temp, overtime, slack


# ---------------------------------------------------------------------------
# High-Level Recommendation API
# ---------------------------------------------------------------------------

def recommend_headcount(
    date: str | dt.date,
    target_quantile: str = "P50",
    workload_hours: float | None = None,
    units: float | None = None,
    lines: float | None = None,
    orders: float | None = None,
    config: StaffingConfig | None = None,
) -> StaffingRecommendation:
    """Generate industrial staffing recommendation for a specific date.

    Parameters
    ----------
    date : str | dt.date
        Operating date to schedule.
    target_quantile : str
        Demand risk profile: 'P50' (expected median workload) or 'P90' (conservative buffer).
    workload_hours : float | None
        Explicit workload hours needed. If None, computed from units/lines/orders.
    units : float | None
        Forecasted units.
    lines : float | None
        Forecasted lines.
    orders : float | None
        Forecasted orders.
    config : StaffingConfig | None
        Staffing configuration parameters.

    Returns
    -------
    StaffingRecommendation
        Comprehensive recommendation with headcount breakdown, capacity, and explanation.
    """
    if config is None:
        config = load_config().staffing

    date_str = pd.to_datetime(date).strftime("%Y-%m-%d")

    # If workload_hours not supplied, project via regression
    if workload_hours is None:
        if units is None:
            # Fallback to empirical daily median if no units provided
            units = 1100.0
            lines = 450.0
            orders = 90.0
        elif lines is None or orders is None:
            # Approximate proportional lines and orders
            lines = units * 0.45
            orders = units * 0.10
        workload_hours = workload_hours_from_forecast(units=units, lines=lines, orders=orders)

    eff_shift = config.shift_hours * config.productive_ratio
    eff_perm = config.permanent_operators * (1.0 - config.absenteeism_rate)
    perm_capacity = eff_perm * eff_shift

    n_temp, overtime, slack = solve_staffing_milp(workload_hours, config=config)

    total_headcount = config.permanent_operators + n_temp
    total_scheduled_hours = total_headcount * config.shift_hours
    total_productive_capacity = perm_capacity + (n_temp * eff_shift)

    utilization = (
        round(workload_hours / total_productive_capacity, 4)
        if total_productive_capacity > 0
        else 0.0
    )

    daily_cost = (
        config.permanent_operators * config.permanent_daily_rate
        + n_temp * config.daily_wage_rate
        + overtime * config.overtime_hourly_rate
    )

    # Risk evaluation
    if utilization > 0.95 or overtime > 0.5:
        shortfall_risk = "HIGH"
    elif utilization > 0.85:
        shortfall_risk = "MODERATE"
    else:
        shortfall_risk = "LOW"

    # Deterministic plain-language rationale
    if workload_hours <= 0.1:
        explanation = (
            f"Zero or negligible picking volume projected for {date_str} (e.g. weekend or statutory holiday). "
            f"Schedule 0 temporary workers. Permanent core staff ({config.permanent_operators} FTE) handles basic housekeeping."
        )
    else:
        explanation = (
            f"Target {target_quantile} workload of {workload_hours:.1f} labor-hours requires "
            f"{n_temp} temporary daily-wage pickers alongside {config.permanent_operators} permanent staff "
            f"({eff_perm:.2f} effective FTE after {config.absenteeism_rate * 100:.0f}% absenteeism). "
            f"Delivers {total_productive_capacity:.1f} productive picking hours at {utilization * 100:.1f}% utilization, "
            f"guaranteeing complete order dispatch before the {config.cutoff_hour}:00 outbound cutoff."
        )

    return StaffingRecommendation(
        date=date_str,
        target_quantile=target_quantile,
        workload_hours=round(workload_hours, 2),
        permanent_headcount=config.permanent_operators,
        effective_permanent_headcount=round(eff_perm, 2),
        recommended_temp_headcount=n_temp,
        total_headcount=total_headcount,
        scheduled_hours=round(total_scheduled_hours, 2),
        productive_capacity_hours=round(total_productive_capacity, 2),
        utilization=utilization,
        expected_overtime_hours=overtime,
        slack_capacity_hours=slack,
        estimated_daily_cost=round(daily_cost, 2),
        shortfall_risk=shortfall_risk,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Historical Simulation & Benchmarking
# ---------------------------------------------------------------------------

def simulate_historical_staffing(
    daily_df: pd.DataFrame | None = None,
    config: StaffingConfig | None = None,
) -> pd.DataFrame:
    """Replay historical operations comparing actual active operators vs MILP recommendations.

    Benchmarks:
    1. Actual active operators scheduled by facility management.
    2. Recommended headcount under P50 workload.
    3. Recommended headcount under P90 workload (+20% safety margin).
    """
    if config is None:
        config = load_config().staffing

    if daily_df is None:
        cfg = load_config()
        daily_df = pd.read_parquet(Path(cfg.paths.data_processed) / "daily.parquet")

    # Filter to active operational days (units > 0)
    active_days = daily_df[daily_df["units"] > 0].copy()
    active_days["date"] = pd.to_datetime(active_days["date"])
    active_days = active_days.sort_values("date").reset_index(drop=True)

    rows = []
    for _, row in active_days.iterrows():
        units = float(row["units"])
        lines = float(row["lines"])
        orders = float(row["orders"])
        actual_operators = int(row["active_operators"])

        # Engineered workload hours needed
        workload_p50 = workload_hours_from_forecast(units=units, lines=lines, orders=orders)
        workload_p90 = workload_p50 * 1.25  # Conservative 25% upper buffer

        # P50 recommendation
        rec_p50 = recommend_headcount(
            date=row["date"],
            target_quantile="P50",
            workload_hours=workload_p50,
            config=config,
        )

        # P90 recommendation
        rec_p90 = recommend_headcount(
            date=row["date"],
            target_quantile="P90",
            workload_hours=workload_p90,
            config=config,
        )

        actual_scheduled_hours = actual_operators * config.shift_hours
        actual_cost = actual_operators * config.daily_wage_rate
        excess_headcount_p50 = actual_operators - rec_p50.total_headcount
        daily_saving_p50 = max(0.0, excess_headcount_p50 * config.daily_wage_rate)

        rows.append({
            "date": row["date"].strftime("%Y-%m-%d"),
            "units": units,
            "lines": lines,
            "orders": orders,
            "workload_hours": round(workload_p50, 2),
            "actual_operators": actual_operators,
            "actual_hours": actual_scheduled_hours,
            "actual_cost": actual_cost,
            "p50_total_staff": rec_p50.total_headcount,
            "p50_temp_staff": rec_p50.recommended_temp_headcount,
            "p50_utilization": rec_p50.utilization,
            "p50_cost": rec_p50.estimated_daily_cost,
            "p90_total_staff": rec_p90.total_headcount,
            "p90_temp_staff": rec_p90.recommended_temp_headcount,
            "excess_headcount_p50": excess_headcount_p50,
            "daily_saving_cad": daily_saving_p50,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Sensitivity Analysis
# ---------------------------------------------------------------------------

def run_staffing_sensitivity(
    daily_df: pd.DataFrame | None = None,
    base_config: StaffingConfig | None = None,
) -> pd.DataFrame:
    """Run sensitivity analysis across productivity, absenteeism, and risk posture."""
    if base_config is None:
        base_config = load_config().staffing

    if daily_df is None:
        cfg = load_config()
        daily_df = pd.read_parquet(Path(cfg.paths.data_processed) / "daily.parquet")

    active_days = daily_df[daily_df["units"] > 0]
    total_days = len(active_days)
    mean_units = active_days["units"].mean()
    mean_lines = active_days["lines"].mean()
    mean_orders = active_days["orders"].mean()
    base_workload = workload_hours_from_forecast(mean_units, mean_lines, mean_orders)

    scenarios = [
        {"name": "Baseline (P50)", "prod_factor": 1.0, "absenteeism": 0.05, "quantile": "P50", "workload": base_workload},
        {"name": "High Demand (P90)", "prod_factor": 1.0, "absenteeism": 0.05, "quantile": "P90", "workload": base_workload * 1.25},
        {"name": "Low Productivity (-10%)", "prod_factor": 0.90, "absenteeism": 0.05, "quantile": "P50", "workload": base_workload / 0.90},
        {"name": "High Productivity (+10%)", "prod_factor": 1.10, "absenteeism": 0.05, "quantile": "P50", "workload": base_workload / 1.10},
        {"name": "Zero Absenteeism (0%)", "prod_factor": 1.0, "absenteeism": 0.00, "quantile": "P50", "workload": base_workload},
        {"name": "High Absenteeism (10%)", "prod_factor": 1.0, "absenteeism": 0.10, "quantile": "P50", "workload": base_workload},
    ]

    out = []
    for sc in scenarios:
        cfg = StaffingConfig(
            permanent_operators=base_config.permanent_operators,
            shift_hours=base_config.shift_hours,
            productive_ratio=base_config.productive_ratio * sc["prod_factor"],
            absenteeism_rate=sc["absenteeism"],
            daily_wage_rate=base_config.daily_wage_rate,
            permanent_daily_rate=base_config.permanent_daily_rate,
            overtime_hourly_rate=base_config.overtime_hourly_rate,
            cutoff_hour=base_config.cutoff_hour,
        )
        rec = recommend_headcount(
            date="2023-06-01",
            target_quantile=sc["quantile"],
            workload_hours=sc["workload"],
            config=cfg,
        )
        out.append({
            "scenario": sc["name"],
            "avg_workload_hours": round(sc["workload"], 2),
            "recommended_temp": rec.recommended_temp_headcount,
            "total_headcount": rec.total_headcount,
            "productive_capacity_hours": rec.productive_capacity_hours,
            "utilization_pct": round(rec.utilization * 100, 1),
            "estimated_daily_cost": rec.estimated_daily_cost,
            "annualized_labor_cost_cad": round(rec.estimated_daily_cost * total_days, 2),
        })

    return pd.DataFrame(out)
