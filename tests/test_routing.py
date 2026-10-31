"""Unit tests for pick wave routing, 2-opt TSP optimization, and scenario evaluation."""

import numpy as np
import pandas as pd
import pytest

from warehouse_ai.optimization.routing import (
    scenario_summary,
    statistical_comparison,
    tour_len,
    tour_nn_2opt,
    tour_serpentine,
)
from warehouse_ai.utils.geometry import Network


@pytest.fixture
def synthetic_distance_network():
    """Distance matrix where a crossed tour exists:
    Depot at 0: (0, 0)
    Stop 1: (0, 10)
    Stop 2: (10, 10)
    Stop 3: (10, 0)
    Crossed tour 0 -> 1 -> 3 -> 2 -> 0 has length 10 + sqrt(200) + 10 + sqrt(200) ≈ 48.28
    Optimal uncrossed tour 0 -> 1 -> 2 -> 3 -> 0 has length 10 + 10 + 10 + 10 = 40.0
    """
    coords = np.array([[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0]])
    D = np.linalg.norm(coords[:, None] - coords[None, :], axis=-1)
    return D


def test_2opt_tsp_reversal_optimality(synthetic_distance_network):
    D = synthetic_distance_network
    tour = tour_nn_2opt(D, max_passes=10)
    assert tour[0] == 0
    assert tour[-1] == 0
    assert len(tour) == 5
    # Should find the optimal uncrossed rectangular tour of length 40.0
    assert tour_len(D, tour) == 40.0


def test_tour_serpentine_sweep():
    # 3 nodes: depot (0) and 2 stops in aisle 0
    net = Network(
        aisle_id=[0, 0, -1],
        along=[10.0, 30.0, 0.0],
        cross=[0.0, 0.0, 0.0],
        access=np.ones((3, 1), dtype=bool),
        xpos=[0.0],
        xnames=["CC"],
    )
    nodes = np.array([2, 0, 1])  # node 2 is depot, nodes 0 and 1 are stops
    D = net.matrix(nodes)
    tour = tour_serpentine(D, nodes, net)
    assert tour[0] == 0
    assert tour[-1] == 0
    assert len(tour) == 4
    # Depot to stop at 10.0 (dist 10), then to 30.0 (dist 20), back to depot (dist 30) = 60.0
    assert tour_len(D, tour) == 60.0


def test_scenario_summary_and_statistical_testing():
    # Synthetic wave results comparing two scenarios
    data = []
    for wid in range(1, 21):
        data.append({"wave": wid, "scenario": "AS-IS", "routing": "recorded", "dist_m": 160.0 + wid, "units": 20.0, "units_unplaced": 0.0, "stops": 10, "aisles": 4, "set": "train"})
        data.append({"wave": wid, "scenario": "AS-IS", "routing": "nn2opt", "dist_m": 140.0 + wid, "units": 20.0, "units_unplaced": 0.0, "stops": 10, "aisles": 4, "set": "train"})
        data.append({"wave": wid, "scenario": "Optimised", "routing": "nn2opt", "dist_m": 65.0 + wid, "units": 20.0, "units_unplaced": 0.0, "stops": 8, "aisles": 3, "set": "train"})

    res_df = pd.DataFrame(data)
    # Time calculations
    res_df["walk_s"] = res_df["dist_m"] / 1.0
    res_df["stop_s"] = res_df["stops"] * 10.0
    res_df["pick_s"] = res_df["units"] * 6.0
    res_df["setup_s"] = 60.0
    res_df["time_s"] = res_df["walk_s"] + res_df["stop_s"] + res_df["pick_s"] + res_df["setup_s"]
    res_df["minutes"] = res_df["time_s"] / 60.0

    summ = scenario_summary(res_df, base_key=("AS-IS", "recorded"))
    assert len(summ) >= 3

    # Wilcoxon test
    stat = statistical_comparison(res_df, ("AS-IS", "recorded"), ("Optimised", "nn2opt"))
    assert stat["n_waves"] == 20
    assert stat["median_saving_m"] > 90.0
    assert stat["waves_improved_pct"] == 100.0
    assert stat["p_value"] < 0.01
