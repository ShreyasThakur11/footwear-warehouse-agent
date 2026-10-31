"""Unit tests for replenishment optimization and simulation models."""

from __future__ import annotations

import pandas as pd
import pytest

from warehouse_ai.models.replenishment import (
    ABC_XYZ_OPTIMIZED_POLICY,
    LEAN_JIT_POLICY,
    calculate_sku_targets,
    replenishment_plan,
    simulate_replenishment_policy,
)


@pytest.fixture
def synthetic_orders_fixture() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2023-01-02", periods=28, freq="D")
    for d in dates:
        if d.dayofweek < 5:  # Monday - Friday
            rows.append({"sku_size": "SKU_FAST|10.0", "date": d.date(), "qty": 10})
            rows.append({"sku_size": "SKU_SLOW|8.5", "date": d.date(), "qty": 1})
    return pd.DataFrame(rows)


def test_calculate_sku_targets(synthetic_orders_fixture):
    targets = calculate_sku_targets(synthetic_orders_fixture, ABC_XYZ_OPTIMIZED_POLICY)
    assert len(targets) == 2
    fast = targets[targets["sku_size"] == "SKU_FAST|10.0"].iloc[0]
    slow = targets[targets["sku_size"] == "SKU_SLOW|8.5"].iloc[0]

    assert fast["abc_class"] == "A"
    assert fast["mean_daily"] > slow["mean_daily"]
    assert fast["reorder_point"] > slow["reorder_point"]
    assert fast["order_up_to"] > fast["reorder_point"]


def test_simulate_replenishment_policy(synthetic_orders_fixture):
    daily = pd.DataFrame({"date": pd.date_range("2023-01-02", periods=28, freq="D")})
    res, log_df = simulate_replenishment_policy(synthetic_orders_fixture, LEAN_JIT_POLICY, daily_df=daily)
    assert res.total_demand_units > 0
    assert res.unit_fill_rate > 0.50
    assert len(log_df) == 28


def test_replenishment_plan_directives(synthetic_orders_fixture):
    plan = replenishment_plan(
        date="2023-01-15",
        current_pick_face_stock={"SKU_FAST|10.0": 1, "SKU_SLOW|8.5": 5},
        current_reserve_stock={"SKU_FAST|10.0": 20, "SKU_SLOW|8.5": 10},
        orders_df=synthetic_orders_fixture,
    )
    assert "pick_face_transfers" in plan
    assert "supplier_purchase_orders" in plan
    transfers = plan["pick_face_transfers"]
    assert len(transfers) >= 1
    assert "SKU_FAST|10.0" in transfers["sku_size"].values

