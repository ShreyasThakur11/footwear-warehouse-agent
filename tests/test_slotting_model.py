"""Unit tests for models/slotting.py — policy simulator, COI layout, co-picking, reslotting API."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from warehouse_ai.models.slotting import (
    compute_co_picking_pairs,
    generate_coi_slotting,
    recommend_reslotting,
    simulate_storage_policy,
)

# ---------------------------------------------------------------------------
# Fixtures — tiny synthetic 2-aisle warehouse
# ---------------------------------------------------------------------------

@pytest.fixture()
def toy_picks() -> pd.DataFrame:
    """20 pick records across 4 waves, 3 SKU-sizes, 4 locations."""
    rng = np.random.default_rng(42)
    skus = ["BOOT_A|10.0", "BOOT_A|11.0", "BOOT_B|9.0"]
    locs = ["A-01-11", "A-02-11", "B-01-11", "B-02-11"]

    rows = []
    for wave in range(1, 5):
        for i in range(5):
            rows.append({
                "wave_number": wave,
                "sku_size": rng.choice(skus),
                "location": rng.choice(locs),
                "qty": int(rng.integers(1, 4)),
                "operator": "Op_1",
                "x": rng.uniform(50, 400),
                "y": rng.uniform(0, 600),
                "z": 1.0,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def toy_locations() -> pd.DataFrame:
    """Four storage locations for the toy 2-aisle layout."""
    return pd.DataFrame([
        {"location": "A-01-11", "x": 100.0, "y": 100.0, "z": 1.0, "aisle": "A", "bay": 1, "level": 1},
        {"location": "A-02-11", "x": 100.0, "y": 200.0, "z": 1.0, "aisle": "A", "bay": 2, "level": 1},
        {"location": "B-01-11", "x": 300.0, "y": 100.0, "z": 1.0, "aisle": "B", "bay": 1, "level": 1},
        {"location": "B-02-11", "x": 300.0, "y": 200.0, "z": 1.0, "aisle": "B", "bay": 2, "level": 1},
    ])


@pytest.fixture()
def toy_storage(toy_locations: pd.DataFrame) -> pd.DataFrame:
    """Simple storage table: one SKU-size per location under 'random' policy."""
    skus = ["BOOT_A|10.0", "BOOT_A|11.0", "BOOT_B|9.0", "BOOT_B|10.0"]
    locs = toy_locations["location"].tolist()
    rows = [
        {"policy": "random", "location": locs[i], "sku_size": skus[i], "reference": skus[i].split("|")[0], "size": float(skus[i].split("|")[1])}
        for i in range(len(locs))
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# compute_co_picking_pairs
# ---------------------------------------------------------------------------

class TestComputeCoPickingPairs:
    def test_returns_dataframe(self, toy_picks: pd.DataFrame) -> None:
        result = compute_co_picking_pairs(toy_picks, min_co_picks=1)
        assert isinstance(result, pd.DataFrame)

    def test_columns(self, toy_picks: pd.DataFrame) -> None:
        result = compute_co_picking_pairs(toy_picks, min_co_picks=1)
        assert set(result.columns) >= {"sku_a", "sku_b", "co_pick_waves"}

    def test_sorted_descending(self, toy_picks: pd.DataFrame) -> None:
        result = compute_co_picking_pairs(toy_picks, min_co_picks=1)
        if len(result) > 1:
            assert result["co_pick_waves"].is_monotonic_decreasing

    def test_min_threshold_filters(self, toy_picks: pd.DataFrame) -> None:
        all_pairs = compute_co_picking_pairs(toy_picks, min_co_picks=1)
        filtered = compute_co_picking_pairs(toy_picks, min_co_picks=999)
        assert len(filtered) <= len(all_pairs)
        if len(filtered) > 0:
            assert (filtered["co_pick_waves"] >= 999).all()

    def test_no_self_pairs(self, toy_picks: pd.DataFrame) -> None:
        result = compute_co_picking_pairs(toy_picks, min_co_picks=1)
        if len(result) > 0:
            assert (result["sku_a"] != result["sku_b"]).all()

    def test_empty_picks_returns_empty(self) -> None:
        empty = pd.DataFrame(columns=["wave_number", "sku_size"])
        result = compute_co_picking_pairs(empty, min_co_picks=1)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_single_wave_single_sku_returns_empty(self) -> None:
        single = pd.DataFrame({"wave_number": [1, 1], "sku_size": ["SKU_A|10", "SKU_A|10"]})
        result = compute_co_picking_pairs(single, min_co_picks=1)
        # Only one unique SKU per wave — no pairs
        assert len(result) == 0


# ---------------------------------------------------------------------------
# generate_coi_slotting
# ---------------------------------------------------------------------------

class TestGenerateCOISlotting:
    def test_returns_dataframe(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=18, use_co_picking=False)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=18, use_co_picking=False)
        assert "sku_size" in result.columns
        assert "location" in result.columns
        assert "policy" in result.columns

    def test_policy_label(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=18, use_co_picking=False)
        assert (result["policy"] == "optimised_coi").all()

    def test_slots_per_location_respected(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        slots = 3
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=slots, use_co_picking=False)
        n_locs = toy_locations.shape[0]
        # Total assignments cannot exceed n_locs * slots
        assert len(result) <= n_locs * slots

    def test_no_duplicate_sku_in_same_slot(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=18, use_co_picking=False)
        assert result["sku_size"].nunique() == len(result)

    def test_with_co_picking(self, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame) -> None:
        result = generate_coi_slotting(toy_picks, toy_locations, slots_per_location=18, use_co_picking=True)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# simulate_storage_policy
# ---------------------------------------------------------------------------

class TestSimulateStoragePolicy:
    def test_returns_summary_and_wave_df(
        self, toy_storage: pd.DataFrame, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        summary, wave_df = simulate_storage_policy(
            policy_name="random",
            storage_df=toy_storage,
            picks_df=toy_picks,
            locations_df=toy_locations,
            max_waves=4,
        )
        assert isinstance(summary, dict)
        assert isinstance(wave_df, pd.DataFrame)

    def test_summary_keys(
        self, toy_storage: pd.DataFrame, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        summary, _ = simulate_storage_policy(
            policy_name="random",
            storage_df=toy_storage,
            picks_df=toy_picks,
            locations_df=toy_locations,
            max_waves=4,
        )
        for key in ("policy_name", "total_waves", "total_picks", "total_travel_distance", "mean_wave_travel"):
            assert key in summary, f"Missing key: {key}"

    def test_wave_df_shape(
        self, toy_storage: pd.DataFrame, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        _, wave_df = simulate_storage_policy(
            policy_name="random",
            storage_df=toy_storage,
            picks_df=toy_picks,
            locations_df=toy_locations,
            max_waves=4,
        )
        assert "wave_number" in wave_df.columns
        assert "travel_distance" in wave_df.columns
        # At most 4 waves
        assert len(wave_df) <= 4

    def test_total_travel_non_negative(
        self, toy_storage: pd.DataFrame, toy_picks: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        summary, _ = simulate_storage_policy(
            policy_name="random",
            storage_df=toy_storage,
            picks_df=toy_picks,
            locations_df=toy_locations,
            max_waves=4,
        )
        assert summary["total_travel_distance"] >= 0.0


# ---------------------------------------------------------------------------
# recommend_reslotting
# ---------------------------------------------------------------------------

class TestRecommendReslotting:
    def test_returns_list(
        self, toy_picks: pd.DataFrame, toy_storage: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        moves = recommend_reslotting(
            baseline_policy="random",
            top_n=5,
            picks_df=toy_picks,
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        assert isinstance(moves, list)

    def test_top_n_respected(
        self, toy_picks: pd.DataFrame, toy_storage: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        moves = recommend_reslotting(
            baseline_policy="random",
            top_n=2,
            picks_df=toy_picks,
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        assert len(moves) <= 2

    def test_required_fields_present(
        self, toy_picks: pd.DataFrame, toy_storage: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        moves = recommend_reslotting(
            baseline_policy="random",
            top_n=5,
            picks_df=toy_picks,
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        if moves:
            for field in ("sku_size", "from_location", "to_location", "expected_travel_saved_per_week", "move_effort"):
                assert field in moves[0], f"Missing field: {field}"

    def test_sorted_by_travel_savings(
        self, toy_picks: pd.DataFrame, toy_storage: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        moves = recommend_reslotting(
            baseline_policy="random",
            top_n=10,
            picks_df=toy_picks,
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        savings = [m["expected_travel_saved_per_week"] for m in moves]
        assert savings == sorted(savings, reverse=True)

    def test_no_self_moves(
        self, toy_picks: pd.DataFrame, toy_storage: pd.DataFrame, toy_locations: pd.DataFrame
    ) -> None:
        moves = recommend_reslotting(
            baseline_policy="random",
            top_n=10,
            picks_df=toy_picks,
            storage_df=toy_storage,
            locations_df=toy_locations,
        )
        for m in moves:
            assert m["from_location"] != m["to_location"]
