"""Demand forecasting models for warehouse workload and SKU-size requirements.

Provides:
- Daily aggregate forecasts for units, lines, and orders (horizon 1–14 days).
- Multiple model architectures: Seasonal Naive, 4-Week Weekday Average,
  Holt-Winters ETS (statsmodels), and Quantile Histogram Gradient Boosting
  (P10, P50, P90 prediction intervals).
- Canadian/Quebec statutory holiday calendar integration.
- Intra-day hourly demand profiling (weekday-conditioned arrival shares).
- Intermittent weekly demand forecasting using Croston's method with
  Syntetos-Boylan Approximation (SBA) and smooth exponential smoothing.
- Rolling-origin backtesting engine (MAE, WAPE, Bias, Interval Coverage).
- Production API: ``forecast_daily``, ``forecast_sku_size``, and model store persistence.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from warehouse_ai.config import load_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canadian & Quebec Statutory Holidays (2023)
# ---------------------------------------------------------------------------

HOLIDAYS_QUEBEC_2023: set[str] = {
    "2023-01-01",  # New Year's Day
    "2023-01-02",  # Day after New Year's Day (Lendemain du Jour de l'An)
    "2023-04-07",  # Good Friday (Vendredi saint)
    "2023-04-10",  # Easter Monday (Lundi de Pâques)
    "2023-05-22",  # National Patriots' Day / Victoria Day (Journée des patriotes)
    "2023-06-23",  # Saint-Jean-Baptiste observed (Fête nationale)
    "2023-06-24",  # Saint-Jean-Baptiste Day
    "2023-07-01",  # Canada Day
    "2023-07-03",  # Canada Day observed
    "2023-08-07",  # Civic Holiday / Summer shutdown
    "2023-09-04",  # Labour Day (Fête du travail)
    "2023-09-30",  # National Day for Truth and Reconciliation
    "2023-10-09",  # Thanksgiving (Action de grâce)
    "2023-12-25",  # Christmas Day
    "2023-12-26",  # Boxing Day (Lendemain de Noël)
}


def is_quebec_holiday(date_val: str | dt.date | pd.Timestamp) -> bool:
    """Return True if date_val matches a Quebec/Canadian holiday."""
    ds = pd.to_datetime(date_val).strftime("%Y-%m-%d")
    return ds in HOLIDAYS_QUEBEC_2023


# ---------------------------------------------------------------------------
# Feature Engineering for Daily Time Series
# ---------------------------------------------------------------------------

def create_daily_features(
    df: pd.DataFrame,
    target_col: str = "units",
    max_lag: int = 14,
) -> pd.DataFrame:
    """Engineer calendar, lag, and rolling features for daily tabular forecasting.

    Parameters
    ----------
    df : pd.DataFrame
        Daily table with columns ['date', target_col].
    target_col : str
        Target series column name (e.g. 'units', 'orders', 'lines').
    max_lag : int
        Maximum lag to compute.

    Returns
    -------
    pd.DataFrame
        Enriched DataFrame with lag features, rolling statistics, and calendar attributes.
    """
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)

    # Calendar features
    data["day_of_week"] = data["date"].dt.dayofweek
    data["day_of_month"] = data["date"].dt.day
    data["week_of_year"] = data["date"].dt.isocalendar().week.astype(int)
    data["month"] = data["date"].dt.month
    data["is_weekend"] = data["day_of_week"].isin([5, 6]).astype(int)
    data["is_holiday"] = data["date"].apply(is_quebec_holiday).astype(int)

    # Lag features
    for lag in [1, 2, 7, 14]:
        data[f"lag_{lag}"] = data[target_col].shift(lag)

    # Rolling statistics (using shifted series to avoid leakage)
    shifted = data[target_col].shift(1)
    data["rolling_mean_7"] = shifted.rolling(window=7, min_periods=1).mean()
    data["rolling_mean_14"] = shifted.rolling(window=14, min_periods=1).mean()
    data["rolling_std_7"] = shifted.rolling(window=7, min_periods=1).std().fillna(0.0)

    return data


# ---------------------------------------------------------------------------
# Forecast Metrics
# ---------------------------------------------------------------------------

@dataclass
class ForecastMetrics:
    mae: float
    wape: float
    bias: float
    coverage_80: float
    n_samples: int


def calculate_metrics(
    actual: Sequence[float],
    forecast: Sequence[float],
    p10: Sequence[float] | None = None,
    p90: Sequence[float] | None = None,
) -> ForecastMetrics:
    """Calculate standard supply chain forecasting evaluation metrics."""
    y = np.asarray(actual, dtype=float)
    y_hat = np.asarray(forecast, dtype=float)
    n = len(y)

    if n == 0:
        return ForecastMetrics(0.0, 0.0, 0.0, 0.0, 0)

    mae = float(np.mean(np.abs(y - y_hat)))
    sum_y = float(np.sum(y))
    wape = float(np.sum(np.abs(y - y_hat)) / sum_y) if sum_y > 0 else 0.0
    bias = float(np.sum(y_hat - y) / sum_y) if sum_y > 0 else 0.0

    if p10 is not None and p90 is not None:
        p10_arr = np.asarray(p10, dtype=float)
        p90_arr = np.asarray(p90, dtype=float)
        inside = (y >= p10_arr) & (y <= p90_arr)
        coverage = float(np.mean(inside))
    else:
        coverage = 0.0

    return ForecastMetrics(
        mae=round(mae, 2),
        wape=round(wape, 4),
        bias=round(bias, 4),
        coverage_80=round(coverage, 4),
        n_samples=n,
    )


# ---------------------------------------------------------------------------
# Individual Daily Forecasters
# ---------------------------------------------------------------------------

class SeasonalNaiveForecaster:
    """7-day seasonal naive benchmark (predicts same day of week last week)."""

    def __init__(self, season_length: int = 7) -> None:
        self.season_length = season_length
        self.history_: np.ndarray | None = None
        self.residuals_: np.ndarray | None = None

    def fit(self, y: Sequence[float]) -> SeasonalNaiveForecaster:
        arr = np.asarray(y, dtype=float)
        self.history_ = arr
        if len(arr) > self.season_length:
            actual = arr[self.season_length:]
            pred = arr[:-self.season_length]
            self.residuals_ = actual - pred
        else:
            self.residuals_ = np.array([0.0])
        return self

    def predict(self, horizon: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Predict point forecast and (P10, P90) intervals."""
        if self.history_ is None or len(self.history_) == 0:
            zeros = np.zeros(horizon)
            return zeros, zeros, zeros

        m = self.season_length
        preds = []
        hist = list(self.history_)
        for h in range(horizon):
            idx = len(hist) - m
            val = max(0.0, hist[idx] if idx >= 0 else hist[-1])
            preds.append(val)
            hist.append(val)

        p50 = np.array(preds)
        q10 = float(np.quantile(self.residuals_, 0.10)) if self.residuals_ is not None else 0.0
        q90 = float(np.quantile(self.residuals_, 0.90)) if self.residuals_ is not None else 0.0

        p10 = np.clip(p50 + q10, 0.0, None)
        p90 = np.clip(p50 + q90, 0.0, None)
        p90 = np.maximum(p90, p50)
        p10 = np.minimum(p10, p50)
        return p10, p50, p90


class WeekdayAverageForecaster:
    """4-week rolling average for matching weekday."""

    def __init__(self, weeks: int = 4) -> None:
        self.weeks = weeks
        self.history_dates_: pd.Series | None = None
        self.history_values_: pd.Series | None = None
        self.residuals_: np.ndarray | None = None

    def fit(self, dates: Sequence[str | dt.date], y: Sequence[float]) -> WeekdayAverageForecaster:
        dts = pd.to_datetime(dates)
        self.history_dates_ = dts
        self.history_values_ = pd.Series(y, index=dts)

        # Residuals on training set
        preds = []
        actuals = []
        for i in range(28, len(dts)):
            curr_date = dts[i]
            val = self._predict_single(curr_date, self.history_values_.iloc[:i])
            preds.append(val)
            actuals.append(y[i])

        if len(preds) > 0:
            self.residuals_ = np.array(actuals) - np.array(preds)
        else:
            self.residuals_ = np.array([0.0])
        return self

    def _predict_single(self, target_date: pd.Timestamp, history: pd.Series) -> float:
        lags = [target_date - pd.Timedelta(days=7 * w) for w in range(1, self.weeks + 1)]
        vals = [history.get(lag, np.nan) for lag in lags if lag in history.index]
        vals = [v for v in vals if not np.isnan(v)]
        if len(vals) == 0:
            return float(history.iloc[-1]) if len(history) > 0 else 0.0
        return float(np.mean(vals))

    def predict(
        self,
        start_date: str | dt.date,
        horizon: int = 14,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.history_values_ is None:
            zeros = np.zeros(horizon)
            return zeros, zeros, zeros

        start_dt = pd.to_datetime(start_date)
        forecast_dates = pd.date_range(start_dt, periods=horizon, freq="D")

        hist = self.history_values_.copy()
        preds = []
        for fdate in forecast_dates:
            val = self._predict_single(fdate, hist)
            # Clip weekend/holiday volume if standard weekday average
            if is_quebec_holiday(fdate) or fdate.dayofweek in [5, 6]:
                # Weekends in historical data have near-zero operations
                val = 0.0
            val = max(0.0, val)
            preds.append(val)
            hist.loc[fdate] = val

        p50 = np.array(preds)
        q10 = float(np.quantile(self.residuals_, 0.10)) if self.residuals_ is not None else 0.0
        q90 = float(np.quantile(self.residuals_, 0.90)) if self.residuals_ is not None else 0.0

        p10 = np.clip(p50 + q10, 0.0, None)
        p90 = np.clip(p50 + q90, 0.0, None)
        p90 = np.maximum(p90, p50)
        p10 = np.minimum(p10, p50)
        return p10, p50, p90


class HoltWintersForecaster:
    """Holt-Winters Exponential Smoothing with weekly seasonality."""

    def __init__(self, seasonal_periods: int = 7) -> None:
        self.seasonal_periods = seasonal_periods
        self.model_ = None
        self.residuals_: np.ndarray | None = None

    def fit(self, y: Sequence[float]) -> HoltWintersForecaster:
        arr = np.asarray(y, dtype=float)
        # Shift positive to avoid non-positive issues in ETS
        min_val = np.min(arr)
        shift = abs(min_val) + 1.0 if min_val <= 0 else 0.0
        shifted_arr = arr + shift

        try:
            ets = ExponentialSmoothing(
                shifted_arr,
                seasonal_periods=self.seasonal_periods,
                trend="add",
                seasonal="add",
                initialization_method="estimated",
            ).fit(optimized=True)
            self.model_ = ets
            fitted = np.clip(ets.fittedvalues - shift, 0.0, None)
            self.residuals_ = arr - fitted
            self.shift_ = shift
        except Exception as exc:
            logger.warning("Holt-Winters fitting failed (%s); fallback to naive.", exc)
            self.model_ = None
            self.residuals_ = np.array([0.0])
            self.shift_ = 0.0
            self.fallback_ = SeasonalNaiveForecaster(season_length=self.seasonal_periods).fit(arr)
        return self

    def predict(self, horizon: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.model_ is None:
            return self.fallback_.predict(horizon)

        raw_forecast = self.model_.forecast(horizon)
        p50 = np.clip(raw_forecast - self.shift_, 0.0, None)

        q10 = float(np.quantile(self.residuals_, 0.10)) if self.residuals_ is not None else 0.0
        q90 = float(np.quantile(self.residuals_, 0.90)) if self.residuals_ is not None else 0.0

        p10 = np.clip(p50 + q10, 0.0, None)
        p90 = np.clip(p50 + q90, 0.0, None)
        p90 = np.maximum(p90, p50)
        p10 = np.minimum(p10, p50)
        return p10, p50, p90


class QuantileGradientBoostingForecaster:
    """Tabular Gradient Boosting predicting P10, P50, and P90 quantiles.

    Uses scikit-learn's ``HistGradientBoostingRegressor`` with quantile loss,
    offering exact parity with LightGBM without dynamic library linking hazards.
    """

    def __init__(self, random_seed: int = 42) -> None:
        self.random_seed = random_seed
        self.feature_cols = [
            "day_of_week",
            "day_of_month",
            "week_of_year",
            "month",
            "is_weekend",
            "is_holiday",
            "lag_1",
            "lag_2",
            "lag_7",
            "lag_14",
            "rolling_mean_7",
            "rolling_mean_14",
            "rolling_std_7",
        ]
        self.model_p10 = HistGradientBoostingRegressor(
            loss="quantile", quantile=0.10, random_state=random_seed, max_iter=150, min_samples_leaf=5
        )
        self.model_p50 = HistGradientBoostingRegressor(
            loss="quantile", quantile=0.50, random_state=random_seed, max_iter=150, min_samples_leaf=5
        )
        self.model_p90 = HistGradientBoostingRegressor(
            loss="quantile", quantile=0.90, random_state=random_seed, max_iter=150, min_samples_leaf=5
        )
        self.history_df_: pd.DataFrame | None = None
        self.target_col_: str = "units"

    def fit(self, df: pd.DataFrame, target_col: str = "units") -> QuantileGradientBoostingForecaster:
        self.target_col_ = target_col
        feat_df = create_daily_features(df, target_col=target_col)
        # Drop initial rows where lags are incomplete
        clean_df = feat_df.dropna(subset=self.feature_cols + [target_col]).copy()

        X = clean_df[self.feature_cols]
        y = clean_df[target_col]

        self.model_p10.fit(X, y)
        self.model_p50.fit(X, y)
        self.model_p90.fit(X, y)
        self.history_df_ = df.copy()
        return self

    def predict(
        self,
        start_date: str | dt.date,
        horizon: int = 14,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Multi-step autoregressive recursive forecast for P10, P50, and P90."""
        if self.history_df_ is None:
            zeros = np.zeros(horizon)
            return zeros, zeros, zeros

        curr_history = self.history_df_[["date", self.target_col_]].copy()
        curr_history["date"] = pd.to_datetime(curr_history["date"])
        curr_history = curr_history.sort_values("date").reset_index(drop=True)

        start_dt = pd.to_datetime(start_date)
        forecast_dates = pd.date_range(start_dt, periods=horizon, freq="D")

        preds_10, preds_50, preds_90 = [], [], []

        for fdate in forecast_dates:
            # Append placeholder row for target date
            row = pd.DataFrame([{"date": fdate, self.target_col_: np.nan}])
            extended = pd.concat([curr_history, row], ignore_index=True)
            feat = create_daily_features(extended, target_col=self.target_col_)
            X_curr = feat[feat["date"] == fdate][self.feature_cols]

            q10 = float(self.model_p10.predict(X_curr)[0])
            q50 = float(self.model_p50.predict(X_curr)[0])
            q90 = float(self.model_p90.predict(X_curr)[0])

            # Apply domain constraints: weekend / holiday near-zero
            if is_quebec_holiday(fdate) or fdate.dayofweek in [5, 6]:
                q10 = 0.0
                q50 = 0.0
                q90 = 0.0

            q10 = max(0.0, q10)
            q50 = max(0.0, q50)
            q90 = max(0.0, q90)

            # Enforce monotonicity: q10 <= q50 <= q90
            q50 = max(q10, q50)
            q90 = max(q50, q90)

            preds_10.append(q10)
            preds_50.append(q50)
            preds_90.append(q90)

            # Update history with median forecast for autoregressive lag features
            curr_history = pd.concat(
                [curr_history, pd.DataFrame([{"date": fdate, self.target_col_: q50}])],
                ignore_index=True,
            )

        return np.array(preds_10), np.array(preds_50), np.array(preds_90)


# ---------------------------------------------------------------------------
# Hourly Demand Profiling
# ---------------------------------------------------------------------------

def compute_hourly_profile(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Compute normalized hourly arrival shares conditioned on day of week.

    Returns
    -------
    pd.DataFrame
        Table with columns ['weekday', 'hour', 'share'] where
        sum(share) == 1.0 for each weekday.
    """
    df = hourly_df.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["weekday"] = df["dt"].dt.dayofweek

    # Aggregate total units by weekday and hour across the dataset
    grouped = df.groupby(["weekday", "hour"])["units"].sum().reset_index()

    # Fill full 7x24 grid
    grid = pd.MultiIndex.from_product([range(7), range(24)], names=["weekday", "hour"]).to_frame().reset_index(drop=True)
    merged = pd.merge(grid, grouped, on=["weekday", "hour"], how="left").fillna(0.0)

    # Normalize by weekday
    weekday_totals = merged.groupby("weekday")["units"].transform("sum")
    # For days with zero total activity (weekends), assign uniform share
    merged["share"] = np.where(
        weekday_totals > 0,
        merged["units"] / weekday_totals,
        1.0 / 24.0,
    )
    return merged[["weekday", "hour", "share"]].sort_values(["weekday", "hour"]).reset_index(drop=True)


def disaggregate_daily_to_hourly(
    daily_forecast_df: pd.DataFrame,
    hourly_profile_df: pd.DataFrame,
) -> pd.DataFrame:
    """Disaggregate daily forecasts into hourly volumes using arrival shares."""
    daily = daily_forecast_df.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["weekday"] = daily["date"].dt.dayofweek

    rows = []
    for _, d_row in daily.iterrows():
        sub_profile = hourly_profile_df[hourly_profile_df["weekday"] == d_row["weekday"]]
        for _, p_row in sub_profile.iterrows():
            hour = int(p_row["hour"])
            share = float(p_row["share"])
            rows.append({
                "date": d_row["date"].strftime("%Y-%m-%d"),
                "hour": hour,
                "p10": round(d_row["p10"] * share, 2),
                "p50": round(d_row["p50"] * share, 2),
                "p90": round(d_row["p90"] * share, 2),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Intermittent SKU-Size Forecasting (Croston SBA)
# ---------------------------------------------------------------------------

def croston_sba(demand: Sequence[float], alpha: float = 0.1) -> float:
    """Croston's method with Syntetos-Boylan Approximation (SBA).

    Estimates average demand per period for intermittent demand series.
    The SBA multiplier (1 - alpha/2) corrects for the inherent positive bias of
    standard Croston's estimator.
    """
    dem = np.asarray(demand, dtype=float)
    n = len(dem)
    if n == 0 or np.sum(dem) == 0:
        return 0.0

    pos_idx = np.where(dem > 0)[0]
    if len(pos_idx) == 0:
        return 0.0

    # Initialize at first positive observation
    z = dem[pos_idx[0]]
    p = 1.0
    q = 0.0

    for t in range(n):
        if dem[t] > 0:
            q += 1.0
            z = alpha * dem[t] + (1.0 - alpha) * z
            p = alpha * q + (1.0 - alpha) * p
            q = 0.0
        else:
            q += 1.0

    # Syntetos-Boylan Approximation
    sba_factor = 1.0 - (alpha / 2.0)
    rate = (z / p) if p > 0 else 0.0
    return float(max(0.0, sba_factor * rate))


def forecast_sku_size(
    orders_df: pd.DataFrame,
    weeks: int = 4,
    alpha: float = 0.1,
    intermittent_threshold: float = 0.70,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Produce weekly SKU-size demand forecasts.

    Classifies each series:
    - If fraction of zero-demand weeks >= intermittent_threshold: Croston-SBA.
    - Otherwise: Exponential Moving Average / Smooth forecaster.
    """
    df = orders_df.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["week"] = df["dt"].dt.to_period("W-SUN")

    # Pivot weekly demand
    weekly_agg = df.groupby(["sku_size", "week"])["qty"].sum().unstack(fill_value=0.0)

    # Filter to top N if requested
    if top_n is not None and top_n < len(weekly_agg):
        totals = weekly_agg.sum(axis=1)
        weekly_agg = weekly_agg.loc[totals.nlargest(top_n).index]

    results = []
    for sku_size, series in weekly_agg.iterrows():
        demands = series.values
        zero_ratio = float(np.mean(demands == 0))

        if zero_ratio >= intermittent_threshold:
            method = "Croston-SBA"
            weekly_rate = croston_sba(demands, alpha=alpha)
        else:
            method = "Smooth-EMA"
            # 4-week weighted moving average
            weights = np.array([0.1, 0.2, 0.3, 0.4])
            recent = demands[-4:] if len(demands) >= 4 else demands
            w = weights[-len(recent):]
            w = w / np.sum(w)
            weekly_rate = float(np.dot(recent, w))

        weekly_rate = max(0.0, round(weekly_rate, 2))
        results.append({
            "sku_size": sku_size,
            "method": method,
            "zero_ratio": round(zero_ratio, 3),
            "historical_mean": round(float(np.mean(demands)), 2),
            "weekly_forecast": weekly_rate,
            "horizon_weeks": weeks,
            "total_forecast": round(weekly_rate * weeks, 2),
        })

    return pd.DataFrame(results).sort_values("total_forecast", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Rolling-Origin Backtesting Engine
# ---------------------------------------------------------------------------

def run_rolling_backtest(
    daily_df: pd.DataFrame,
    target_col: str = "units",
    horizon: int = 14,
    test_weeks: int = 8,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Evaluate models via rolling-origin backtesting over the last test_weeks."""
    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    max_date = df["date"].max()
    test_start = max_date - pd.Timedelta(weeks=test_weeks)

    # Origin split points every 7 days
    origins = [test_start + pd.Timedelta(days=7 * k) for k in range(test_weeks)]
    origins = [orig for orig in origins if orig + pd.Timedelta(days=horizon) <= max_date]

    models = {
        "Seasonal_Naive": SeasonalNaiveForecaster(season_length=7),
        "Weekday_Average_4W": WeekdayAverageForecaster(weeks=4),
        "Holt_Winters_ETS": HoltWintersForecaster(seasonal_periods=7),
        "Quantile_Gradient_Boosting": QuantileGradientBoostingForecaster(random_seed=random_seed),
    }

    records: dict[str, dict[str, list[float]]] = {
        m_name: {"actual": [], "pred": [], "p10": [], "p90": []}
        for m_name in models
    }

    for origin in origins:
        train_df = df[df["date"] <= origin].copy()
        test_df = df[(df["date"] > origin) & (df["date"] <= origin + pd.Timedelta(days=horizon))].copy()

        if len(test_df) < horizon:
            continue

        actual_vals = test_df[target_col].values
        start_eval_date = test_df["date"].min()

        # 1. Seasonal Naive
        sn = SeasonalNaiveForecaster(season_length=7).fit(train_df[target_col].values)
        p10, p50, p90 = sn.predict(horizon=horizon)
        records["Seasonal_Naive"]["actual"].extend(actual_vals)
        records["Seasonal_Naive"]["pred"].extend(p50)
        records["Seasonal_Naive"]["p10"].extend(p10)
        records["Seasonal_Naive"]["p90"].extend(p90)

        # 2. Weekday Average 4W
        wa = WeekdayAverageForecaster(weeks=4).fit(train_df["date"].values, train_df[target_col].values)
        p10, p50, p90 = wa.predict(start_eval_date, horizon=horizon)
        records["Weekday_Average_4W"]["actual"].extend(actual_vals)
        records["Weekday_Average_4W"]["pred"].extend(p50)
        records["Weekday_Average_4W"]["p10"].extend(p10)
        records["Weekday_Average_4W"]["p90"].extend(p90)

        # 3. Holt-Winters ETS
        hw = HoltWintersForecaster(seasonal_periods=7).fit(train_df[target_col].values)
        p10, p50, p90 = hw.predict(horizon=horizon)
        records["Holt_Winters_ETS"]["actual"].extend(actual_vals)
        records["Holt_Winters_ETS"]["pred"].extend(p50)
        records["Holt_Winters_ETS"]["p10"].extend(p10)
        records["Holt_Winters_ETS"]["p90"].extend(p90)

        # 4. Quantile Gradient Boosting
        qgb = QuantileGradientBoostingForecaster(random_seed=random_seed).fit(train_df, target_col=target_col)
        p10, p50, p90 = qgb.predict(start_eval_date, horizon=horizon)
        records["Quantile_Gradient_Boosting"]["actual"].extend(actual_vals)
        records["Quantile_Gradient_Boosting"]["pred"].extend(p50)
        records["Quantile_Gradient_Boosting"]["p10"].extend(p10)
        records["Quantile_Gradient_Boosting"]["p90"].extend(p90)

    # Compute aggregate summary metrics
    results = []
    for m_name, d in records.items():
        met = calculate_metrics(d["actual"], d["pred"], d["p10"], d["p90"])
        results.append({
            "model": m_name,
            "target": target_col,
            "mae": met.mae,
            "wape": met.wape,
            "bias": met.bias,
            "coverage_80": met.coverage_80,
            "n_eval_points": met.n_samples,
        })

    return pd.DataFrame(results).sort_values("wape").reset_index(drop=True)


# ---------------------------------------------------------------------------
# High-Level Production APIs & Model Store
# ---------------------------------------------------------------------------

MODEL_STORE_DIR = Path("models_store")


def save_forecaster(
    forecaster: Any,
    model_name: str,
    version: str = "v1",
    store_dir: Path | str = MODEL_STORE_DIR,
) -> Path:
    """Serialize fitted forecaster to disk."""
    sdir = Path(store_dir)
    sdir.mkdir(parents=True, exist_ok=True)
    out_path = sdir / f"{model_name}_{version}.joblib"
    joblib.dump(forecaster, out_path)
    logger.info("Saved %s to %s", model_name, out_path)
    return out_path


def load_forecaster(
    model_name: str,
    version: str = "v1",
    store_dir: Path | str = MODEL_STORE_DIR,
) -> Any:
    """Load serialized forecaster from disk."""
    path = Path(store_dir) / f"{model_name}_{version}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"No checkpoint found at {path}")
    return joblib.load(path)


def forecast_daily(
    start_date: str | dt.date | None = None,
    horizon: int = 14,
    target: str = "units",
    model_name: str = "gradient_boosting",
    daily_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Production entry point returning daily forecasts with prediction intervals.

    Parameters
    ----------
    start_date : str | dt.date | None
        First day of forecast horizon. When None, defaults to day after dataset max.
    horizon : int
        Number of calendar days ahead to project (default: 14).
    target : str
        Target metric: 'units', 'orders', or 'lines'.
    model_name : str
        Model architecture: 'gradient_boosting', 'holt_winters', 'weekday_average', 'seasonal_naive'.
    daily_df : pd.DataFrame | None
        Daily dataset. When None, loaded from data/processed/daily.parquet.

    Returns
    -------
    pd.DataFrame
        Columns ['date', 'target', 'p10', 'p50', 'p90', 'model'].
    """
    if daily_df is None:
        cfg = load_config()
        daily_path = Path(cfg.paths.data_processed) / "daily.parquet"
        daily_df = pd.read_parquet(daily_path)

    daily_df = daily_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date").reset_index(drop=True)

    if start_date is None:
        start_dt = daily_df["date"].max() + pd.Timedelta(days=1)
    else:
        start_dt = pd.to_datetime(start_date)

    forecast_dates = pd.date_range(start_dt, periods=horizon, freq="D")

    # Fit selected model
    if model_name in ["gradient_boosting", "auto"]:
        model = QuantileGradientBoostingForecaster(random_seed=42).fit(daily_df, target_col=target)
        p10, p50, p90 = model.predict(start_dt, horizon=horizon)
        m_label = "QuantileGradientBoosting"
    elif model_name == "holt_winters":
        model = HoltWintersForecaster(seasonal_periods=7).fit(daily_df[target].values)
        p10, p50, p90 = model.predict(horizon=horizon)
        m_label = "HoltWintersETS"
    elif model_name == "weekday_average":
        model = WeekdayAverageForecaster(weeks=4).fit(daily_df["date"].values, daily_df[target].values)
        p10, p50, p90 = model.predict(start_dt, horizon=horizon)
        m_label = "WeekdayAverage4W"
    elif model_name == "seasonal_naive":
        model = SeasonalNaiveForecaster(season_length=7).fit(daily_df[target].values)
        p10, p50, p90 = model.predict(horizon=horizon)
        m_label = "SeasonalNaive"
    else:
        raise ValueError(f"Unknown model_name: {model_name}")

    out = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in forecast_dates],
        "target": target,
        "p10": np.round(p10, 1),
        "p50": np.round(p50, 1),
        "p90": np.round(p90, 1),
        "model": m_label,
    })
    return out
