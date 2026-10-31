"""Unit tests for models/waves.py — wave batching, operator assignment, and evaluation API."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from warehouse_ai.models.waves import (
    WavePlan,
    batch_aisle_cluster,
    batch_fcfs,
    batch_seed_savings,
    plan_waves,
    replay_historical_waves,
)

# ---------------------------------------------------------------------------
# Fixtures — tiny synthetic 2-aisle warehouse
# ---------------------------------------------------------------------------

@pytest.fixture()
def toy_orders() -> pd.DataFrame:
    """12 order lines across 4 orders and 4 SKU-sizes."""
    return pd.DataFrame([
        {"order_number": 1, "sku_size": "BOOT_A|10.0", "qty": 6, "created_at": pd.Timestamp("2023-01-05 07:00")},
        {"order_number": 1, "sku_size": "BOOT_A|11.0", "qty": 3, "created_at": pd.Timestamp("2023-01-05 07:00")},
        {"order_number": 2, "sku_size": "BOOT_B|9.0",  "qty": 4, "created_at": pd.Timestamp("2023-01-05 07:01")},
        {"order_number": 2, "sku_size": "BOOT_B|10.0", "qty": 2, "created_at": pd.Timestamp("2023-01-05 07:01")},
        {"order_number": 3, "sku_size": "BOOT_A|10.0", "qty": 5, "created_at": pd.Timestamp("2023-01-05 07:02")},
        {"order_number": 3, "sku_size": "BOOT_C|8.5",  "qty": 3, "created_at": pd.Timestamp("2023-01-05 07:02")},
        {"order_number": 4, "sku_size": "BOOT_D|12.0", "qty": 6, "created_at": pd.Timestamp("2023-01-05 07:03")},
        {"order_number": 4, "sku_size": "BOOT_D|13.0", "qty": 5, "created_at": pd.Timestamp("2023-01-05 07:03")},
    ])


@pytest.fixture()
def toy_storage() -> pd.DataFrame:
    """One SKU-size per location under 'random' policy."""
    return pd.DataFrame([
        {"policy": "random", "location": "A-01-11", "sku_size": "BOOT_A|10.0", "reference": "BOOT_A", "size": 10.0},
        {"policy": "random", "location": "A-02-11", "sku_size": "BOOT_A|11.0", "reference": "BOOT_A", "size": 11.0},
        {"policy": "random", "location": "B-01-11", "sku_size": "BOOT_B|9.0",  "reference": "BOOT_B", "size": 9.0},
        {"policy": "random", "location": "B-02-11", "sku_size": "BOOT_B|10.0", "reference": "BOOT_B", "size": 10.0},
        {"policy": "random", "location": "A-03-11", "sku_size": "BOOT_C|8.5",  "reference": "BOOT_C", "size": 8.5},
        {"policy": "random", "location": "B-03-11", "sku_size": "BOOT_D|12.0", "reference": "BOOT_D", "size": 12.0},
        {"policy": "random", "location": "B-04-11", "sku_size": "BOOT_D|13.0", "reference": "BOOT_D", "size": 13.0},
    ])


@pytest.fixture()
def toy_locations() -> pd.DataFrame:
    """Location metadata for 7 toy shelf positions."""
    return pd.DataFrame([
        {"location": "A-01-11", "x": 100.0, "y": 100.0, "z": 1.0, "aisle": "A", "bay": 1, "level": 1, "slot": 1},
        {"location": "A-02-11", "x": 100.0, "y": 200.0, "z": 1.0, "aisle": "A", "bay": 2, "level": 1, "slot": 1},
        {"location": "A-03-11", "x": 100.0, "y": 300.0, "z": 1.0, "aisle": "A", "bay": 3, "level": 1, "slot": 1},
        {"location": "B-01-11", "x": 300.0, "y": 100.0, "z": 1.0, "aisle": "B", "bay": 1, "level": 1, "slot": 1},
        {"location": "B-02-11", "x": 300.0, "y": 200.0, "z": 1.0, "aisle": "B", "bay": 2, "level": 1, "slot": 1},
        {"location": "B-03-11", "x": 300.0, "y": 300.0, "z": 1.0, "aisle": "B", "bay": 3, "level": 1, "slot": 1},
        {"location": "B-04-11", "x": 300.0, "y": 400.0, "z": 1.0, "aisle": "B", "bay": 4, "level": 1, "slot": 1},
    ])


@pytest.fixture()
def toy_mapped(toy_orders, toy_storage, toy_locations) -> pd.DataFrame:
    """Pre-joined order → location mapping."""
    from warehouse_ai.models.waves import _build_order_location_map
    return _build_order_location_map(toy_orders, toy_storage, toy_locations, policy="random")


@pytest.fixture()
def toy_waves() -> pd.DataFrame:
    """Minimal waves table for 2 historical waves."""
    return pd.DataFrame([
        {
            "wave_id": 101, "first_created_at": pd.Timestamp("2023-01-05 07:00"),
            "last_created_at": pd.Timestamp("2023-01-05 07:00"),
            "n_orders": 2, "n_lines": 4, "n_units": 9, "n_distinct_locations": 3.0,
            "n_aisles": 2.0, "operator": "Operator_1", "date": "2023-01-05", "travel_dist": 1500.0,
        },
        {
            "wave_id": 102, "first_created_at": pd.Timestamp("2023-01-05 07:05"),
            "last_created_at": pd.Timestamp("2023-01-05 07:05"),
            "n_orders": 2, "n_lines": 4, "n_units": 14, "n_distinct_locations": 4.0,
            "n_aisles": 2.0, "operator": "Operator_2", "date": "2023-01-05", "travel_dist": 2200.0,
        },
    ])


@pytest.fixture()
def toy_picks() -> pd.DataFrame:
    """Minimal picks table for the 2 historical waves above."""
    return pd.DataFrame([
        {"wave_number": 101, "location": "A-01-11", "qty": 6, "aisle": "A", "x": 100.0, "y": 100.0, "z": 1.0},
        {"wave_number": 101, "location": "A-02-11", "qty": 3, "aisle": "A", "x": 100.0, "y": 200.0, "z": 1.0},
        {"wave_number": 101, "location": "B-01-11", "qty": 0, "aisle": "B", "x": 300.0, "y": 100.0, "z": 1.0},
        {"wave_number": 102, "location": "B-01-11", "qty": 4, "aisle": "B", "x": 300.0, "y": 100.0, "z": 1.0},
        {"wave_number": 102, "location": "B-02-11", "qty": 2, "aisle": "B", "x": 300.0, "y": 200.0, "z": 1.0},
        {"wave_number": 102, "location": "A-03-11", "qty": 3, "aisle": "A", "x": 100.0, "y": 300.0, "z": 1.0},
        {"wave_number": 102, "location": "B-03-11", "qty": 5, "aisle": "B", "x": 300.0, "y": 300.0, "z": 1.0},
    ])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestBuildOrderLocationMap:
    def test_returns_dataframe(self, toy_orders, toy_storage, toy_locations) -> None:
        from warehouse_ai.models.waves import _build_order_location_map
        result = _build_order_location_map(toy_orders, toy_storage, toy_locations)
        assert isinstance(result, pd.DataFrame)

    def test_all_mapped_orders_have_location(self, toy_orders, toy_storage, toy_locations) -> None:
        from warehouse_ai.models.waves import _build_order_location_map
        result = _build_order_location_map(toy_orders, toy_storage, toy_locations)
        assert result["location"].notna().all()

    def test_has_required_columns(self, toy_orders, toy_storage, toy_locations) -> None:
        from warehouse_ai.models.waves import _build_order_location_map
        result = _build_order_location_map(toy_orders, toy_storage, toy_locations)
        for col in ("order_number", "sku_size", "qty", "location", "aisle"):
            assert col in result.columns


# ---------------------------------------------------------------------------
# FCFS batching
# ---------------------------------------------------------------------------

class TestBatchFCFS:
    def test_returns_list_of_lists(self, toy_orders, toy_mapped) -> None:
        batches = batch_fcfs(toy_orders, max_units=27, max_orders=24, mapped=toy_mapped)
        assert isinstance(batches, list)
        assert all(isinstance(b, list) for b in batches)

    def test_all_orders_assigned(self, toy_orders, toy_mapped) -> None:
        batches = batch_fcfs(toy_orders, max_units=27, max_orders=24, mapped=toy_mapped)
        assigned = [o for b in batches for o in b]
        original = sorted(toy_orders["order_number"].unique())
        assert sorted(assigned) == original

    def test_unit_capacity_respected(self, toy_orders, toy_mapped) -> None:
        order_qty = toy_orders.groupby("order_number")["qty"].sum().to_dict()
        batches = batch_fcfs(toy_orders, max_units=10, max_orders=24, mapped=toy_mapped)
        for batch in batches:
            total = sum(order_qty.get(o, 0) for o in batch)
            # A single oversized order is allowed alone
            if len(batch) > 1:
                assert total <= 10, f"Batch {batch} has {total} units > 10"

    def test_max_orders_respected(self, toy_orders, toy_mapped) -> None:
        batches = batch_fcfs(toy_orders, max_units=999, max_orders=2, mapped=toy_mapped)
        for batch in batches:
            assert len(batch) <= 2

    def test_empty_orders_returns_empty(self) -> None:
        empty = pd.DataFrame(columns=["order_number", "sku_size", "qty", "created_at"])
        empty_map = pd.DataFrame(columns=["order_number", "sku_size", "qty", "location", "aisle"])
        batches = batch_fcfs(empty, max_units=27, max_orders=24, mapped=empty_map)
        assert batches == []


# ---------------------------------------------------------------------------
# Seed + Savings batching
# ---------------------------------------------------------------------------

class TestBatchSeedSavings:
    def test_returns_list_of_lists(self, toy_orders, toy_mapped, toy_locations) -> None:
        rng = np.random.default_rng(42)
        batches = batch_seed_savings(toy_orders, 27, 24, toy_mapped, toy_locations, rng=rng)
        assert isinstance(batches, list)
        assert all(isinstance(b, list) for b in batches)

    def test_all_orders_covered(self, toy_orders, toy_mapped, toy_locations) -> None:
        rng = np.random.default_rng(42)
        batches = batch_seed_savings(toy_orders, 27, 24, toy_mapped, toy_locations, rng=rng)
        assigned = sorted([o for b in batches for o in b])
        original = sorted(toy_orders["order_number"].unique())
        assert assigned == original

    def test_unit_capacity_respected(self, toy_orders, toy_mapped, toy_locations) -> None:
        order_qty = toy_orders.groupby("order_number")["qty"].sum().to_dict()
        rng = np.random.default_rng(42)
        batches = batch_seed_savings(toy_orders, max_units=10, max_orders=24,
                                     mapped=toy_mapped, locations_df=toy_locations, rng=rng)
        for batch in batches:
            total = sum(order_qty.get(o, 0) for o in batch)
            if len(batch) > 1:
                assert total <= 10, f"Batch {batch} has {total} units > 10"


# ---------------------------------------------------------------------------
# Aisle-cluster batching
# ---------------------------------------------------------------------------

class TestBatchAisleCluster:
    def test_returns_list_of_lists(self, toy_orders, toy_mapped) -> None:
        rng = np.random.default_rng(42)
        batches = batch_aisle_cluster(toy_orders, 27, 24, toy_mapped, rng=rng)
        assert isinstance(batches, list)
        assert all(isinstance(b, list) for b in batches)

    def test_all_orders_covered(self, toy_orders, toy_mapped) -> None:
        rng = np.random.default_rng(42)
        batches = batch_aisle_cluster(toy_orders, 27, 24, toy_mapped, rng=rng)
        assigned = sorted([o for b in batches for o in b])
        original = sorted(toy_orders["order_number"].unique())
        assert assigned == original


# ---------------------------------------------------------------------------
# plan_waves public API
# ---------------------------------------------------------------------------

class TestPlanWaves:
    def test_returns_list_of_wave_plans(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders,
            n_operators=2,
            algorithm="fcfs",
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        assert isinstance(plans, list)
        assert all(isinstance(p, WavePlan) for p in plans)

    def test_wave_plans_non_empty(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        assert len(plans) > 0

    def test_operator_assigned(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=3, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        for p in plans:
            assert p.operator != "", "All waves must have an operator assigned"

    def test_operators_within_n(self, toy_orders, toy_storage, toy_locations) -> None:
        n_ops = 2
        plans = plan_waves(
            orders_df=toy_orders, n_operators=n_ops, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        used = {p.operator for p in plans}
        assert len(used) <= n_ops

    def test_estimated_time_positive(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        for p in plans:
            assert p.estimated_time_s >= 0.0

    def test_seed_savings_algorithm(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="seed_savings",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        assert len(plans) > 0
        assert all(p.algorithm == "seed_savings" for p in plans)

    def test_aisle_cluster_algorithm(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="aisle_cluster",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        assert len(plans) > 0

    def test_unknown_algorithm_raises(self, toy_orders, toy_storage, toy_locations) -> None:
        with pytest.raises(ValueError, match="Unknown algorithm"):
            plan_waves(
                orders_df=toy_orders, n_operators=1, algorithm="bad_algo",
                storage_df=toy_storage, locations_df=toy_locations,
            )

    def test_wave_plan_to_dict(self, toy_orders, toy_storage, toy_locations) -> None:
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        d = plans[0].to_dict()
        for key in ("wave_index", "n_orders", "n_units", "estimated_travel",
                    "estimated_time_s", "operator", "algorithm"):
            assert key in d

    def test_max_units_capacity(self, toy_orders, toy_storage, toy_locations) -> None:
        """Waves must not exceed max_units (unless a single oversized order)."""
        plans = plan_waves(
            orders_df=toy_orders, n_operators=2, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
            max_units=8,
        )
        for p in plans:
            if p.n_orders > 1:
                assert p.n_units <= 8, f"Wave {p.wave_index} has {p.n_units} units > 8"

    def test_lpt_balances_load(self, toy_orders, toy_storage, toy_locations) -> None:
        """LPT operator assignment: heaviest wave goes to least-loaded operator."""
        plans = plan_waves(
            orders_df=toy_orders, n_operators=4, algorithm="fcfs",
            storage_df=toy_storage, locations_df=toy_locations,
        )
        op_loads: dict[str, float] = {}
        for p in plans:
            op_loads[p.operator] = op_loads.get(p.operator, 0.0) + p.estimated_time_s
        if len(op_loads) > 1:
            loads = list(op_loads.values())
            # LPT guarantees max/min ratio ≤ 4/3 for identical jobs;
            # with real data we just check the spread is not extreme
            assert max(loads) / max(min(loads), 1.0) < 20.0


# ---------------------------------------------------------------------------
# replay_historical_waves
# ---------------------------------------------------------------------------

class TestReplayHistoricalWaves:
    def test_returns_list(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks)
        assert isinstance(plans, list)

    def test_count_matches_waves(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks)
        assert len(plans) == len(toy_waves)

    def test_algorithm_label(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks)
        assert all(p.algorithm == "historical" for p in plans)

    def test_travel_matches_record(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks)
        recorded = toy_waves["travel_dist"].tolist()
        for plan, rec_travel in zip(plans, recorded):
            assert plan.estimated_travel == pytest.approx(rec_travel, abs=1.0)

    def test_date_filter(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks, date="2023-01-05")
        assert len(plans) == 2   # both waves are on 2023-01-05

    def test_date_filter_no_match(self, toy_waves, toy_picks) -> None:
        plans = replay_historical_waves(waves_df=toy_waves, picks_df=toy_picks, date="1900-01-01")
        assert plans == []
