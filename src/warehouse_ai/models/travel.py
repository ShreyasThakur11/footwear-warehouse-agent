"""Warehouse travel distance model and route optimization.

Constructs a networkx graph of the physical warehouse (support points, aisle
centrelines, and projected storage locations), precomputes all-pairs Dijkstra
distances, and implements standard warehouse tour heuristics:
- Nearest Neighbor (NN)
- S-Shape (Serpentine)
- Largest Gap
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from warehouse_ai.data.loaders import load_locations, load_support_points

_ROOT = Path(__file__).resolve().parents[3]
_LOC_PATTERN = re.compile(r"^(?P<aisle>[A-Za-z]+)-(?P<bay>\d+)-(?P<level_slot>\d{2})$")


def build_warehouse_graph(
    locations_df: pd.DataFrame | None = None,
    support_points_df: pd.DataFrame | None = None,
) -> nx.Graph:
    """Build a networkx graph representing the warehouse walkways and corridors.

    Nodes
    -----
    - Support points: corridor waypoints from Support_Points_Navigation (LC, CC, RC)
    - Waypoint nodes: projected aisle positions along aisle centrelines
    - Storage locations: every physical shelf location connected to its aisle centreline

    Edges
    -----
    - Longitudinal cross-corridors connecting consecutive support points (LC, CC, RC)
    - Horizontal aisles connecting LC, aisle waypoints, CC, and RC (for aisles 8-17)
    - Zero-weight projection edges connecting storage locations to their aisle waypoints
    """
    if locations_df is None:
        loc_path = _ROOT / "data" / "processed" / "locations.parquet"
        if loc_path.exists():
            locations_df = pd.read_parquet(loc_path)
        else:
            locations_df = load_locations()

    if support_points_df is None:
        support_points_df = load_support_points()

    G = nx.Graph()

    # 1. Add Support Points
    for _, row in support_points_df.iterrows():
        G.add_node(
            row["label"],
            x=float(row["x"]),
            y=float(row["y"]),
            node_type="support",
        )

    # 2. Add Longitudinal Corridor Edges (LC, CC, RC)
    for prefix in ["LC", "CC", "RC"]:
        sub = support_points_df[support_points_df["label"].str.startswith(prefix)].copy()
        sub["idx"] = sub["label"].str[-2:].astype(int)
        sub = sub.sort_values("idx").reset_index(drop=True)
        for i in range(len(sub) - 1):
            u, v = sub.iloc[i], sub.iloc[i + 1]
            dist = abs(float(v["y"]) - float(u["y"]))
            G.add_edge(u["label"], v["label"], weight=dist)

    # 3. Determine Aisle Centrelines from Support Points y levels
    y_levels = sorted(support_points_df["y"].unique())
    locs = locations_df.copy()

    # Map each location to the closest aisle centreline y level
    locs["aisle_y"] = locs["y"].apply(
        lambda ly: y_levels[int(np.argmin([abs(ly - yl) for yl in y_levels]))]
    )

    # 4. Add Horizontal Aisle Edges along each of the 17 aisles
    for k, y_val in enumerate(y_levels, start=1):
        lc_label = f"LC-{k:02d}"
        cc_label = f"CC-{k:02d}"
        rc_label = f"RC-{k:02d}" if k >= 8 else None

        sub_locs = locs[locs["aisle_y"] == y_val]

        # Left Block: between LC (x=66) and CC (x=403)
        left_xs = sorted(sub_locs[sub_locs["x"] < 403]["x"].unique())
        prev_node = lc_label
        prev_x = 66.0
        for x in left_xs:
            wp_node = f"WP_{int(x)}_{y_val:.1f}"
            if wp_node not in G:
                G.add_node(wp_node, x=float(x), y=float(y_val), node_type="waypoint")
            G.add_edge(prev_node, wp_node, weight=float(x - prev_x))
            prev_node = wp_node
            prev_x = x
        G.add_edge(prev_node, cc_label, weight=float(403.0 - prev_x))

        # Right Block: between CC (x=403) and RC (x=686) for aisles 8-17
        if rc_label and rc_label in G:
            right_xs = sorted(sub_locs[sub_locs["x"] > 403]["x"].unique())
            prev_node = cc_label
            prev_x = 403.0
            for x in right_xs:
                wp_node = f"WP_{int(x)}_{y_val:.1f}"
                if wp_node not in G:
                    G.add_node(wp_node, x=float(x), y=float(y_val), node_type="waypoint")
                G.add_edge(prev_node, wp_node, weight=float(x - prev_x))
                prev_node = wp_node
                prev_x = x
            G.add_edge(prev_node, rc_label, weight=float(686.0 - prev_x))

    # 5. Connect each Storage Location to its projected waypoint on the centreline
    for _, row in locs.iterrows():
        loc = str(row["location"]).strip()
        x = float(row["x"])
        ay = float(row["aisle_y"])
        z_val = int(row["z"]) if "z" in row and pd.notna(row["z"]) else 1

        if x == 403.0:
            k = y_levels.index(ay) + 1
            target_node = f"CC-{k:02d}"
        elif x == 66.0:
            k = y_levels.index(ay) + 1
            target_node = f"LC-{k:02d}"
        elif x == 686.0:
            k = y_levels.index(ay) + 1
            target_node = f"RC-{k:02d}"
        else:
            target_node = f"WP_{int(x)}_{ay:.1f}"

        G.add_node(
            loc,
            x=x,
            y=ay,
            z=z_val,
            original_y=float(row["y"]),
            node_type="location",
        )
        G.add_edge(loc, target_node, weight=0.0)

    # 6. Map known staging and corridor pick locations
    _map_special_locations(G, y_levels, locs)

    return G


def _map_special_locations(G: nx.Graph, y_levels: list[float], locs_df: pd.DataFrame) -> None:
    """Connect non-rack staging locations to nearest corridor/depot nodes."""
    # Sibling mapping by aisle and bay
    bay_map = locs_df.groupby(["aisle", "bay"])[["x", "aisle_y"]].first().to_dict(orient="index")

    special_mappings = {
        "RC-01": "CC-01",
        "RC-03": "CC-03",
        "RC-04": "CC-04",
        "RC-05": "CC-05",
        "EX-01": "CC-01",
        "EX-04": "CC-04",
        "EX-11": "CC-11",
        "ZN-COR": "CC-08",
        "C-014": "CC-03",
        "C-021": "CC-03",
        "C-022": "CC-03",
        "C-023": "CC-03",
        "C-024": "CC-03",
        "C-026": "CC-03",
        "C-061": "CC-03",
        "C-102": "CC-03",
        "I-25-20": "CC-09",
        "J-25-20": "CC-10",
    }

    for special_loc, target in special_mappings.items():
        if special_loc not in G and target in G:
            t_data = G.nodes[target]
            G.add_node(special_loc, x=t_data["x"], y=t_data["y"], z=1, node_type="staging")
            G.add_edge(special_loc, target, weight=0.0)

    # Additional standard bay patterns like "E-25-20"
    for loc_code in ["E-25-20", "G-25-10", "K-25-20", "K-26-20"]:
        if loc_code not in G:
            parts = loc_code.split("-")
            key = (parts[0], int(parts[1])) if len(parts) >= 2 and parts[1].isdigit() else None
            if key and key in bay_map:
                x = bay_map[key]["x"]
                ay = bay_map[key]["aisle_y"]
                wp = f"WP_{int(x)}_{ay:.1f}" if x not in [66, 403, 686] else f"CC-{y_levels.index(ay)+1:02d}"
                G.add_node(loc_code, x=x, y=ay, z=2, node_type="location")
                G.add_edge(loc_code, wp, weight=0.0)


# ---------------------------------------------------------------------------
# Precomputed Distance Cache & Lookups
# ---------------------------------------------------------------------------

_GRAPH: nx.Graph | None = None
_DIST_DF: pd.DataFrame | None = None
_DEPOT_DEFAULT = "CC-01"


def get_graph() -> nx.Graph:
    """Return the cached warehouse graph."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_warehouse_graph()
    return _GRAPH


def precompute_distance_matrix(
    locations: list[str] | None = None,
    depot: str = _DEPOT_DEFAULT,
    cache_path: str | Path | None = None,
    G: nx.Graph | None = None,
) -> pd.DataFrame:
    """Precompute all-pairs shortest distances using Dijkstra and cache to Parquet."""
    global _DIST_DF
    if G is None:
        G = get_graph()

    if cache_path is None:
        cache_path = _ROOT / "data" / "processed" / "distance_matrix.parquet"
    cache_path = Path(cache_path)

    if cache_path.exists() and locations is None:
        _DIST_DF = pd.read_parquet(cache_path)
        return _DIST_DF

    if locations is None:
        # Precompute for all location nodes + depot + support points
        loc_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") in ("location", "staging")]
        if depot not in loc_nodes and depot in G:
            loc_nodes.append(depot)
    else:
        loc_nodes = list(set(locations))
        if depot not in loc_nodes and depot in G:
            loc_nodes.append(depot)

    # Use waypoint-level Dijkstra to accelerate all-pairs computation
    # Map each location node to its entry waypoint on the aisle
    loc_to_wp: dict[str, str] = {}
    for node in loc_nodes:
        if node in G:
            neighbors = list(G.neighbors(node))
            # Pick neighbor with edge weight 0, or self if support point
            wp = next((nbr for nbr in neighbors if G[node][nbr]["weight"] == 0.0), node)
            loc_to_wp[node] = wp
        else:
            loc_to_wp[node] = depot

    unique_wps = list(set(loc_to_wp.values()))

    # Compute Dijkstra only from the unique waypoints (~500 sources)
    wp_dists: dict[str, dict[str, float]] = {}
    for wp in unique_wps:
        if wp in G:
            wp_dists[wp] = nx.single_source_dijkstra_path_length(G, wp, weight="weight")
        else:
            wp_dists[wp] = {}

    # Assemble dense distance matrix for all location nodes
    n = len(loc_nodes)
    matrix = np.zeros((n, n), dtype=np.float32)

    for i, loc_i in enumerate(loc_nodes):
        wp_i = loc_to_wp[loc_i]
        dists_i = wp_dists.get(wp_i, {})
        for j in range(i + 1, n):
            loc_j = loc_nodes[j]
            wp_j = loc_to_wp[loc_j]
            d = dists_i.get(wp_j, np.inf)
            matrix[i, j] = d
            matrix[j, i] = d

    dist_df = pd.DataFrame(matrix, index=loc_nodes, columns=loc_nodes)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    dist_df.to_parquet(cache_path)
    _DIST_DF = dist_df
    return dist_df


def shortest_distance(
    loc_a: str,
    loc_b: str,
    G: nx.Graph | None = None,
) -> float:
    """Compute the shortest walking distance between any two locations."""
    if loc_a == loc_b:
        return 0.0

    global _DIST_DF
    if _DIST_DF is not None and loc_a in _DIST_DF.index and loc_b in _DIST_DF.columns:
        return float(_DIST_DF.loc[loc_a, loc_b])

    # Check on-disk cache
    cache_path = _ROOT / "data" / "processed" / "distance_matrix.parquet"
    if cache_path.exists():
        _DIST_DF = pd.read_parquet(cache_path)
        if loc_a in _DIST_DF.index and loc_b in _DIST_DF.columns:
            return float(_DIST_DF.loc[loc_a, loc_b])

    if G is None:
        G = get_graph()

    if loc_a not in G or loc_b not in G:
        return np.inf

    return float(nx.shortest_path_length(G, loc_a, loc_b, weight="weight"))


# ---------------------------------------------------------------------------
# Route Length & Tour Heuristics
# ---------------------------------------------------------------------------

def route_length(
    locations: list[str],
    method: str = "s_shape",
    depot: str = _DEPOT_DEFAULT,
    G: nx.Graph | None = None,
    dist_matrix: pd.DataFrame | None = None,
) -> float:
    """Calculate the total walking distance starting at depot, visiting all locations, and returning.

    Parameters
    ----------
    locations : list[str]
        List of pick locations to visit.
    method : {"s_shape", "largest_gap", "nearest_neighbor"}
        Routing heuristic.
    depot : str
        Depot node identifier (default "CC-01").
    """
    if G is None:
        G = get_graph()

    # Filter to unique valid locations
    unique_locs = [loc for loc in dict.fromkeys(locations) if loc in G and loc != depot]

    if not unique_locs:
        return 0.0

    if len(unique_locs) == 1:
        d = shortest_distance(depot, unique_locs[0], G=G)
        return float(2.0 * d)

    if method == "nearest_neighbor":
        return _route_nearest_neighbor(unique_locs, depot, G=G, dist_matrix=dist_matrix)
    elif method in ("nearest_neighbor_2opt", "nn_2opt", "nn2opt"):
        return _route_nn_2opt(unique_locs, depot, G=G, dist_matrix=dist_matrix)
    elif method == "s_shape":
        return _route_s_shape(unique_locs, depot, G=G, dist_matrix=dist_matrix)
    elif method == "largest_gap":
        return _route_largest_gap(unique_locs, depot, G=G, dist_matrix=dist_matrix)
    else:
        raise ValueError(
            f"Unknown routing method: {method}. Choose from: 's_shape', 'largest_gap', 'nearest_neighbor', 'nn_2opt'"
        )


def _route_nn_2opt(
    locations: list[str],
    depot: str,
    G: nx.Graph,
    dist_matrix: pd.DataFrame | None = None,
    max_passes: int = 10,
) -> float:
    """Nearest Neighbor with 2-opt local search refinement from depot returning to depot."""
    nodes = [depot] + locations
    n = len(nodes)
    D = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            d = shortest_distance(nodes[i], nodes[j], G=G)
            D[i, j] = d
            D[j, i] = d

    from warehouse_ai.optimization.routing import tour_len, tour_nn_2opt
    tour = tour_nn_2opt(D, max_passes=max_passes)
    return tour_len(D, tour)


def _route_nearest_neighbor(
    locations: list[str],
    depot: str,
    G: nx.Graph,
    dist_matrix: pd.DataFrame | None = None,
) -> float:
    """Greedy Nearest Neighbor heuristic from depot returning to depot."""
    unvisited = set(locations)
    current = depot
    total_dist = 0.0

    while unvisited:
        next_loc = min(unvisited, key=lambda loc: shortest_distance(current, loc, G=G))
        total_dist += shortest_distance(current, next_loc, G=G)
        unvisited.remove(next_loc)
        current = next_loc

    total_dist += shortest_distance(current, depot, G=G)
    return float(total_dist)


def _route_s_shape(
    locations: list[str],
    depot: str,
    G: nx.Graph,
    dist_matrix: pd.DataFrame | None = None,
) -> float:
    """Serpentine / S-Shape heuristic traversing visited aisles in alternating directions."""
    # Group locations by aisle centreline y
    aisle_groups: dict[float, list[str]] = {}
    for loc in locations:
        node_data = G.nodes[loc]
        y_val = node_data.get("y", 0.0)
        aisle_groups.setdefault(y_val, []).append(loc)

    sorted_ys = sorted(aisle_groups.keys())

    # Try both forward and reverse sweep directions, keep the shorter tour
    best_dist = np.inf

    for y_order in [sorted_ys, sorted_ys[::-1]]:
        tour = [depot]
        ascending_x = True

        for y in y_order:
            group = aisle_groups[y]
            # Sort locations by x
            sorted_by_x = sorted(group, key=lambda loc_node: G.nodes[loc_node].get("x", 0.0), reverse=not ascending_x)
            tour.extend(sorted_by_x)
            ascending_x = not ascending_x

        tour.append(depot)

        # Compute tour length
        tour_dist = sum(shortest_distance(tour[i], tour[i + 1], G=G) for i in range(len(tour) - 1))
        if tour_dist < best_dist:
            best_dist = tour_dist

    return float(best_dist)


def _route_largest_gap(
    locations: list[str],
    depot: str,
    G: nx.Graph,
    dist_matrix: pd.DataFrame | None = None,
) -> float:
    """Largest Gap routing heuristic.

    For each aisle, calculates the largest gap between pick stops. If the internal
    gap exceeds the traversal detour, enters from both ends up to the gap.
    """
    aisle_groups: dict[float, list[str]] = {}
    for loc in locations:
        node_data = G.nodes[loc]
        y_val = node_data.get("y", 0.0)
        aisle_groups.setdefault(y_val, []).append(loc)

    sorted_ys = sorted(aisle_groups.keys())
    best_dist = np.inf

    for y_order in [sorted_ys, sorted_ys[::-1]]:
        tour = [depot]
        ascending = True

        for i, y in enumerate(y_order):
            group = aisle_groups[y]
            if len(group) == 1:
                tour.append(group[0])
                continue

            sorted_locs = sorted(group, key=lambda loc_node: G.nodes[loc_node].get("x", 0.0))
            xs = [G.nodes[loc_node].get("x", 0.0) for loc_node in sorted_locs]

            # Gaps between consecutive picks
            gaps = [xs[j + 1] - xs[j] for j in range(len(xs) - 1)]
            max_gap = max(gaps) if gaps else 0.0
            max_idx = gaps.index(max_gap) if gaps else 0

            # If internal gap is large, visit from left then right
            if max_gap > 100.0:  # significant internal gap
                left_sub = sorted_locs[: max_idx + 1]
                right_sub = sorted_locs[max_idx + 1 :]
                if ascending:
                    tour.extend(left_sub)
                    tour.extend(right_sub[::-1])
                else:
                    tour.extend(right_sub)
                    tour.extend(left_sub[::-1])
            else:
                tour.extend(sorted_locs if ascending else sorted_locs[::-1])

            ascending = not ascending

        tour.append(depot)
        tour_dist = sum(shortest_distance(tour[i], tour[i + 1], G=G) for i in range(len(tour) - 1))
        if tour_dist < best_dist:
            best_dist = tour_dist

    return float(best_dist)


# ---------------------------------------------------------------------------
# Wave Travel Distance & Vertical Level Time Penalty
# ---------------------------------------------------------------------------

def wave_travel(
    wave_id: int,
    method: str = "s_shape",
    depot: str = _DEPOT_DEFAULT,
    vertical_penalty_sec: float = 5.0,
    picks_df: pd.DataFrame | None = None,
    G: nx.Graph | None = None,
) -> dict[str, Any]:
    """Calculate walking travel distance and vertical retrieval time for a picking wave.

    Parameters
    ----------
    wave_id : int
        The identifier of the wave to calculate travel for.
    method : {"s_shape", "largest_gap", "nearest_neighbor"}
        Routing method.
    depot : str
        Depot node (default "CC-01").
    vertical_penalty_sec : float
        Additional retrieval time penalty in seconds per vertical tier above Level 1.
    """
    if G is None:
        G = get_graph()

    if picks_df is None:
        picks_path = _ROOT / "data" / "processed" / "picks_clean.parquet"
        picks_df = pd.read_parquet(picks_path)

    wave_picks = picks_df[picks_df["wave_number"] == wave_id]
    if wave_picks.empty:
        return {
            "wave_id": wave_id,
            "travel_dist": 0.0,
            "n_locations": 0,
            "n_picks": 0,
            "vertical_time_penalty_sec": 0.0,
        }

    loc_list = wave_picks["location"].dropna().tolist()
    dist = route_length(loc_list, method=method, depot=depot, G=G)

    # Vertical level penalty (for levels > 1)
    levels = wave_picks["level"].fillna(1).astype(int)
    vert_penalty = float(levels.apply(lambda lvl: max(0, lvl - 1) * vertical_penalty_sec).sum())

    return {
        "wave_id": wave_id,
        "travel_dist": round(dist, 2),
        "n_locations": wave_picks["location"].nunique(),
        "n_picks": len(wave_picks),
        "vertical_time_penalty_sec": round(vert_penalty, 2),
    }


def compute_all_wave_travel(
    method: str = "s_shape",
    depot: str = _DEPOT_DEFAULT,
    update_waves_table: bool = True,
) -> pd.DataFrame:
    """Compute travel distance for all waves and optionally update waves.parquet."""
    processed_dir = _ROOT / "data" / "processed"
    waves_path = processed_dir / "waves.parquet"
    picks_path = processed_dir / "picks_clean.parquet"

    waves_df = pd.read_parquet(waves_path)
    picks_df = pd.read_parquet(picks_path)
    G = get_graph()

    # Precompute / load distance matrix for maximum speed
    precompute_distance_matrix(depot=depot, G=G)

    print(f"Computing wave travel distances for {len(waves_df):,} waves using method='{method}'...")

    # Group pick locations by wave
    locs_by_wave = picks_df.groupby("wave_number")["location"].apply(list).to_dict()

    distances = []
    for wid in waves_df["wave_id"]:
        locs = locs_by_wave.get(wid, [])
        if locs:
            d = route_length(locs, method=method, depot=depot, G=G)
        else:
            d = 0.0
        distances.append(round(d, 2))

    waves_df["travel_dist"] = distances

    if update_waves_table:
        waves_df.to_parquet(waves_path, index=False)
        print(f"Updated {waves_path} with 'travel_dist' column.")

    return waves_df
