"""Inventory classification models: Pareto ABC and Demand Variability XYZ.

Provides:
- Pareto ABC analysis based on cumulative picking demand (80/15/5 threshold).
- Demand variability XYZ classification using coefficient of variation (CV = std / mean)
  of weekly demand series (X < 0.5, 0.5 <= Y < 1.0, Z >= 1.0).
- Granularity at both parent product (reference) and specific size (sku_size) levels.
- 9-segment ABC-XYZ portfolio matrix (AX through CZ).
- Audit and reconciliation against catalog ABC (Product.ABCCOD) and storage allocation policies.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ABC Pareto Classification
# ---------------------------------------------------------------------------

def compute_abc(
    df: pd.DataFrame,
    entity_col: str = "reference",
    qty_col: str = "qty",
    a_threshold: float = 0.80,
    b_threshold: float = 0.95,
) -> pd.DataFrame:
    """Compute Pareto ABC classification on cumulative volume.

    Parameters
    ----------
    df : pd.DataFrame
        Order lines or transaction records with entity_col and qty_col.
    entity_col : str
        Group identifier ('reference' or 'sku_size').
    qty_col : str
        Quantity column name.
    a_threshold : float
        Cumulative volume threshold for Class A (default: 0.80).
    b_threshold : float
        Cumulative volume threshold for Class B (default: 0.95).

    Returns
    -------
    pd.DataFrame
        DataFrame with [entity_col, 'total_units', 'cum_units', 'cum_share', 'abc_class'].
    """
    grouped = df.groupby(entity_col)[qty_col].sum().reset_index()
    grouped = grouped.rename(columns={qty_col: "total_units"})
    grouped = grouped.sort_values("total_units", ascending=False).reset_index(drop=True)

    total_volume = grouped["total_units"].sum()
    if total_volume <= 0:
        grouped["cum_units"] = 0.0
        grouped["cum_share"] = 0.0
        grouped["abc_class"] = "C"
        return grouped

    grouped["cum_units"] = grouped["total_units"].cumsum()
    grouped["cum_share"] = grouped["cum_units"] / total_volume

    conditions = [
        grouped["cum_share"] <= a_threshold,
        (grouped["cum_share"] > a_threshold) & (grouped["cum_share"] <= b_threshold),
        grouped["cum_share"] > b_threshold,
    ]
    choices = ["A", "B", "C"]

    # In standard Pareto, if the first item exceeds a_threshold, it still belongs to Class A
    grouped["abc_class"] = np.select(conditions, choices, default="C")
    if len(grouped) > 0 and grouped.loc[0, "abc_class"] != "A":
        grouped.loc[0, "abc_class"] = "A"

    return grouped


# ---------------------------------------------------------------------------
# XYZ Variability Classification
# ---------------------------------------------------------------------------

def compute_xyz(
    orders_df: pd.DataFrame,
    entity_col: str = "reference",
    qty_col: str = "qty",
    x_threshold: float = 0.50,
    y_threshold: float = 1.00,
) -> pd.DataFrame:
    """Compute demand predictability XYZ classification using weekly CV.

    CV = sigma / mu of weekly aggregate demand series.
    - X: CV < 0.50 (constant, steady demand, high forecast accuracy)
    - Y: 0.50 <= CV < 1.00 (fluctuating, moderate variability)
    - Z: CV >= 1.00 (intermittent, volatile demand, lumpy spikes)
    """
    df = orders_df.copy()
    df["dt"] = pd.to_datetime(df["date"])
    df["week"] = df["dt"].dt.to_period("W-SUN")

    # Pivot into entity x week matrix
    pivot = df.groupby([entity_col, "week"])[qty_col].sum().unstack(fill_value=0.0)

    means = pivot.mean(axis=1)
    stds = pivot.std(axis=1)

    # Avoid division by zero
    cv = np.where(means > 0, stds / means, 999.0)

    out = pd.DataFrame({
        entity_col: pivot.index,
        "mean_weekly_units": np.round(means.values, 2),
        "std_weekly_units": np.round(stds.values, 2),
        "cv": np.round(cv, 3),
    })

    conditions = [
        out["cv"] < x_threshold,
        (out["cv"] >= x_threshold) & (out["cv"] < y_threshold),
        out["cv"] >= y_threshold,
    ]
    choices = ["X", "Y", "Z"]
    out["xyz_class"] = np.select(conditions, choices, default="Z")

    return out.sort_values("mean_weekly_units", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Unified ABC-XYZ Matrix Builder
# ---------------------------------------------------------------------------

def compute_abc_xyz(
    orders_df: pd.DataFrame,
    entity_col: str = "reference",
    qty_col: str = "qty",
    a_threshold: float = 0.80,
    b_threshold: float = 0.95,
    x_threshold: float = 0.50,
    y_threshold: float = 1.00,
) -> pd.DataFrame:
    """Combine ABC volume and XYZ variability into 9 distinct management segments."""
    abc_df = compute_abc(
        orders_df,
        entity_col=entity_col,
        qty_col=qty_col,
        a_threshold=a_threshold,
        b_threshold=b_threshold,
    )
    xyz_df = compute_xyz(
        orders_df,
        entity_col=entity_col,
        qty_col=qty_col,
        x_threshold=x_threshold,
        y_threshold=y_threshold,
    )

    merged = pd.merge(abc_df, xyz_df, on=entity_col, how="inner")
    merged["abc_xyz"] = merged["abc_class"] + merged["xyz_class"]

    # Recommended inventory strategy
    strategy_map = {
        "AX": "Just-In-Time (JIT) / Continuous flow, minimal safety stock",
        "AY": "Periodic review, moderate safety buffer, primary pick face",
        "AZ": "High safety stock or make-to-order, forward pick face with replenishment",
        "BX": "Standard automated replenishment, moderate safety stock",
        "BY": "Periodic review (s, S), intermediate safety buffer",
        "BZ": "Lean buffer or centralized replenishment, high stockout monitoring",
        "CX": "Bulk periodic replenishment, low review frequency",
        "CY": "Opportunistic replenishment, minimal dedicated pick slots",
        "CZ": "Reserve tier storage only, order-triggered replenishment, tight capital control",
    }
    merged["strategy"] = merged["abc_xyz"].map(strategy_map)

    return merged.sort_values("total_units", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Reconciliation Audits
# ---------------------------------------------------------------------------

def audit_catalog_abc(
    orders_df: pd.DataFrame,
    products_df: pd.DataFrame,
) -> dict[str, Any]:
    """Compare empirical ABC classifications against Product.ABCCOD catalog values.

    Identifies catalog misclassifications where actual picking demand diverged
    from static master data.
    """
    empirical_abc = compute_abc(orders_df, entity_col="reference")
    merged = pd.merge(products_df[["reference", "abc"]], empirical_abc, on="reference", how="inner")
    merged = merged.rename(columns={"abc": "catalog_abc", "abc_class": "empirical_abc"})

    ct = pd.crosstab(merged["catalog_abc"], merged["empirical_abc"], margins=True)

    # Agreement rate
    match_count = (merged["catalog_abc"] == merged["empirical_abc"]).sum()
    total_count = len(merged)
    agreement_rate = round(match_count / total_count, 4) if total_count > 0 else 0.0

    # High-impact mismatches: catalog C that are actually empirical A (hidden fast movers)
    hidden_fast_movers = merged[(merged["catalog_abc"] == "C") & (merged["empirical_abc"] == "A")][
        ["reference", "total_units", "cum_share"]
    ].to_dict(orient="records")

    # Catalog A that are actually empirical C (dead stock occupying prime slots)
    obsolete_fast_movers = merged[(merged["catalog_abc"] == "A") & (merged["empirical_abc"] == "C")][
        ["reference", "total_units", "cum_share"]
    ].to_dict(orient="records")

    return {
        "total_skus": total_count,
        "agreement_count": int(match_count),
        "agreement_rate": agreement_rate,
        "crosstab": ct,
        "hidden_fast_movers_count": len(hidden_fast_movers),
        "hidden_fast_movers": hidden_fast_movers,
        "obsolete_fast_movers_count": len(obsolete_fast_movers),
        "obsolete_fast_movers": obsolete_fast_movers,
    }
