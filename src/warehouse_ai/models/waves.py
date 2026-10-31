"""Wave planning, batching, and operator assignment module.

Provides:
- Baseline: replays historical waves and their travel distances exactly as recorded.
- Batching algorithms (FCFS, Seed+Savings, Aisle-Cluster) for grouping open orders
  into pick waves within trolley-capacity and order-count constraints.
- Workload-balanced operator assignment via a Longest-Processing-Time (LPT) greedy
  schedule so no operator exceeds a configured shift length.
- Evaluation against historical days (total travel, wave count, estimated hours).
- Public API: plan_waves(orders_df, n_operators) -> list[WavePlan].

Design notes
------------
- Orders do not carry location data; the module resolves pick locations by joining
  order SKU-sizes against a storage policy (default: 'random', i.e. AS-IS).
- Route lengths are computed using route_length() from travel.py (S-Shape heuristic).
- Estimated wave times come from wave_time() in labor.py.
- All stochastic tie-breaking uses seed 42 for reproducibility.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from warehouse_ai.config import load_config
from warehouse_ai.models.labor import get_labor_model, wave_time
from warehouse_ai.models.travel import route_length

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WavePlan:
    """One planned pick wave."""

    wave_index: int
    order_numbers: list[int]
    sku_lines: list[dict]          # [{sku_size, qty, location}, ...]
    locations: list[str]
    n_orders: int
    n_lines: int
    n_units: int
    n_distinct_locations: int
    n_aisles: int
    estimated_travel: float        # raw coordinate units (not metres)
    estimated_time_s: float
    operator: str = ""
    algorithm: str = "fcfs"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("sku_lines")         # verbose; omit from summary output
        return d


@dataclass
class DayEvaluation:
    """Per-day comparison of a wave plan vs the historical record."""

    date: str
    algorithm: str
    n_waves_planned: int
    n_waves_historical: int
    total_travel_planned: float
    total_travel_historical: float
    total_hours_planned: float
    total_hours_historical: float
    travel_delta_pct: float
    hours_delta_pct: float
    n_operators_used: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_defaults(
    picks_df: pd.DataFrame | None,
    storage_df: pd.DataFrame | None,
    locations_df: pd.DataFrame | None,
    waves_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load processed tables from disk when not supplied by caller."""
    cfg = load_config()
    proc = Path(cfg.paths.data_processed)
    if picks_df is None:
        picks_df = pd.read_parquet(proc / "picks_clean.parquet")
    if storage_df is None:
        storage_df = pd.read_parquet(proc / "storage_long.parquet")
    if locations_df is None:
        locations_df = pd.read_parquet(proc / "locations.parquet")
    if waves_df is None:
        waves_df = pd.read_parquet(proc / "waves.parquet")
    return picks_df, storage_df, locations_df, waves_df


def _build_order_location_map(
    orders_df: pd.DataFrame,
    storage_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    policy: str = "random",
) -> pd.DataFrame:
    """Join orders → SKU-sizes → storage locations for a given policy.

    Returns a DataFrame with columns:
        order_number, sku_size, qty, location, aisle, x, y, level
    Rows where the SKU-size has no storage slot under this policy are dropped
    with a warning (typically ≤10% of lines for the random policy).
    """
    stor = storage_df[storage_df["policy"] == policy][["sku_size", "location"]].drop_duplicates("sku_size")
    loc_meta = locations_df[["location", "aisle", "x", "y", "level"]].drop_duplicates("location")

    mapped = (
        orders_df[["order_number", "sku_size", "qty"]]
        .merge(stor, on="sku_size", how="left")
        .merge(loc_meta, on="location", how="left")
    )

    missing = mapped["location"].isna().sum()
    if missing:
        logger.warning(
            "%.1f%% of order lines (%d) have no storage slot under policy '%s' — dropped.",
            100 * missing / max(1, len(mapped)), missing, policy,
        )
        mapped = mapped.dropna(subset=["location"])

    return mapped.reset_index(drop=True)


def _wave_stats(
    order_nums: list[int],
    mapped: pd.DataFrame,
) -> dict[str, Any]:
    """Compute pick statistics for a set of order numbers using the location map."""
    lines = mapped[mapped["order_number"].isin(order_nums)]
    locations = lines["location"].dropna().tolist()
    unique_locs = list(dict.fromkeys(locations))   # preserve first occurrence, deduplicate
    aisles = lines["aisle"].dropna().unique().tolist()
    n_distinct_locs = len(unique_locs)
    n_aisles_val = len(aisles)

    if unique_locs:
        est_travel = route_length(unique_locs, method="s_shape")
    else:
        est_travel = 0.0

    wave_dict = {
        "n_distinct_locations": n_distinct_locs,
        "n_units": int(lines["qty"].sum()),
        "travel_dist": est_travel,
        "n_aisles": n_aisles_val,
    }
    est_time = wave_time(wave_dict)

    sku_lines = (
        lines[["sku_size", "qty", "location"]]
        .dropna(subset=["location"])
        .to_dict(orient="records")
    )

    return {
        "order_numbers": order_nums,
        "sku_lines": sku_lines,
        "locations": unique_locs,
        "n_orders": len(order_nums),
        "n_lines": len(lines),
        "n_units": int(lines["qty"].sum()),
        "n_distinct_locations": n_distinct_locs,
        "n_aisles": n_aisles_val,
        "estimated_travel": est_travel,
        "estimated_time_s": est_time,
    }


def _assign_operators(
    wave_plans: list[WavePlan],
    n_operators: int,
    shift_hours: float,
) -> list[WavePlan]:
    """Assign waves to operators using a Longest-Processing-Time (LPT) greedy schedule.

    Waves are sorted longest-first, then each is appended to the operator with
    the currently lowest total workload (classic LPT load balancing).  Operator
    names follow the pattern Op_1 … Op_N.  No wave exceeds a single shift; a
    warning is logged if it would.
    """
    # Sort by estimated time descending (LPT)
    waves_sorted = sorted(wave_plans, key=lambda w: w.estimated_time_s, reverse=True)
    loads = np.zeros(n_operators)   # cumulative seconds per operator
    op_names = [f"Op_{i+1}" for i in range(n_operators)]

    for wp in waves_sorted:
        # Pick the operator with the minimum current load
        idx = int(np.argmin(loads))
        cumulative = loads[idx] + wp.estimated_time_s
        if cumulative > shift_hours * 3600:
            logger.warning(
                "Operator %s would exceed shift capacity (%.1f h); wave %d kept anyway.",
                op_names[idx], shift_hours, wp.wave_index,
            )
        wp.operator = op_names[idx]
        loads[idx] = cumulative

    # Restore original wave index order before returning
    return sorted(waves_sorted, key=lambda w: w.wave_index)


# ---------------------------------------------------------------------------
# 1. Baseline: replay historical waves
# ---------------------------------------------------------------------------


def replay_historical_waves(
    waves_df: pd.DataFrame | None = None,
    picks_df: pd.DataFrame | None = None,
    date: str | None = None,
) -> list[WavePlan]:
    """Reconstruct WavePlan objects from the historical record.

    Parameters
    ----------
    waves_df : pd.DataFrame | None
        waves.parquet (loaded from disk if None).
    picks_df : pd.DataFrame | None
        picks_clean.parquet (loaded from disk if None).
    date : str | None
        If given, filter to a single calendar date (e.g. '2023-01-05').

    Returns
    -------
    list[WavePlan]
        One WavePlan per historical wave, with estimated_travel = recorded travel_dist
        and estimated_time_s from the labor model.
    """
    picks_df, _, _, waves_df = _load_defaults(picks_df, None, None, waves_df)

    if date is not None:
        waves_df = waves_df[waves_df["date"].astype(str) == str(date)]

    plans: list[WavePlan] = []
    for idx, row in enumerate(waves_df.itertuples(index=False)):
        wave_id = row.wave_id
        wave_picks = picks_df[picks_df["wave_number"] == wave_id]
        unique_locs = list(dict.fromkeys(wave_picks["location"].dropna().tolist()))

        n_distinct_locs = getattr(row, "n_distinct_locations", len(unique_locs))
        n_aisles_val = getattr(row, "n_aisles", wave_picks["aisle"].nunique() if "aisle" in wave_picks.columns else 0)
        travel = float(row.travel_dist) if not pd.isna(row.travel_dist) else 0.0

        wave_dict = {
            "n_distinct_locations": n_distinct_locs or len(unique_locs),
            "n_units": row.n_units,
            "travel_dist": travel,
            "n_aisles": n_aisles_val or 0,
        }
        est_time = wave_time(wave_dict)

        plans.append(WavePlan(
            wave_index=idx,
            order_numbers=[],          # orders not linked to picks in processed tables
            sku_lines=[],
            locations=unique_locs,
            n_orders=int(row.n_orders),
            n_lines=int(row.n_lines),
            n_units=int(row.n_units),
            n_distinct_locations=int(n_distinct_locs or len(unique_locs)),
            n_aisles=int(n_aisles_val or 0),
            estimated_travel=travel,
            estimated_time_s=est_time,
            operator=str(row.operator),
            algorithm="historical",
        ))

    return plans


# ---------------------------------------------------------------------------
# 2. Batching algorithms
# ---------------------------------------------------------------------------


def batch_fcfs(
    orders_df: pd.DataFrame,
    max_units: int,
    max_orders: int,
    mapped: pd.DataFrame,
) -> list[list[int]]:
    """First-Come-First-Served batching.

    Orders are sorted by created_at (then order_number as tie-breaker) and
    greedily packed into waves respecting trolley capacity (max_units) and
    max_orders per wave.

    Returns
    -------
    list[list[int]]
        Each inner list is a batch of order_numbers for one wave.
    """
    # Aggregate qty per order
    order_qty = (
        orders_df.groupby("order_number")["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "total_qty"})
    )
    order_info = (
        orders_df[["order_number", "created_at"]]
        .drop_duplicates("order_number")
        .merge(order_qty, on="order_number")
        .sort_values(["created_at", "order_number"])
    )

    batches: list[list[int]] = []
    current_batch: list[int] = []
    current_units = 0

    for row in order_info.itertuples(index=False):
        order_units = int(row.total_qty)
        if order_units == 0:
            continue
        # If adding this order would exceed capacity, flush current batch
        if current_batch and (current_units + order_units > max_units or len(current_batch) >= max_orders):
            batches.append(current_batch)
            current_batch = []
            current_units = 0
        # Handle oversized single orders: put them alone
        current_batch.append(row.order_number)
        current_units += order_units

    if current_batch:
        batches.append(current_batch)

    return batches


def batch_seed_savings(
    orders_df: pd.DataFrame,
    max_units: int,
    max_orders: int,
    mapped: pd.DataFrame,
    locations_df: pd.DataFrame,
    rng: np.random.Generator | None = None,
) -> list[list[int]]:
    """Seed + Savings batching heuristic.

    For each wave:
    1. **Seed selection**: pick the unassigned order whose SKU locations span the
       most (or farthest) aisles — maximising aisle breadth so the wave fills the
       warehouse footprint efficiently.  Ties broken randomly.
    2. **Savings extension**: greedily add the unassigned order that minimises the
       *marginal increase* in estimated route length (re-computed with route_length
       on the combined location set), until max_units or max_orders is reached.

    This clusters orders with geographically similar pick lists, reducing redundant
    aisle traversals vs FCFS.

    Returns
    -------
    list[list[int]]
        Each inner list is a batch of order_numbers for one wave.
    """
    if rng is None:
        rng = np.random.default_rng(42)

    # Pre-compute per-order: total qty, set of locations, farthest aisle y-coord
    order_qty = orders_df.groupby("order_number")["qty"].sum().to_dict()
    loc_meta = (
        mapped[["order_number", "location", "aisle", "y"]]
        .dropna(subset=["location"])
        .copy()
    )

    order_locs: dict[int, list[str]] = (
        loc_meta.groupby("order_number")["location"]
        .apply(lambda s: list(dict.fromkeys(s.tolist())))
        .to_dict()
    )
    order_n_aisles: dict[int, int] = (
        loc_meta.groupby("order_number")["aisle"].nunique().to_dict()
    )

    remaining = set(order_qty.keys())
    batches: list[list[int]] = []

    while remaining:
        # 1. Seed: order with the most aisles (farthest single-order footprint)
        max_aisles = max(order_n_aisles.get(o, 0) for o in remaining)
        seed_candidates = [o for o in remaining if order_n_aisles.get(o, 0) == max_aisles]
        seed = int(rng.choice(seed_candidates))

        current_batch = [seed]
        current_units = int(order_qty.get(seed, 0))
        current_locs = set(order_locs.get(seed, []))
        remaining.discard(seed)

        # 2. Savings: greedily add orders that minimise marginal travel increase
        while remaining and len(current_batch) < max_orders:
            # Evaluate each candidate
            best_order: int | None = None
            best_marginal = float("inf")

            # For speed, limit candidates to those whose qty fits
            candidates = [
                o for o in remaining
                if current_units + int(order_qty.get(o, 0)) <= max_units
            ]
            if not candidates:
                break

            # For very large candidate sets, sample to keep runtime manageable
            if len(candidates) > 50:
                candidates = list(rng.choice(candidates, size=50, replace=False))  # type: ignore[arg-type]

            for o in candidates:
                new_locs = current_locs | set(order_locs.get(o, []))
                if not new_locs:
                    marginal = 0.0
                else:
                    new_travel = route_length(list(new_locs), method="s_shape")
                    old_travel = route_length(list(current_locs), method="s_shape") if current_locs else 0.0
                    marginal = new_travel - old_travel

                if marginal < best_marginal:
                    best_marginal = marginal
                    best_order = o

            if best_order is None:
                break

            current_batch.append(best_order)
            current_units += int(order_qty.get(best_order, 0))
            current_locs |= set(order_locs.get(best_order, []))
            remaining.discard(best_order)

        batches.append(current_batch)

    return batches


def batch_aisle_cluster(
    orders_df: pd.DataFrame,
    max_units: int,
    max_orders: int,
    mapped: pd.DataFrame,
    n_clusters: int | None = None,
    rng: np.random.Generator | None = None,
) -> list[list[int]]:
    """Aisle-vector clustering batching.

    Each order is represented by a binary aisle-visit vector (1 if any SKU is
    in that aisle, 0 otherwise).  Orders are grouped by cosine similarity of
    their aisle vectors using agglomerative clustering.  Each cluster is then
    packed into waves of ≤ max_units units using FCFS within the cluster.

    Falls back to FCFS if sklearn is unavailable or fewer orders than clusters.

    Parameters
    ----------
    n_clusters : int | None
        Target cluster count; defaults to ceil(total_units / max_units).
    """
    if rng is None:
        rng = np.random.default_rng(42)

    try:
        from sklearn.cluster import AgglomerativeClustering  # type: ignore
    except ImportError:
        logger.warning("sklearn not available; falling back to FCFS for aisle_cluster.")
        return batch_fcfs(orders_df, max_units, max_orders, mapped)

    # Build aisle-visit matrix
    all_aisles = sorted(mapped["aisle"].dropna().unique())
    aisle_idx = {a: i for i, a in enumerate(all_aisles)}
    n_aisles_total = len(all_aisles)

    order_ids = sorted(orders_df["order_number"].unique())
    order_qty = orders_df.groupby("order_number")["qty"].sum().to_dict()

    if len(order_ids) < 2:
        return batch_fcfs(orders_df, max_units, max_orders, mapped)

    mat = np.zeros((len(order_ids), n_aisles_total), dtype=np.float32)
    ord_idx = {o: i for i, o in enumerate(order_ids)}

    for _, row in mapped[["order_number", "aisle"]].dropna().iterrows():
        oi = ord_idx.get(row["order_number"])
        ai = aisle_idx.get(row["aisle"])
        if oi is not None and ai is not None:
            mat[oi, ai] = 1.0

    # Determine cluster count
    total_units = sum(order_qty.get(o, 0) for o in order_ids)
    if n_clusters is None:
        n_clusters = max(2, int(np.ceil(total_units / max_units)))
    n_clusters = min(n_clusters, len(order_ids))

    try:
        clustering = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine", linkage="average")
        labels = clustering.fit_predict(mat)
    except Exception as exc:
        logger.warning("Agglomerative clustering failed (%s); falling back to FCFS.", exc)
        return batch_fcfs(orders_df, max_units, max_orders, mapped)

    # Within each cluster, pack orders into waves via FCFS
    batches: list[list[int]] = []
    for cluster_id in range(n_clusters):
        cluster_orders = [order_ids[i] for i, lbl in enumerate(labels) if lbl == cluster_id]
        if not cluster_orders:
            continue

        cluster_order_df = orders_df[orders_df["order_number"].isin(cluster_orders)]
        cluster_mapped = mapped[mapped["order_number"].isin(cluster_orders)]
        cluster_batches = batch_fcfs(cluster_order_df, max_units, max_orders, cluster_mapped)
        batches.extend(cluster_batches)

    return batches


# ---------------------------------------------------------------------------
# 3. Main batching dispatcher
# ---------------------------------------------------------------------------


def _batches_to_wave_plans(
    batches: list[list[int]],
    mapped: pd.DataFrame,
    algorithm: str,
) -> list[WavePlan]:
    """Convert a list of order-number batches into WavePlan objects."""
    plans: list[WavePlan] = []
    for idx, order_nums in enumerate(batches):
        if not order_nums:
            continue
        stats = _wave_stats(order_nums, mapped)
        plans.append(WavePlan(
            wave_index=idx,
            algorithm=algorithm,
            **stats,
        ))
    return plans


# ---------------------------------------------------------------------------
# 4. Public API
# ---------------------------------------------------------------------------


def plan_waves(
    orders_df: pd.DataFrame,
    n_operators: int,
    algorithm: str = "fcfs",
    storage_policy: str = "random",
    max_units: int | None = None,
    max_orders: int | None = None,
    storage_df: pd.DataFrame | None = None,
    locations_df: pd.DataFrame | None = None,
    rng: np.random.Generator | None = None,
) -> list[WavePlan]:
    """Plan pick waves for a set of open orders.

    Parameters
    ----------
    orders_df : pd.DataFrame
        Open order lines with columns: order_number, sku_size, qty, created_at.
    n_operators : int
        Number of available pickers for the day.
    algorithm : {'fcfs', 'seed_savings', 'aisle_cluster'}
        Wave-batching algorithm.
    storage_policy : str
        Storage layout to use when resolving SKU → location mappings.
    max_units : int | None
        Maximum units per trolley (defaults to warehouse.trolley_capacity from config).
    max_orders : int | None
        Maximum orders per wave (defaults to 24 matching historical practice).
    storage_df : pd.DataFrame | None
        storage_long.parquet (loaded from disk if None).
    locations_df : pd.DataFrame | None
        locations.parquet (loaded from disk if None).
    rng : np.random.Generator | None
        Random generator (seed 42 default) for stochastic algorithms.

    Returns
    -------
    list[WavePlan]
        Waves in execution order with operator assignments and estimated times.
    """
    cfg = load_config()
    if max_units is None:
        max_units = int(cfg.warehouse.trolley_capacity)
    if max_orders is None:
        max_orders = 24   # matches historical max observed
    if rng is None:
        rng = np.random.default_rng(cfg.random_seed)

    _, storage_df, locations_df, _ = _load_defaults(None, storage_df, locations_df, None)

    mapped = _build_order_location_map(orders_df, storage_df, locations_df, policy=storage_policy)

    if algorithm == "fcfs":
        batches = batch_fcfs(orders_df, max_units, max_orders, mapped)
    elif algorithm == "seed_savings":
        batches = batch_seed_savings(orders_df, max_units, max_orders, mapped, locations_df, rng=rng)
    elif algorithm == "aisle_cluster":
        batches = batch_aisle_cluster(orders_df, max_units, max_orders, mapped, rng=rng)
    else:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Choose from: fcfs, seed_savings, aisle_cluster.")

    wave_plans = _batches_to_wave_plans(batches, mapped, algorithm)

    shift_hours = float(cfg.staffing.shift_hours)
    wave_plans = _assign_operators(wave_plans, n_operators, shift_hours)

    logger.info(
        "plan_waves(%s): %d orders → %d waves, %d operators.",
        algorithm, orders_df["order_number"].nunique(), len(wave_plans), n_operators,
    )
    return wave_plans


# ---------------------------------------------------------------------------
# 5. Historical evaluation
# ---------------------------------------------------------------------------


def evaluate_on_historical_days(
    n_sample_days: int = 10,
    algorithms: list[str] | None = None,
    n_operators: int = 5,
    max_units: int | None = None,
    max_orders: int | None = None,
    orders_df: pd.DataFrame | None = None,
    picks_df: pd.DataFrame | None = None,
    storage_df: pd.DataFrame | None = None,
    locations_df: pd.DataFrame | None = None,
    waves_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Evaluate batching algorithms vs historical waves on a sample of days.

    Selects the ``n_sample_days`` busiest days by order volume, re-batches their
    orders using each algorithm, and compares total travel, wave count, and
    estimated labor hours against the historical record.

    Returns
    -------
    pd.DataFrame
        Rows = (date × algorithm); columns = evaluation metrics.
    """
    if algorithms is None:
        algorithms = ["fcfs", "seed_savings", "aisle_cluster"]

    cfg = load_config()
    if max_units is None:
        max_units = int(cfg.warehouse.trolley_capacity)
    if max_orders is None:
        max_orders = 24

    picks_df, storage_df, locations_df, waves_df = _load_defaults(
        picks_df, storage_df, locations_df, waves_df
    )
    if orders_df is None:
        proc = Path(cfg.paths.data_processed)
        orders_df = pd.read_parquet(proc / "orders_clean.parquet")

    labor = get_labor_model()  # noqa: F841  kept for potential future use

    # Pick busiest days
    daily_units = (
        orders_df.groupby(orders_df["date"].astype(str))["qty"]
        .sum()
        .sort_values(ascending=False)
    )
    sample_dates = daily_units.head(n_sample_days).index.tolist()

    results: list[dict] = []

    for date_str in sample_dates:
        # Historical baseline for this day
        hist_waves = waves_df[waves_df["date"].astype(str) == date_str]
        hist_travel = float(hist_waves["travel_dist"].sum())
        hist_wave_count = len(hist_waves)
        hist_hours = float(
            hist_waves.apply(
                lambda r: wave_time({
                    "n_distinct_locations": r["n_distinct_locations"],
                    "n_units": r["n_units"],
                    "travel_dist": r["travel_dist"],
                    "n_aisles": r["n_aisles"],
                }),
                axis=1,
            ).sum()
        ) / 3600.0

        day_orders = orders_df[orders_df["date"].astype(str) == date_str].copy()
        if len(day_orders) == 0:
            continue

        for algo in algorithms:
            rng = np.random.default_rng(42)
            try:
                wave_plans = plan_waves(
                    orders_df=day_orders,
                    n_operators=n_operators,
                    algorithm=algo,
                    max_units=max_units,
                    max_orders=max_orders,
                    storage_df=storage_df,
                    locations_df=locations_df,
                    rng=rng,
                )
            except Exception as exc:
                logger.warning("Algorithm %s failed on %s: %s", algo, date_str, exc)
                continue

            plan_travel = sum(w.estimated_travel for w in wave_plans)
            plan_hours = sum(w.estimated_time_s for w in wave_plans) / 3600.0
            n_ops = len({w.operator for w in wave_plans if w.operator})

            travel_delta = (plan_travel - hist_travel) / max(1.0, hist_travel) * 100.0
            hours_delta = (plan_hours - hist_hours) / max(0.01, hist_hours) * 100.0

            results.append(DayEvaluation(
                date=date_str,
                algorithm=algo,
                n_waves_planned=len(wave_plans),
                n_waves_historical=hist_wave_count,
                total_travel_planned=round(plan_travel, 1),
                total_travel_historical=round(hist_travel, 1),
                total_hours_planned=round(plan_hours, 3),
                total_hours_historical=round(hist_hours, 3),
                travel_delta_pct=round(travel_delta, 1),
                hours_delta_pct=round(hours_delta, 1),
                n_operators_used=n_ops,
            ).__dict__)

    return pd.DataFrame(results)
