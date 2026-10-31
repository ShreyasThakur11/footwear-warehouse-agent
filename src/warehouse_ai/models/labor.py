"""Warehouse labor model and engineered workload standards.

Calculates required worker-time for picking workloads using an engineered standard
calibrated against empirical warehouse operations:
1. Engineered time per picking wave:
   time = setup_per_wave + (travel_dist / walk_speed) + (per_location_stop * n_locations)
          + (per_unit_handling * n_units) + (level_penalty * sum(z-1))
2. Shift calibration against high-volume operator days.
3. Macro workload forecasting model:
   workload_hours_from_forecast(units, lines, orders) via linear regression.
4. Implied labor productivity and staffing gap analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from warehouse_ai.config import get_config

_ROOT = Path(__file__).resolve().parents[3]


class LaborModel:
    """Engineered labor standard and workload forecasting model.

    Parameters
    ----------
    walk_speed_mps : float
        Walking speed pushing a manual trolley in m/s (default 1.0 m/s; De Koster et al. 2007).
    setup_per_wave_s : float
        Fixed wave dispatch, trolley acquisition, and staging drop time in seconds (default 60.0 s).
    per_location_stop_s : float
        Stop, verify location label, and position trolley in seconds (default 10.0 s; Tompkins et al. 2010).
    per_unit_handling_s : float
        Pick item box, verify SKU, and place in cart in seconds (default 6.0 s).
    level_penalty_s : float
        Retrieval delay per vertical level above ground tier Level 1 in seconds (default 5.0 s).
    shift_hours : float
        Standard productive shift length per full-time equivalent in hours (default 7.5 h).
    raw_to_meters : float
        Conversion factor from raw coordinate graph units to physical metres (default 0.0423 m/unit).
    calibration_scale : float
        Empirical scaling multiplier calibrated against full-shift busy operator-days (default 1.0).
    """

    def __init__(
        self,
        walk_speed_mps: float = 1.0,
        setup_per_wave_s: float = 60.0,
        per_location_stop_s: float = 10.0,
        per_unit_handling_s: float = 6.0,
        level_penalty_s: float = 5.0,
        shift_hours: float = 7.5,
        raw_to_meters: float = 0.0423,
        calibration_scale: float = 1.0,
    ) -> None:
        self.walk_speed_mps = walk_speed_mps
        self.setup_per_wave_s = setup_per_wave_s
        self.per_location_stop_s = per_location_stop_s
        self.per_unit_handling_s = per_unit_handling_s
        self.level_penalty_s = level_penalty_s
        self.shift_hours = shift_hours
        self.raw_to_meters = raw_to_meters
        self.calibration_scale = calibration_scale

        # Regression model for macro forecast
        self.regression_model: LinearRegression | None = None
        self.regression_metrics: dict[str, Any] = {}

    @classmethod
    def from_config(cls) -> LaborModel:
        """Instantiate LaborModel using application configuration."""
        cfg = get_config()
        l_cfg = cfg.labor
        return cls(
            walk_speed_mps=l_cfg.walk_speed_mps,
            setup_per_wave_s=l_cfg.setup_per_wave_s,
            per_location_stop_s=l_cfg.per_location_stop_s,
            per_unit_handling_s=l_cfg.per_unit_handling_s,
            level_penalty_s=l_cfg.level_penalty_s,
            shift_hours=l_cfg.shift_hours,
            raw_to_meters=0.0423,
            calibration_scale=1.0,
        )

    def wave_time(
        self,
        wave: pd.Series | dict[str, Any],
        dist_is_meters: bool = False,
        breakdown: bool = False,
        apply_calibration: bool = True,
    ) -> float | dict[str, float]:
        """Compute engineered picking time for a single wave in seconds.

        Parameters
        ----------
        wave : pd.Series or dict
            Wave data with travel_dist, n_distinct_locations (or n_locations),
            n_units (or units), and optional z_excess / vertical_penalty.
        dist_is_meters : bool
            Whether travel_dist is already in physical metres (default False).
        breakdown : bool
            Whether to return a detailed component dictionary (default False).
        apply_calibration : bool
            Whether to apply calibration_scale factor (default True).
        """
        # Extract features
        dist_raw = float(wave.get("travel_dist", wave.get("dist_m", 0.0)))
        dist_m = dist_raw if dist_is_meters else (dist_raw * self.raw_to_meters)

        n_locs = float(wave.get("n_distinct_locations", wave.get("n_locations", wave.get("stops", 1.0))))
        n_units = float(wave.get("n_units", wave.get("units", 1.0)))
        z_excess = float(wave.get("z_excess", wave.get("z_penalty", 0.0)))

        # Time components (seconds)
        setup_s = self.setup_per_wave_s
        walk_s = dist_m / max(0.1, self.walk_speed_mps)
        stop_s = self.per_location_stop_s * n_locs
        pick_s = self.per_unit_handling_s * n_units
        level_s = self.level_penalty_s * z_excess

        base_time_s = setup_s + walk_s + stop_s + pick_s + level_s
        scale = self.calibration_scale if apply_calibration else 1.0
        total_time_s = base_time_s * scale

        if breakdown:
            return {
                "total_seconds": round(total_time_s, 2),
                "total_minutes": round(total_time_s / 60.0, 2),
                "setup_s": round(setup_s * scale, 2),
                "walk_s": round(walk_s * scale, 2),
                "stop_s": round(stop_s * scale, 2),
                "pick_s": round(pick_s * scale, 2),
                "level_s": round(level_s * scale, 2),
                "distance_m": round(dist_m, 2),
                "calibration_scale": scale,
            }

        return float(total_time_s)

    def compute_waves_workload(
        self,
        waves_df: pd.DataFrame,
        picks_df: pd.DataFrame | None = None,
        dist_is_meters: bool = False,
    ) -> pd.DataFrame:
        """Enrich waves DataFrame with engineered labor duration columns."""
        w = waves_df.copy()

        # Compute z_excess if picks table is provided and not already present
        if "z_excess" not in w.columns:
            if picks_df is not None:
                p = picks_df.copy()
                p["z_excess"] = (p["level"].fillna(1).astype(int) - 1).clip(lower=0)
                z_map = p.groupby("wave_number")["z_excess"].sum().to_dict()
                w["z_excess"] = w["wave_id"].map(z_map).fillna(0.0)
            else:
                w["z_excess"] = 0.0

        # Vectorized wave calculation
        dist_raw = w["travel_dist"].fillna(0.0).values
        dist_m = dist_raw if dist_is_meters else (dist_raw * self.raw_to_meters)
        n_locs = w["n_distinct_locations"].fillna(1.0).values
        n_units = w["n_units"].fillna(1.0).values
        z_pen = w["z_excess"].fillna(0.0).values

        w["walk_time_s"] = dist_m / self.walk_speed_mps
        w["stop_time_s"] = self.per_location_stop_s * n_locs
        w["pick_time_s"] = self.per_unit_handling_s * n_units
        w["level_time_s"] = self.level_penalty_s * z_pen
        w["setup_time_s"] = self.setup_per_wave_s

        w["engineered_time_s"] = (
            w["setup_time_s"]
            + w["walk_time_s"]
            + w["stop_time_s"]
            + w["pick_time_s"]
            + w["level_time_s"]
        ) * self.calibration_scale

        w["engineered_hours"] = w["engineered_time_s"] / 3600.0
        w["engineered_minutes"] = w["engineered_time_s"] / 60.0

        return w

    def calibrate(
        self,
        waves_df: pd.DataFrame,
        picks_df: pd.DataFrame | None = None,
        target_shift_hours: float = 7.5,
        percentile: float = 95.0,
        method: str = "daily_max",
    ) -> float:
        """Fit empirical calibration scale so busy operator-days match target shift length.

        Parameters
        ----------
        waves_df : pd.DataFrame
            Waves table containing date, operator, and workload features.
        picks_df : pd.DataFrame | None
            Picks table for vertical level penalty computation.
        target_shift_hours : float
            Target full-shift duration in productive hours (default 7.5 h).
        percentile : float
            Percentile of busy operator-days to calibrate against (default 95.0).
        method : {"daily_max", "all_operator_days"}
            "daily_max": uses the busiest operator of each active day.
            "all_operator_days": uses all active operator-day observations.

        Returns
        -------
        float
            Fitted calibration scaling factor.
        """
        # Compute uncalibrated hours (scale = 1.0)
        self.calibration_scale = 1.0
        w = self.compute_waves_workload(waves_df, picks_df=picks_df)

        op_day = w.groupby(["date", "operator"])["engineered_hours"].sum().reset_index()

        if method == "daily_max":
            sample_series = op_day.groupby("date")["engineered_hours"].max()
        else:
            sample_series = op_day["engineered_hours"]

        obs_val = float(np.percentile(sample_series.dropna(), percentile))
        fitted_scale = float(target_shift_hours / max(0.01, obs_val))

        self.calibration_scale = fitted_scale
        return fitted_scale

    def day_workload_hours(
        self,
        date: str | pd.Timestamp,
        waves_df: pd.DataFrame,
        picks_df: pd.DataFrame | None = None,
    ) -> float:
        """Return total engineered labor hours required for a given calendar date."""
        w = self.compute_waves_workload(waves_df, picks_df=picks_df)
        date_str = pd.to_datetime(date).strftime("%Y-%m-%d")
        w_date = pd.to_datetime(w["date"]).dt.strftime("%Y-%m-%d")
        sub = w[w_date == date_str]
        return float(sub["engineered_hours"].sum())

    def fit_forecast_model(
        self,
        daily_df: pd.DataFrame,
        waves_df: pd.DataFrame | None = None,
        picks_df: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Fit linear regression predicting daily labor hours from units, lines, and orders.

        Parameters
        ----------
        daily_df : pd.DataFrame
            Daily aggregated table with date, orders, lines, units.
        waves_df : pd.DataFrame | None
            Wave-level table to derive daily actual engineered hours.
        """
        daily = daily_df.copy()
        if "engineered_hours" not in daily.columns:
            if waves_df is None:
                raise ValueError("waves_df must be provided if daily_df lacks 'engineered_hours'")
            w = self.compute_waves_workload(waves_df, picks_df=picks_df)
            day_hours = w.groupby("date")["engineered_hours"].sum().reset_index()
            daily["date_str"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
            day_hours["date_str"] = pd.to_datetime(day_hours["date"]).dt.strftime("%Y-%m-%d")
            daily = daily.merge(day_hours[["date_str", "engineered_hours"]], on="date_str", how="inner")

        active = daily[daily["units"] > 0].copy()
        X = active[["units", "lines", "orders"]].values
        y = active["engineered_hours"].values

        reg = LinearRegression(fit_intercept=True)
        reg.fit(X, y)
        y_pred = reg.predict(X)

        r2 = float(r2_score(y, y_pred))
        mae = float(mean_absolute_error(y, y_pred))
        rmse = float(np.sqrt(mean_squared_error(y, y_pred)))
        residuals = y - y_pred

        self.regression_model = reg
        self.regression_metrics = {
            "r2": r2,
            "mae": mae,
            "rmse": rmse,
            "intercept": float(reg.intercept_),
            "coef_units": float(reg.coef_[0]),
            "coef_lines": float(reg.coef_[1]),
            "coef_orders": float(reg.coef_[2]),
            "n_observations": len(active),
            "residuals_mean": float(np.mean(residuals)),
            "residuals_std": float(np.std(residuals)),
            "residuals_p90": float(np.percentile(np.abs(residuals), 90)),
        }
        return self.regression_metrics

    def workload_hours_from_forecast(
        self,
        units: float,
        lines: float,
        orders: float,
    ) -> float:
        """Predict required labor hours from macro daily forecast (units, lines, orders)."""
        if self.regression_model is None:
            # Fallback coefficients derived from default parameters
            return float(max(0.0, 0.00314 * units + 0.00571 * lines - 0.00039 * orders - 0.0484))

        X_new = np.array([[units, lines, orders]], dtype=float)
        pred = float(self.regression_model.predict(X_new)[0])
        return max(0.0, pred)

    def implied_productivity(
        self,
        waves_df: pd.DataFrame,
        picks_df: pd.DataFrame | None = None,
    ) -> tuple[pd.DataFrame, float]:
        """Compute implied labor productivity (units per labor-hour) overall and per operator.

        Returns
        -------
        tuple of (op_df, overall_units_per_hour)
        """
        w = self.compute_waves_workload(waves_df, picks_df=picks_df)
        total_units = float(w["n_units"].sum())
        total_hours = float(w["engineered_hours"].sum())
        overall_uph = total_units / max(0.001, total_hours)

        op_grp = w.groupby("operator").agg(
            waves=("wave_id", "nunique"),
            units=("n_units", "sum"),
            stops=("n_distinct_locations", "sum"),
            hours=("engineered_hours", "sum"),
        ).reset_index()

        op_grp["units_per_hour"] = op_grp["units"] / op_grp["hours"].replace(0, np.nan)
        op_grp["workload_share"] = op_grp["units"] / max(1.0, total_units)
        op_grp = op_grp.sort_values("units", ascending=False).reset_index(drop=True)

        return op_grp, overall_uph

    def staffing_analysis(
        self,
        daily_df: pd.DataFrame,
        waves_df: pd.DataFrame,
        picks_df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Analyze daily required labor-hours versus actual active operator capacity.

        Identifies over-staffed and under-staffed days for headcount right-sizing.
        """
        w = self.compute_waves_workload(waves_df, picks_df=picks_df)
        day_workload = w.groupby("date")["engineered_hours"].sum().rename("required_hours")

        daily = daily_df.copy()
        daily["date_str"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
        day_workload_df = day_workload.reset_index()
        day_workload_df["date_str"] = pd.to_datetime(day_workload_df["date"]).dt.strftime("%Y-%m-%d")

        m = daily.merge(day_workload_df[["date_str", "required_hours"]], on="date_str", how="inner")
        m = m[m["active_operators"] > 0].copy()

        m["available_hours"] = m["active_operators"] * self.shift_hours
        m["utilization"] = m["required_hours"] / m["available_hours"].replace(0, np.nan)
        m["fte_required"] = m["required_hours"] / self.shift_hours
        m["headcount_excess"] = m["active_operators"] - m["fte_required"]

        # Classification
        # Over-staffed: utilization < 60% or excess >= 1 full operator
        # Under-staffed: utilization > 100%
        # Balanced: 60% <= utilization <= 100%
        m["staffing_status"] = np.where(
            m["utilization"] > 1.0,
            "Under-staffed",
            np.where(m["utilization"] < 0.60, "Over-staffed", "Balanced"),
        )
        return m.sort_values("date").reset_index(drop=True)


# Module-level default model
_DEFAULT_LABOR_MODEL: LaborModel | None = None


def get_labor_model() -> LaborModel:
    """Return the global default LaborModel instance."""
    global _DEFAULT_LABOR_MODEL
    if _DEFAULT_LABOR_MODEL is None:
        _DEFAULT_LABOR_MODEL = LaborModel.from_config()
    return _DEFAULT_LABOR_MODEL


def wave_time(
    wave: pd.Series | dict[str, Any],
    dist_is_meters: bool = False,
    breakdown: bool = False,
) -> float | dict[str, float]:
    """Convenience function: compute engineered picking duration for a wave in seconds."""
    return get_labor_model().wave_time(wave, dist_is_meters=dist_is_meters, breakdown=breakdown)


def day_workload_hours(
    date: str | pd.Timestamp,
    waves_df: pd.DataFrame,
    picks_df: pd.DataFrame | None = None,
) -> float:
    """Convenience function: compute total required labor hours for a specific date."""
    return get_labor_model().day_workload_hours(date, waves_df, picks_df=picks_df)


def workload_hours_from_forecast(
    units: float,
    lines: float,
    orders: float,
) -> float:
    """Convenience function: forecast required labor hours from units, lines, and orders."""
    return get_labor_model().workload_hours_from_forecast(units, lines, orders)
