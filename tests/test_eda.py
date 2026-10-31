from pathlib import Path

import pandas as pd
import pytest

from warehouse_ai.analysis.eda import (
    compute_daily_trends,
    compute_order_and_wave_distributions,
    compute_pareto_analysis,
    compute_storage_policy_coverage,
    compute_temporal_profiles,
)

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


@pytest.fixture
def sample_data():
    daily = pd.read_parquet(PROCESSED_DIR / "daily.parquet")
    orders = pd.read_parquet(PROCESSED_DIR / "orders_clean.parquet")
    waves = pd.read_parquet(PROCESSED_DIR / "waves.parquet")
    storage = pd.read_parquet(PROCESSED_DIR / "storage_long.parquet")
    return {"daily": daily, "orders": orders, "waves": waves, "storage": storage}


def test_compute_daily_trends(sample_data):
    trends = compute_daily_trends(sample_data["daily"])
    assert "orders_rolling_7d" in trends.columns
    assert len(trends) == len(sample_data["daily"])
    assert not trends["orders_rolling_7d"].isna().all()


def test_compute_temporal_profiles(sample_data):
    dow_df, hour_df = compute_temporal_profiles(sample_data["orders"])
    assert len(dow_df) <= 7
    assert "day_name" in dow_df.columns
    assert "share_of_orders_pct" in hour_df.columns
    assert 7 in hour_df["hour"].values


def test_compute_order_and_wave_distributions(sample_data):
    stats = compute_order_and_wave_distributions(sample_data["orders"], sample_data["waves"])
    assert "order_units" in stats
    assert "wave_units" in stats
    assert stats["wave_units"]["mean"] > 0


def test_compute_pareto_analysis(sample_data):
    sku_demand, size_demand, metrics = compute_pareto_analysis(sample_data["orders"])
    assert not sku_demand.empty
    assert "cum_units_pct" in sku_demand.columns
    assert metrics["top_20pct_units_share"] > 50.0  # Should be ~80%
    assert not size_demand.empty


def test_compute_storage_policy_coverage(sample_data):
    coverage = compute_storage_policy_coverage(sample_data["storage"])
    assert len(coverage) == 4
    for policy in ["random", "class_based", "dedicated", "hybrid"]:
        assert policy in coverage["policy"].values
