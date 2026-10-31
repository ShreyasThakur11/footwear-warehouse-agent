"""Unit tests for storage allocation, demand profiling, and re-slotting optimization."""

from collections import Counter

import numpy as np
import pandas as pd
import pytest

from warehouse_ai.optimization.slotting import (
    abc_from_counts,
    build_demand_profile,
    design_slotting,
    min_move_layout,
)
from warehouse_ai.utils.geometry import Network


@pytest.fixture
def sample_picks():
    """Small sample of picks across 3 waves and 4 SKUs."""
    return pd.DataFrame([
        {"wave_number": 1, "reference": "BOOT_A", "sku_size": "BOOT_A|10.0", "qty": 2, "location": "A-01-11", "operator": "Op_1"},
        {"wave_number": 1, "reference": "BOOT_A", "sku_size": "BOOT_A|11.0", "qty": 1, "location": "A-01-12", "operator": "Op_1"},
        {"wave_number": 2, "reference": "BOOT_A", "sku_size": "BOOT_A|10.0", "qty": 3, "location": "A-01-11", "operator": "Op_1"},
        {"wave_number": 2, "reference": "BOOT_B", "sku_size": "BOOT_B|9.0", "qty": 1, "location": "B-02-11", "operator": "Op_2"},
        {"wave_number": 3, "reference": "BOOT_C", "sku_size": "BOOT_C|8.5", "qty": 1, "location": "B-02-12", "operator": "Op_2"},
    ])


@pytest.fixture
def toy_network():
    """Simple 2-aisle toy network for slotting tests."""
    # 4 locations: 2 pick face (lvl 1-2), 2 reserve (lvl 3-4)
    locs = pd.DataFrame([
        {"location": "LOC_1", "loc_id": 0, "level": 1, "dist_io": 5.0, "dist_rank": 1, "aisle_id": 0, "column": 1, "position": 1, "in_file": True},
        {"location": "LOC_2", "loc_id": 1, "level": 2, "dist_io": 6.0, "dist_rank": 2, "aisle_id": 0, "column": 1, "position": 2, "in_file": True},
        {"location": "LOC_3", "loc_id": 2, "level": 3, "dist_io": 5.0, "dist_rank": 3, "aisle_id": 0, "column": 1, "position": 0, "in_file": True},
        {"location": "LOC_4", "loc_id": 3, "level": 4, "dist_io": 6.0, "dist_rank": 4, "aisle_id": 0, "column": 1, "position": 0, "in_file": True},
    ])
    net = Network(
        aisle_id=[0, 0, 0, 0, -1],
        along=[5.0, 6.0, 5.0, 6.0, 0.0],
        cross=[0.0, 0.0, 0.0, 0.0, 0.0],
        access=np.ones((5, 1), dtype=bool),
        xpos=[0.0],
        xnames=["CC"],
    )
    return locs, net


def test_abc_classification():
    counts = pd.Series([100, 50, 20, 10, 5, 2], index=["SKU_1", "SKU_2", "SKU_3", "SKU_4", "SKU_5", "SKU_6"])
    abc = abc_from_counts(counts, cuts=(0.80, 0.95))
    # Cumulative: 100/187 = 53.5% (A), +50 = 80.2% (B), +20 = 90.9% (B), +10 = 96.2% (C)...
    assert abc["SKU_1"] == "A"
    assert abc["SKU_2"] in ("A", "B")
    assert abc["SKU_6"] == "C"


def test_demand_profile_structure(sample_picks):
    waves, dem_sku, dem_ref, n_days = build_demand_profile(sample_picks, train_fraction=0.7)
    assert len(waves) == 3
    assert len(dem_sku) >= 4
    assert len(dem_ref) >= 3
    assert "visits" in dem_sku.columns
    assert "coi_density" in dem_sku.columns
    assert "abc" in dem_sku.columns
    # BOOT_A|10.0 had 2 visits out of 3 waves
    assert dem_sku.loc["BOOT_A|10.0", "visits_all"] == 2


def test_design_slotting_family_and_coi(toy_network):
    locs, net = toy_network
    dem = pd.DataFrame(
        {"visits": [20, 15, 5], "daily_units": [5.0, 3.0, 1.0], "ref": ["BOOT_A", "BOOT_A", "BOOT_B"]},
        index=["BOOT_A|10.0", "BOOT_A|11.0", "BOOT_B|9.0"],
    )
    stock = pd.Series([10, 10, 10], index=["BOOT_A|10.0", "BOOT_A|11.0", "BOOT_B|9.0"])

    lay_fam, info_fam = design_slotting("FAMILY", dem, stock, locs, net, slots_per_location=2)
    assert info_fam["variant"] == "FAMILY"
    assert info_fam["primary_slots"] > 0
    assert "role" in lay_fam.columns

    lay_coi, info_coi = design_slotting("COI", dem, stock, locs, net, slots_per_location=2)
    assert info_coi["variant"] == "COI"
    assert len(lay_coi) == len(lay_fam)


def test_min_move_layout_swap_integrity(toy_network):
    locs, net = toy_network
    # Current inventory: 2 locations x 2 slots = 4 slots
    base_inv = pd.DataFrame([
        {"loc_id": 0, "slot": 1, "key": "BOOT_B|9.0", "level": 1, "dist_io": 5.0, "dist_rank": 1, "pickable": True},
        {"loc_id": 0, "slot": 2, "key": "BOOT_C|8.0", "level": 1, "dist_io": 5.0, "dist_rank": 1, "pickable": True},
        {"loc_id": 1, "slot": 1, "key": "BOOT_A|10.0", "level": 2, "dist_io": 6.0, "dist_rank": 2, "pickable": True},
        {"loc_id": 1, "slot": 2, "key": "BOOT_A|11.0", "level": 2, "dist_io": 6.0, "dist_rank": 2, "pickable": True},
    ])
    # Target design wants BOOT_A|10.0 in LOC_1 (loc_id 0)
    design = pd.DataFrame([
        {"loc_id": 0, "slot": 1, "sku": "BOOT_A|10.0", "role": "primary pick face"},
        {"loc_id": 0, "slot": 2, "sku": "BOOT_A|11.0", "role": "primary pick face"},
    ])

    final_lay, moves_df = min_move_layout(
        design_df=design,
        base_inv_df=base_inv,
        locs_df=locs,
        net=net,
        key="sku",
        variant="FAMILY",
        slots_per_location=2,
    )

    # Moves should swap BOOT_A into LOC_1 and displace existing items
    assert len(moves_df) > 0
    # Total units across warehouse must be completely preserved
    assert len(final_lay) == len(base_inv)
    assert Counter(final_lay["sku"]) == Counter(base_inv["key"])
