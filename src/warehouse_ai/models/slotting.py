"""Storage policy simulation, COI optimization, co-picking, and re-slotting recommendations.

Provides:
- Storage-policy simulator: replays historical waves across Random, Class-Based,
  Dedicated, and Hybrid policies, mapping each pick to the nearest available shelf location
  and computing tour distances (via travel.py) and labor hours (via labor.py).
- Optimised COI (Cube-per-Order Index) slotting: ranks SKU-sizes by pick frequency
  and co-picking affinity, and maps them to top-accessibility locations near the depot
  on Level 1-2, respecting 18 bin slots per location.
- Co-picking affinity analysis: identifies SKU-size pairs frequently picked in the same wave.
- Re-slotting recommendation API: ``recommend_reslotting(top_n=50)`` proposing high-ROI
  box relocations with expected weekly travel savings and operational move effort.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from warehouse_ai.config import load_config
from warehouse_ai.models.labor import get_labor_model
from warehouse_ai.models.travel import route_length, shortest_distance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class PolicySummary:
    policy_name: str
    total_waves: int
    total_picks: int
    total_travel_distance: float
    mean_wave_travel: float
    total_labor_hours: float
    mean_wave_time_sec: float
    travel_reduction_pct: float
    labor_reduction_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReslottingProposal:
    sku_size: str
    from_location: str
    to_location: str
    weekly_picks: float
    expected_travel_saved_per_week: float
    move_effort: str
    from_level: int
    to_level: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Co-Picking Affinity Analysis
# ---------------------------------------------------------------------------

def compute_co_picking_pairs(
    picks_df: pd.DataFrame,
    min_co_picks: int = 5,
) -> pd.DataFrame:
    """Compute co-occurrence frequencies of SKU-size pairs across waves.

    Parameters
    ----------
    picks_df : pd.DataFrame
        Pick records containing 'wave_number' and 'sku_size'.
    min_co_picks : int
        Minimum co-occurrence threshold to retain in output table.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ['sku_a', 'sku_b', 'co_pick_waves'].
    """
    waves_skus = picks_df.groupby("wave_number")["sku_size"].apply(
        lambda s: sorted(set(s.dropna()))
    ).values

    pair_counts = Counter()
    for skus in waves_skus:
        if len(skus) > 1:
            for u, v in itertools.combinations(skus, 2):
                pair_counts[(u, v)] += 1

    records = [
        {"sku_a": u, "sku_b": v, "co_pick_waves": count}
        for (u, v), count in pair_counts.items()
        if count >= min_co_picks
    ]

    out = pd.DataFrame(records)
    if len(out) > 0:
        out = out.sort_values("co_pick_waves", ascending=False).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# COI Slotting Layout Generation
# ---------------------------------------------------------------------------

def generate_coi_slotting(
    picks_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    slots_per_location: int = 18,
    depot: str = "CC-01",
    use_co_picking: bool = True,
    method: str = "greedy",
) -> pd.DataFrame:
    """Generate optimized Cube-per-Order Index (COI) layout.

    Ranks shelf locations by accessibility:
        score = dist_to_depot + 300.0 * (level - 1)
    Level 1 locations near the dispatch depot receive top priority.
    Ranks SKU-sizes by pick frequency, optionally clustering co-picked size runs,
    and assigns up to slots_per_location items per physical shelf location.

    Parameters
    ----------
    picks_df : pd.DataFrame
        Pick history table.
    locations_df : pd.DataFrame
        Location attributes table with columns ['location', 'level'].
    slots_per_location : int
        Number of bin slots per location (default: 18).
    depot : str
        Depot node identifier (default: 'CC-01').
    use_co_picking : bool
        Whether to cluster frequently co-picked pairs into adjacent slots.
    method : {"greedy", "linear_assignment"}
        Assignment algorithm.

    Returns
    -------
    pd.DataFrame
        Slotting table with ['location', 'slot_index', 'sku_size', 'policy'].
    """
    locs = locations_df.copy()

    # Precompute distances from depot
    dists_to_depot = [shortest_distance(depot, loc) for loc in locs["location"]]
    locs["dist_depot"] = dists_to_depot
    # Penalize vertical tiers: Level 1 penalty=0, Level 2 penalty=300, etc.
    locs["score"] = locs["dist_depot"] + (locs["level"] - 1).clip(lower=0) * 300.0
    sorted_locs = locs.sort_values("score")["location"].tolist()

    # Calculate SKU pick frequencies
    sku_freq = picks_df["sku_size"].dropna().value_counts()
    all_skus = sku_freq.index.tolist()

    if use_co_picking and len(all_skus) > 1:
        # Precompute co-picking pairs
        waves_skus = picks_df.groupby("wave_number")["sku_size"].apply(
            lambda s: sorted(set(s.dropna()))
        ).values
        co_pairs = Counter()
        for skus in waves_skus:
            if len(skus) > 1:
                for u, v in itertools.combinations(skus, 2):
                    co_pairs[(u, v)] += 1
                    co_pairs[(v, u)] += 1

        remaining = set(all_skus)
        ordered_skus = []
        while remaining:
            # Seed with most frequent remaining item
            seed = max(remaining, key=lambda s: sku_freq[s])
            ordered_skus.append(seed)
            remaining.remove(seed)

            # Greedily pull strong co-picked partners
            partners = sorted(
                [s for s in remaining if (seed, s) in co_pairs],
                key=lambda s: co_pairs[(seed, s)],
                reverse=True,
            )
            for p in partners[: slots_per_location - 1]:
                ordered_skus.append(p)
                remaining.remove(p)
    else:
        ordered_skus = all_skus

    # Build slot assignments
    rows = []
    if method == "linear_assignment" and len(ordered_skus) <= 300:
        # Exact linear assignment for smaller instances
        n_items = len(ordered_skus)
        # Flatten available slots
        slot_locs = []
        for loc in sorted_locs:
            for sl in range(1, slots_per_location + 1):
                slot_locs.append((loc, f"col_{sl}"))
                if len(slot_locs) >= n_items:
                    break
            if len(slot_locs) >= n_items:
                break

        cost_matrix = np.zeros((n_items, len(slot_locs)))
        loc_score_map = dict(zip(locs["location"], locs["score"]))
        for i, sku in enumerate(ordered_skus):
            freq = sku_freq.get(sku, 1)
            for j, (loc, _) in enumerate(slot_locs):
                cost_matrix[i, j] = -freq * (10000.0 - loc_score_map.get(loc, 5000.0))

        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        for i, j in zip(row_ind, col_ind):
            loc, sl = slot_locs[j]
            rows.append({
                "location": loc,
                "slot_index": sl,
                "sku_size": ordered_skus[i],
                "policy": "optimised_coi",
            })
    else:
        # Standard greedy COI block assignment
        loc_idx = 0
        slot_in_loc = 1
        for sku in ordered_skus:
            if loc_idx >= len(sorted_locs):
                break
            curr_loc = sorted_locs[loc_idx]
            rows.append({
                "location": curr_loc,
                "slot_index": f"col_{slot_in_loc}",
                "sku_size": sku,
                "policy": "optimised_coi",
            })
            slot_in_loc += 1
            if slot_in_loc > slots_per_location:
                slot_in_loc = 1
                loc_idx += 1

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Storage Policy Wave Simulation Engine
# ---------------------------------------------------------------------------

def simulate_storage_policy(
    policy_name: str,
    storage_df: pd.DataFrame,
    picks_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    depot: str = "CC-01",
    routing_method: str = "s_shape",
    max_waves: int | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Replay historical waves under a specific storage policy.

    For every picked unit, chooses the nearest location that holds that SKU-size
    under the policy (or reference fallback). Computes the picking tour distance
    and labor duration per wave.
    """
    logger.info("Simulating storage policy: %s ...", policy_name)
    lm = get_labor_model()

    # Pre-index locations
    loc_levels = dict(zip(locations_df["location"], locations_df["level"]))

    # Filter policy rows and map each SKU to nearest location to depot
    pol_stor = storage_df[storage_df["policy"] == policy_name].dropna(subset=["sku_size"]).copy()
    if len(pol_stor) == 0:
        raise ValueError(f"No storage records found for policy '{policy_name}'")

    # Precompute distance to depot for all locations
    pol_locs = pol_stor["location"].unique()
    depot_dists = {loc: shortest_distance(depot, loc) for loc in pol_locs}
    pol_stor["dist_depot"] = pol_stor["location"].map(depot_dists).fillna(9999.0)

    # Preferred location per SKU-size (lowest distance to depot)
    sku_to_loc = pol_stor.sort_values("dist_depot").groupby("sku_size")["location"].first().to_dict()

    # Fallback by reference
    if "reference" not in pol_stor.columns:
        pol_stor["reference"] = pol_stor["sku_size"].astype(str).str.split("|").str[0]
    ref_to_loc = pol_stor.sort_values("dist_depot").groupby("reference")["location"].first().to_dict()

    # Default fallback location if item not found anywhere in policy
    default_loc = pol_stor.sort_values("dist_depot")["location"].iloc[0]

    # Group picks by wave
    grouped = picks_df.groupby("wave_number")
    wave_ids = list(grouped.groups.keys())
    if max_waves is not None:
        wave_ids = wave_ids[:max_waves]

    wave_results = []
    total_travel = 0.0
    total_labor_sec = 0.0
    total_picks_count = 0

    for w_id in wave_ids:
        w_df = grouped.get_group(w_id)
        n_units = len(w_df)
        total_picks_count += n_units

        # Map each picked unit to its location under this policy
        chosen_locs = []
        for _, row in w_df.iterrows():
            sku = row.get("sku_size")
            ref = row.get("reference")
            if sku in sku_to_loc:
                loc = sku_to_loc[sku]
            elif ref in ref_to_loc:
                loc = ref_to_loc[ref]
            elif pd.notna(row.get("location")):
                loc = row["location"]
            else:
                loc = default_loc
            chosen_locs.append(loc)

        distinct_locs = list(set(chosen_locs))

        # Calculate tour route length
        tour_dist = route_length(distinct_locs, method=routing_method, depot=depot)
        total_travel += tour_dist

        # Calculate vertical level penalty
        z_excess = sum(max(0, loc_levels.get(loc, 1) - 1) for loc in distinct_locs)
        wave_data = {
            "travel_dist": tour_dist,
            "n_distinct_locations": len(distinct_locs),
            "n_units": n_units,
            "vertical_penalty": z_excess * 5.0,
        }
        duration_s = lm.wave_time(wave_data, dist_is_meters=False)
        total_labor_sec += duration_s

        wave_results.append({
            "wave_number": w_id,
            "policy": policy_name,
            "units": n_units,
            "distinct_locations": len(distinct_locs),
            "travel_distance": round(tour_dist, 1),
            "duration_seconds": round(duration_s, 1),
        })

    waves_df = pd.DataFrame(wave_results)
    n_waves = len(waves_df)

    summary = {
        "policy_name": policy_name,
        "total_waves": n_waves,
        "total_picks": total_picks_count,
        "total_travel_distance": round(total_travel, 1),
        "mean_wave_travel": round(total_travel / max(1, n_waves), 1),
        "total_labor_hours": round(total_labor_sec / 3600.0, 2),
        "mean_wave_time_sec": round(total_labor_sec / max(1, n_waves), 1),
    }

    return summary, waves_df


def compare_all_policies(
    picks_df: pd.DataFrame | None = None,
    storage_df: pd.DataFrame | None = None,
    locations_df: pd.DataFrame | None = None,
    depot: str = "CC-01",
    routing_method: str = "s_shape",
    max_waves: int | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Simulate and compare all 4 empirical policies + Optimised COI.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, pd.DataFrame]]
        (summary_table, per_policy_wave_details)
    """
    cfg = load_config()
    proc_dir = Path(cfg.paths.data_processed)

    if picks_df is None:
        picks_df = pd.read_parquet(proc_dir / "picks_clean.parquet")
    if storage_df is None:
        storage_df = pd.read_parquet(proc_dir / "storage_long.parquet")
    if locations_df is None:
        locations_df = pd.read_parquet(proc_dir / "locations.parquet")

    # 1. Generate Optimised COI layout
    coi_df = generate_coi_slotting(
        picks_df=picks_df,
        locations_df=locations_df,
        slots_per_location=cfg.warehouse.slots_per_location,
        depot=depot,
        use_co_picking=True,
    )

    combined_storage = pd.concat([storage_df, coi_df], ignore_index=True)

    policies = ["random", "class_based", "dedicated", "hybrid", "optimised_coi"]
    summaries = []
    details = {}

    for pol in policies:
        sm, w_df = simulate_storage_policy(
            policy_name=pol,
            storage_df=combined_storage,
            picks_df=picks_df,
            locations_df=locations_df,
            depot=depot,
            routing_method=routing_method,
            max_waves=max_waves,
        )
        summaries.append(sm)
        details[pol] = w_df

    sum_df = pd.DataFrame(summaries)

    # Compute percentage improvements vs random baseline
    rand_row = sum_df[sum_df["policy_name"] == "random"].iloc[0]
    base_dist = rand_row["total_travel_distance"]
    base_hours = rand_row["total_labor_hours"]

    sum_df["travel_reduction_pct"] = np.round((1.0 - sum_df["total_travel_distance"] / base_dist) * 100.0, 1)
    sum_df["labor_reduction_pct"] = np.round((1.0 - sum_df["total_labor_hours"] / base_hours) * 100.0, 1)

    return sum_df, details


# ---------------------------------------------------------------------------
# Re-Slotting Recommendation API
# ---------------------------------------------------------------------------

def recommend_reslotting(
    baseline_policy: str = "random",
    top_n: int = 50,
    picks_df: pd.DataFrame | None = None,
    storage_df: pd.DataFrame | None = None,
    locations_df: pd.DataFrame | None = None,
    depot: str = "CC-01",
) -> list[dict[str, Any]]:
    """Generate high-ROI proposed SKU relocations to forward pick-face slots.

    Parameters
    ----------
    baseline_policy : str
        Source policy representing current storage arrangement (default: 'random').
    top_n : int
        Number of top relocation proposals to return (default: 50).
    picks_df : pd.DataFrame | None
        Picks history table.
    storage_df : pd.DataFrame | None
        Current storage layout table.
    locations_df : pd.DataFrame | None
        Location attributes table.
    depot : str
        Depot node identifier.

    Returns
    -------
    list[dict[str, Any]]
        List of recommended move proposals with expected weekly travel savings and effort.
    """
    cfg = load_config()
    proc_dir = Path(cfg.paths.data_processed)

    if picks_df is None:
        picks_df = pd.read_parquet(proc_dir / "picks_clean.parquet")
    if storage_df is None:
        storage_df = pd.read_parquet(proc_dir / "storage_long.parquet")
    if locations_df is None:
        locations_df = pd.read_parquet(proc_dir / "locations.parquet")

    # Pre-index locations metadata
    locs_meta = locations_df.set_index("location").to_dict(orient="index")
    depot_dists = {loc: shortest_distance(depot, loc) for loc in locations_df["location"]}

    # Baseline mapping: current location under baseline policy
    base_stor = storage_df[storage_df["policy"] == baseline_policy].dropna(subset=["sku_size"])
    from_map = base_stor.groupby("sku_size")["location"].first().to_dict()

    # Target optimized layout
    coi_df = generate_coi_slotting(
        picks_df=picks_df,
        locations_df=locations_df,
        slots_per_location=cfg.warehouse.slots_per_location,
        depot=depot,
        use_co_picking=True,
    )
    to_map = coi_df.groupby("sku_size")["location"].first().to_dict()

    # Pick counts and time span
    sku_counts = picks_df["sku_size"].dropna().value_counts()
    n_weeks = 41.0  # Approx 41 operating weeks

    moves = []
    for sku, count in sku_counts.items():
        from_loc = from_map.get(sku)
        to_loc = to_map.get(sku)

        if not from_loc or not to_loc or from_loc == to_loc:
            continue

        w_picks = max(0.1, count / n_weeks)
        d_from = depot_dists.get(from_loc, 1000.0)
        d_to = depot_dists.get(to_loc, 500.0)

        # Round-trip travel saved per pick
        round_trip_saved = max(0.0, (d_from - d_to) * 2.0)
        weekly_saved = round(w_picks * round_trip_saved, 1)

        from_lvl = locs_meta.get(from_loc, {}).get("level", 1)
        to_lvl = locs_meta.get(to_loc, {}).get("level", 1)
        from_aisle = locs_meta.get(from_loc, {}).get("aisle", "")
        to_aisle = locs_meta.get(to_loc, {}).get("aisle", "")

        # Operational move effort
        if from_lvl > 2 or to_lvl > 2:
            effort = "High"  # Requires forklift / ladder access to upper reserve tiers
        elif from_aisle == to_aisle:
            effort = "Low"  # Hand carry within same aisle
        else:
            effort = "Medium"  # Trolley transfer across aisles

        moves.append(ReslottingProposal(
            sku_size=sku,
            from_location=from_loc,
            to_location=to_loc,
            weekly_picks=round(w_picks, 1),
            expected_travel_saved_per_week=weekly_saved,
            move_effort=effort,
            from_level=int(from_lvl),
            to_level=int(to_lvl),
        ).to_dict())

    # Sort proposals by expected travel saved descending
    moves = sorted(moves, key=lambda m: m["expected_travel_saved_per_week"], reverse=True)
    return moves[:top_n]

