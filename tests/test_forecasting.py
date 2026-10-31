"""Unit tests for demand forecasting models."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from warehouse_ai.models.forecasting import (
    HoltWintersForecaster,
    QuantileGradientBoostingForecaster,
    SeasonalNaiveForecaster,
    WeekdayAverageForecaster,
    compute_hourly_profile,
    create_daily_features,
    croston_sba,
    is_quebec_holiday,
)


@pytest.fixture
def synthetic_daily_df() -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=60, freq="D")
    # Base weekly cycle with weekend dip
    y = []
    for d in dates:
        if d.dayofweek in [5, 6]:
            y.append(0.0)
        else:
            y.append(float(100 + (d.dayofweek * 20) + (d.day % 10)))
    return pd.DataFrame({"date": dates, "units": y, "lines": [val * 0.4 for val in y], "orders": [val * 0.1 for val in y]})


def test_holiday_detection():
    assert is_quebec_holiday("2023-04-07") is True  # Good Friday
    assert is_quebec_holiday("2023-05-22") is True  # Patriots' Day
    assert is_quebec_holiday("2023-09-04") is True  # Labour Day
    assert is_quebec_holiday("2023-05-15") is False  # Regular Monday


def test_create_daily_features_no_leakage(synthetic_daily_df):
    feat = create_daily_features(synthetic_daily_df, target_col="units")
    assert "lag_1" in feat.columns
    assert "lag_7" in feat.columns
    assert "rolling_mean_7" in feat.columns
    # Check that lag_1 at index 1 matches units at index 0
    assert feat.loc[1, "lag_1"] == synthetic_daily_df.loc[0, "units"]
    assert np.isnan(feat.loc[0, "lag_1"])


def test_seasonal_naive_forecaster(synthetic_daily_df):
    sn = SeasonalNaiveForecaster(season_length=7).fit(synthetic_daily_df["units"].values)
    p10, p50, p90 = sn.predict(horizon=14)
    assert len(p50) == 14
    assert len(p10) == 14
    assert len(p90) == 14
    assert np.all(p10 <= p50)
    assert np.all(p50 <= p90)
    assert np.all(p10 >= 0.0)


def test_weekday_average_forecaster(synthetic_daily_df):
    wa = WeekdayAverageForecaster(weeks=4).fit(synthetic_daily_df["date"].values, synthetic_daily_df["units"].values)
    p10, p50, p90 = wa.predict(start_date="2023-03-02", horizon=7)
    assert len(p50) == 7
    assert np.all(p10 <= p50)
    assert np.all(p50 <= p90)


def test_holt_winters_forecaster(synthetic_daily_df):
    hw = HoltWintersForecaster(seasonal_periods=7).fit(synthetic_daily_df["units"].values)
    p10, p50, p90 = hw.predict(horizon=14)
    assert len(p50) == 14
    assert np.all(p10 <= p50)
    assert np.all(p50 <= p90)


def test_quantile_gradient_boosting_determinism(synthetic_daily_df):
    # Split train and test strictly
    train_df = synthetic_daily_df.iloc[:45]
    test_start = synthetic_daily_df.iloc[45]["date"]

    m1 = QuantileGradientBoostingForecaster(random_seed=42).fit(train_df, target_col="units")
    p10_a, p50_a, p90_a = m1.predict(test_start, horizon=14)

    m2 = QuantileGradientBoostingForecaster(random_seed=42).fit(train_df, target_col="units")
    p10_b, p50_b, p90_b = m2.predict(test_start, horizon=14)

    # Monotonicity
    assert np.all(p10_a <= p50_a)
    assert np.all(p50_a <= p90_a)
    assert np.all(p10_a >= 0.0)

    # Deterministic with seed
    np.testing.assert_allclose(p50_a, p50_b)
    np.testing.assert_allclose(p90_a, p90_b)


def test_compute_hourly_profile():
    # Build tiny hourly dataset
    rows = []
    dates = pd.date_range("2023-01-02", periods=14, freq="D")
    for d in dates:
        for h in range(24):
            # Peak at hour 7 and 11
            u = 50.0 if h in [7, 11] else 0.0
            rows.append({"date": d, "hour": h, "units": u})
    hdf = pd.DataFrame(rows)
    profile = compute_hourly_profile(hdf)

    # Every weekday sum of shares should equal 1.0
    for w in range(7):
        sub = profile[profile["weekday"] == w]
        assert len(sub) == 24
        assert pytest.approx(sub["share"].sum(), rel=1e-4) == 1.0


def test_croston_sba_intermittent():
    # Zero demand returns 0.0
    assert croston_sba([0, 0, 0, 0]) == 0.0

    # Constant non-zero demand
    sba_val = croston_sba([10, 10, 10, 10, 10], alpha=0.1)
    assert sba_val > 8.0 and sba_val <= 10.0

    # Intermittent series
    interm = [0, 0, 5, 0, 0, 0, 8, 0, 0, 6]
    pred = croston_sba(interm, alpha=0.1)
    assert pred > 0.0
    assert pred < 8.0
