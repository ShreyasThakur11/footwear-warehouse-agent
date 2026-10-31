"""Unit tests for warehouse labor model, wave time, and workload forecasting."""

import pandas as pd
import pytest

from warehouse_ai.models.labor import (
    LaborModel,
    wave_time,
    workload_hours_from_forecast,
)


@pytest.fixture
def synthetic_wave():
    """Synthetic wave record with known attributes."""
    return {
        "wave_id": 101,
        "travel_dist": 100.0,  # 100 metres
        "n_distinct_locations": 5,
        "n_units": 10,
        "z_excess": 2,
        "date": "2023-05-10",
        "operator": "Operator_A",
    }


@pytest.fixture
def synthetic_waves_df():
    """Small DataFrame of synthetic waves."""
    return pd.DataFrame([
        {
            "wave_id": 1,
            "travel_dist": 100.0,
            "n_distinct_locations": 5,
            "n_units": 10,
            "z_excess": 0,
            "date": "2023-01-01",
            "operator": "Op_1",
        },
        {
            "wave_id": 2,
            "travel_dist": 200.0,
            "n_distinct_locations": 8,
            "n_units": 20,
            "z_excess": 4,
            "date": "2023-01-01",
            "operator": "Op_1",
        },
        {
            "wave_id": 3,
            "travel_dist": 150.0,
            "n_distinct_locations": 6,
            "n_units": 15,
            "z_excess": 1,
            "date": "2023-01-02",
            "operator": "Op_2",
        },
    ])


@pytest.fixture
def synthetic_daily_df():
    """Synthetic daily aggregated table."""
    return pd.DataFrame([
        {"date": "2023-01-01", "units": 30, "lines": 25, "orders": 5, "active_operators": 2},
        {"date": "2023-01-02", "units": 15, "lines": 12, "orders": 3, "active_operators": 1},
        {"date": "2023-01-03", "units": 45, "lines": 35, "orders": 8, "active_operators": 3},
        {"date": "2023-01-04", "units": 60, "lines": 50, "orders": 10, "active_operators": 4},
        {"date": "2023-01-05", "units": 20, "lines": 18, "orders": 4, "active_operators": 2},
    ])


def test_wave_time_exact_calculation(synthetic_wave):
    model = LaborModel(
        walk_speed_mps=1.0,
        setup_per_wave_s=60.0,
        per_location_stop_s=10.0,
        per_unit_handling_s=6.0,
        level_penalty_s=5.0,
        calibration_scale=1.0,
    )
    # Expected:
    # Setup = 60
    # Travel = 100 / 1.0 = 100
    # Stops = 5 * 10 = 50
    # Units = 10 * 6 = 60
    # Level = 2 * 5 = 10
    # Total = 60 + 100 + 50 + 60 + 10 = 280.0 s
    t_sec = model.wave_time(synthetic_wave, dist_is_meters=True)
    assert t_sec == 280.0

    # Breakdown verification
    bd = model.wave_time(synthetic_wave, dist_is_meters=True, breakdown=True)
    assert bd["total_seconds"] == 280.0
    assert bd["total_minutes"] == round(280.0 / 60.0, 2)
    assert bd["walk_s"] == 100.0
    assert bd["setup_s"] == 60.0
    assert bd["stop_s"] == 50.0
    assert bd["pick_s"] == 60.0
    assert bd["level_s"] == 10.0


def test_wave_time_calibration_scaling(synthetic_wave):
    model = LaborModel(calibration_scale=1.5)
    t_uncal = model.wave_time(synthetic_wave, dist_is_meters=True, apply_calibration=False)
    t_cal = model.wave_time(synthetic_wave, dist_is_meters=True, apply_calibration=True)
    assert t_cal == pytest.approx(t_uncal * 1.5, rel=1e-5)


def test_convenience_functions(synthetic_wave):
    t_sec = wave_time(synthetic_wave, dist_is_meters=True)
    assert t_sec > 0.0

    forecast_h = workload_hours_from_forecast(units=1000, lines=500, orders=100)
    assert forecast_h > 0.0


def test_day_workload_hours(synthetic_waves_df):
    model = LaborModel(calibration_scale=1.0)
    h = model.day_workload_hours("2023-01-01", synthetic_waves_df)
    assert h > 0.0
    # Date 2023-01-01 has 2 small waves; should be between 0.05 and 0.5 hours
    assert 0.05 <= h <= 0.5


def test_workload_forecast_regression_interface(synthetic_daily_df, synthetic_waves_df):
    model = LaborModel()
    metrics = model.fit_forecast_model(synthetic_daily_df, waves_df=synthetic_waves_df)
    assert "r2" in metrics
    assert "mae" in metrics
    assert "rmse" in metrics
    assert metrics["r2"] >= 0.0

    # Test prediction
    pred_h = model.workload_hours_from_forecast(units=50, lines=40, orders=8)
    assert pred_h > 0.0
    assert isinstance(pred_h, float)


def test_implied_productivity_and_staffing(synthetic_waves_df, synthetic_daily_df):
    model = LaborModel()
    op_prod, overall_uph = model.implied_productivity(synthetic_waves_df)
    assert overall_uph > 0.0
    assert len(op_prod) == 2
    assert "units_per_hour" in op_prod.columns

    staff = model.staffing_analysis(synthetic_daily_df, synthetic_waves_df)
    assert "utilization" in staff.columns
    assert "staffing_status" in staff.columns
    assert set(staff["staffing_status"]).issubset({"Over-staffed", "Balanced", "Under-staffed"})
