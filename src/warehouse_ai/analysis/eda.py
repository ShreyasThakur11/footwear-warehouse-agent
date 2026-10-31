"""Exploratory Data Analysis (EDA) & Workload Drivers Module.

Provides modular analysis functions returning DataFrames that compute
demand patterns, temporal profiles, operator productivity proxies,
Pareto SKU distributions, and storage coverage for reuse across agents.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def compute_daily_trends(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Compute 7-day rolling means and cumulative metrics over calendar dates."""
    df = df_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df["orders_rolling_7d"] = df["orders"].rolling(window=7, min_periods=1).mean()
    df["lines_rolling_7d"] = df["lines"].rolling(window=7, min_periods=1).mean()
    df["units_rolling_7d"] = df["units"].rolling(window=7, min_periods=1).mean()

    df["is_weekend"] = df["date"].dt.weekday.isin([5, 6])
    return df


def compute_temporal_profiles(df_orders_clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute Day-of-Week and Hour-of-Day order arrival distributions."""
    df = df_orders_clean.copy()
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Day-of-week profile
    dow_df = df.groupby("weekday").agg(
        orders=("order_number", "nunique"),
        lines=("order_number", "count"),
        units=("qty", "sum"),
        active_days=("date", "nunique"),
    ).reset_index()

    dow_df["day_name"] = dow_df["weekday"].apply(lambda w: weekday_names[w])
    dow_df["orders_per_day"] = dow_df["orders"] / dow_df["active_days"].replace(0, np.nan)
    dow_df["units_per_day"] = dow_df["units"] / dow_df["active_days"].replace(0, np.nan)
    dow_df["share_of_orders_pct"] = (dow_df["orders"] / dow_df["orders"].sum()) * 100.0

    # Hour-of-day profile
    hour_df = df.groupby("hour").agg(
        orders=("order_number", "nunique"),
        lines=("order_number", "count"),
        units=("qty", "sum"),
    ).reset_index()

    hour_df["share_of_orders_pct"] = (hour_df["orders"] / hour_df["orders"].sum()) * 100.0
    hour_df["share_of_units_pct"] = (hour_df["units"] / hour_df["units"].sum()) * 100.0
    hour_df = hour_df.sort_values("hour").reset_index(drop=True)

    return dow_df, hour_df


def compute_order_and_wave_distributions(
    df_orders_clean: pd.DataFrame,
    df_waves: pd.DataFrame,
) -> dict[str, Any]:
    """Compute distribution statistics for order sizes and wave sizes."""
    # Units per order
    order_units = df_orders_clean.groupby("order_number")["qty"].sum()
    order_lines = df_orders_clean.groupby("order_number")["reference"].count()

    # Units per wave
    wave_units = df_waves["n_units"]

    stats = {
        "order_units": {
            "mean": float(order_units.mean()),
            "median": float(order_units.median()),
            "std": float(order_units.std()),
            "p10": float(order_units.quantile(0.10)),
            "p25": float(order_units.quantile(0.25)),
            "p75": float(order_units.quantile(0.75)),
            "p90": float(order_units.quantile(0.90)),
            "p99": float(order_units.quantile(0.99)),
            "series": order_units,
        },
        "order_lines": {
            "mean": float(order_lines.mean()),
            "median": float(order_lines.median()),
            "std": float(order_lines.std()),
            "p90": float(order_lines.quantile(0.90)),
            "series": order_lines,
        },
        "wave_units": {
            "mean": float(wave_units.mean()),
            "median": float(wave_units.median()),
            "std": float(wave_units.std()),
            "p90": float(wave_units.quantile(0.90)),
            "max": float(wave_units.max()),
            "series": wave_units,
        },
    }
    return stats


def compute_operator_performance(
    df_picks_clean: pd.DataFrame,
    df_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute per-operator volume & productivity metrics + daily active operator regression data."""
    # Group picks by operator
    op_summary = df_picks_clean.groupby("operator").agg(
        units=("qty", "sum"),
        picks=("qty", "count"),
        waves=("wave_number", "nunique"),
        locations_visited=("location", "nunique"),
    ).reset_index()

    total_units = op_summary["units"].sum()
    op_summary["workload_share_pct"] = (op_summary["units"] / total_units) * 100.0
    op_summary = op_summary.sort_values("units", ascending=False).reset_index(drop=True)

    # Daily units vs active operators (operating days only)
    active_daily = df_daily[df_daily["active_operators"] > 0].copy()
    active_daily["units_per_operator"] = active_daily["units"] / active_daily["active_operators"]

    return op_summary, active_daily


def compute_pareto_analysis(df_orders_clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    """Compute SKU and SKU-size Pareto distribution and footwear size curve."""
    # 1. Reference Pareto
    sku_demand = df_orders_clean.groupby("reference")["qty"].sum().reset_index()
    sku_demand = sku_demand.sort_values("qty", ascending=False).reset_index(drop=True)

    total_skus = len(sku_demand)
    total_units = sku_demand["qty"].sum()

    sku_demand["sku_rank"] = np.arange(1, total_skus + 1)
    sku_demand["sku_pct"] = (sku_demand["sku_rank"] / total_skus) * 100.0
    sku_demand["cum_units"] = sku_demand["qty"].cumsum()
    sku_demand["cum_units_pct"] = (sku_demand["cum_units"] / total_units) * 100.0

    # Share from top 20% SKUs
    top_20_count = int(np.ceil(0.20 * total_skus))
    top_20_units_share = float(sku_demand.iloc[top_20_count - 1]["cum_units_pct"])

    # 2. Footwear Size Curve
    size_demand = df_orders_clean.groupby("size_decoded")["qty"].sum().reset_index()
    size_demand = size_demand.sort_values("size_decoded").reset_index(drop=True)
    size_demand["share_pct"] = (size_demand["qty"] / total_units) * 100.0

    metrics = {
        "total_skus": total_skus,
        "total_units": float(total_units),
        "top_20pct_sku_count": top_20_count,
        "top_20pct_units_share": round(top_20_units_share, 2),
    }

    return sku_demand, size_demand, metrics


def compute_location_heatmap(df_picks_clean: pd.DataFrame) -> pd.DataFrame:
    """Aggregate pick counts by (x, y) coordinates for warehouse spatial heatmap."""
    valid_coords = df_picks_clean.dropna(subset=["x", "y"]).copy()
    heatmap_df = valid_coords.groupby(["x", "y", "aisle"]).agg(
        total_picks=("qty", "sum"),
        distinct_skus=("reference", "nunique"),
    ).reset_index()
    return heatmap_df


def compute_storage_policy_coverage(df_storage_long: pd.DataFrame) -> pd.DataFrame:
    """Compute SKU and location coverage across the 4 storage policies."""
    coverage = df_storage_long.groupby("policy").agg(
        total_slots=("slot_index", "count"),
        distinct_locations=("location", "nunique"),
        distinct_references=("reference", "nunique"),
        distinct_sku_sizes=("sku_size", "nunique"),
    ).reset_index()
    return coverage
