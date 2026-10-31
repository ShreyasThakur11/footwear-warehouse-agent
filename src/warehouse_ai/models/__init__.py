"""Warehouse modeling modules for labor, travel, forecasting, staffing, classification, replenishment, waves, and anomaly."""

from warehouse_ai.models.anomaly import (
    AnomalyThresholds,
    ExceptionRecord,
    check_forecast_breaches,
    check_operator_productivity_outliers,
    check_policy_location_mismatch,
    check_short_and_over_picks,
    check_unknown_master_data,
    detect_wave_statistical_anomalies,
    exceptions_to_dataframe,
    scan_all_exceptions,
)
from warehouse_ai.models.classification import (
    audit_catalog_abc,
    compute_abc,
    compute_abc_xyz,
    compute_xyz,
)
from warehouse_ai.models.forecasting import (
    HoltWintersForecaster,
    QuantileGradientBoostingForecaster,
    SeasonalNaiveForecaster,
    WeekdayAverageForecaster,
    compute_hourly_profile,
    croston_sba,
    disaggregate_daily_to_hourly,
    forecast_daily,
    forecast_sku_size,
    run_rolling_backtest,
)
from warehouse_ai.models.labor import (
    LaborModel,
    day_workload_hours,
    get_labor_model,
    wave_time,
    workload_hours_from_forecast,
)
from warehouse_ai.models.replenishment import (
    ABC_XYZ_OPTIMIZED_POLICY,
    HIGH_SERVICE_POLICY,
    LEAN_JIT_POLICY,
    calculate_sku_targets,
    replenishment_plan,
    simulate_replenishment_policies,
    simulate_replenishment_policy,
)
from warehouse_ai.models.slotting import (
    PolicySummary,
    ReslottingProposal,
    compare_all_policies,
    compute_co_picking_pairs,
    generate_coi_slotting,
    recommend_reslotting,
    simulate_storage_policy,
)
from warehouse_ai.models.staffing import (
    StaffingRecommendation,
    recommend_headcount,
    run_staffing_sensitivity,
    simulate_historical_staffing,
    solve_staffing_milp,
)
from warehouse_ai.models.travel import (
    build_warehouse_graph,
    compute_all_wave_travel,
    precompute_distance_matrix,
    route_length,
    shortest_distance,
    wave_travel,
)
from warehouse_ai.models.waves import (
    DayEvaluation,
    WavePlan,
    batch_aisle_cluster,
    batch_fcfs,
    batch_seed_savings,
    evaluate_on_historical_days,
    plan_waves,
    replay_historical_waves,
)

__all__ = [
    # Labor
    "LaborModel",
    "get_labor_model",
    "wave_time",
    "day_workload_hours",
    "workload_hours_from_forecast",
    # Travel
    "build_warehouse_graph",
    "precompute_distance_matrix",
    "shortest_distance",
    "route_length",
    "wave_travel",
    "compute_all_wave_travel",
    # Forecasting
    "SeasonalNaiveForecaster",
    "WeekdayAverageForecaster",
    "HoltWintersForecaster",
    "QuantileGradientBoostingForecaster",
    "compute_hourly_profile",
    "disaggregate_daily_to_hourly",
    "croston_sba",
    "forecast_sku_size",
    "run_rolling_backtest",
    "forecast_daily",
    # Staffing
    "StaffingRecommendation",
    "solve_staffing_milp",
    "recommend_headcount",
    "simulate_historical_staffing",
    "run_staffing_sensitivity",
    # Classification
    "compute_abc",
    "compute_xyz",
    "compute_abc_xyz",
    "audit_catalog_abc",
    # Replenishment
    "LEAN_JIT_POLICY",
    "HIGH_SERVICE_POLICY",
    "ABC_XYZ_OPTIMIZED_POLICY",
    "calculate_sku_targets",
    "simulate_replenishment_policy",
    "simulate_replenishment_policies",
    "replenishment_plan",
    # Slotting (models layer)
    "PolicySummary",
    "ReslottingProposal",
    "compare_all_policies",
    "compute_co_picking_pairs",
    "generate_coi_slotting",
    "simulate_storage_policy",
    "recommend_reslotting",
    # Waves & batching
    "WavePlan",
    "DayEvaluation",
    "replay_historical_waves",
    "batch_fcfs",
    "batch_seed_savings",
    "batch_aisle_cluster",
    "plan_waves",
    "evaluate_on_historical_days",
    # Anomaly detection & exceptions
    "ExceptionRecord",
    "AnomalyThresholds",
    "check_short_and_over_picks",
    "check_policy_location_mismatch",
    "check_unknown_master_data",
    "check_forecast_breaches",
    "check_operator_productivity_outliers",
    "detect_wave_statistical_anomalies",
    "scan_all_exceptions",
    "exceptions_to_dataframe",
]
