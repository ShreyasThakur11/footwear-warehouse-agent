"""Pick wave route optimization, TSP heuristics, and scenario benchmarking.

Implements:
1. Traveling Salesperson Problem (TSP) solvers:
   - Nearest-Neighbor with 2-opt local search refinement (tour_nn_2opt)
   - Serpentine / S-shape routing heuristic (tour_serpentine)
2. Fast scenario evaluator:
   - Evaluates thousands of picking waves across storage policies and routing heuristics
   - Stop-set caching for sub-second execution
   - Standard engineering time model (walking, stopping, picking, setup)
3. Statistical benchmarking:
   - Paired Wilcoxon signed-rank tests
   - Out-of-sample evaluation on unseen test waves
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from warehouse_ai.utils.geometry import Network


def tour_len(D: np.ndarray, tour: list[int]) -> float:
    """Compute the total tour length given a distance matrix and visiting order."""
    return float(sum(D[tour[k], tour[k + 1]] for k in range(len(tour) - 1)))


def tour_nn_2opt(D: np.ndarray, max_passes: int = 10) -> list[int]:
    """Nearest-Neighbor TSP tour followed by 2-opt edge-exchange improvements.

    Parameters
    ----------
    D : np.ndarray
        Distance matrix of shape (n, n), where index 0 is the depot.
    max_passes : int
        Maximum number of 2-opt improvement passes (default 10).

    Returns
    -------
    list[int]
        Visiting order starting at 0, visiting all stops 1..n-1, and returning to 0.
    """
    n = D.shape[0]
    if n <= 2:
        return list(range(n)) + [0]

    Dl = D.tolist()
    unvisited = set(range(1, n))
    tour = [0]
    cur = 0

    # 1. Greedy Nearest Neighbor tour
    while unvisited:
        row = Dl[cur]
        nxt = min(unvisited, key=row.__getitem__)
        tour.append(nxt)
        unvisited.remove(nxt)
        cur = nxt
    tour.append(0)

    # 2. 2-opt local search refinement
    passes = 0
    improved = True
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b, c, e = tour[i - 1], tour[i], tour[j], tour[j + 1]
                # Reversal gain check
                if Dl[a][c] + Dl[b][e] < Dl[a][b] + Dl[c][e] - 1e-9:
                    tour[i : j + 1] = tour[i : j + 1][::-1]
                    improved = True

    return tour


def tour_serpentine(D: np.ndarray, nodes: np.ndarray, net: Network) -> list[int]:
    """Serpentine / S-shape routing heuristic.

    Sorts stops aisle by aisle, alternating direction along each walkway;
    evaluates both forward and reverse sweep sequences and returns the shorter tour.
    """
    idx = np.arange(1, len(nodes))
    a = net.aisle[nodes[1:]]
    s = net.s[nodes[1:]]
    aisles = sorted(set(a))

    best_len = np.inf
    best_tour: list[int] = [0]

    for seq in (aisles, aisles[::-1]):
        tour = [0]
        ascending = True
        for ai in seq:
            m = idx[a == ai]
            sorted_idx = m[np.argsort(s[a == ai] * (1 if ascending else -1), kind="stable")]
            tour.extend(sorted_idx.tolist())
            ascending = not ascending
        tour.append(0)

        length = tour_len(D, tour)
        if length < best_len:
            best_len = length
            best_tour = tour

    return best_tour


def evaluate_scenarios(
    picks_df: pd.DataFrame,
    scen_locs: dict[str, tuple[np.ndarray, list[str]]],
    net: Network,
    waves_df: pd.DataFrame | None = None,
    max_passes: int = 10,
    walk_speed_mps: float = 1.0,
    time_per_stop_s: float = 10.0,
    time_per_unit_s: float = 6.0,
    wave_setup_s: float = 60.0,
) -> pd.DataFrame:
    """Evaluate picking waves across storage scenarios and routing heuristics.

    Parameters
    ----------
    picks_df : pd.DataFrame
        Picks DataFrame with wave_number, units / qty.
    scen_locs : dict
        Mapping scenario_name -> (loc_id_array, list_of_routing_methods)
    net : Network
        Calibrated rectilinear distance network.
    waves_df : pd.DataFrame | None
        Optional waves metadata with train/test set flag.
    max_passes : int
        Maximum 2-opt passes.
    walk_speed_mps : float
        Walking speed in metres/second (default 1.0).
    time_per_stop_s : float
        Fixed time per physical pick stop in seconds (default 10.0).
    time_per_unit_s : float
        Variable handling time per picked unit in seconds (default 6.0).
    wave_setup_s : float
        Fixed wave dispatch and setup time in seconds (default 60.0).

    Returns
    -------
    pd.DataFrame
        Detailed per-wave, per-scenario evaluation metrics.
    """
    IO = net.aisle.shape[0] - 1
    picks = picks_df.copy()
    if "wave" not in picks.columns and "wave_number" in picks.columns:
        picks["wave"] = picks["wave_number"]
    if "units" not in picks.columns and "qty" in picks.columns:
        picks["units"] = picks["qty"]

    order = np.argsort(picks["wave"].values, kind="stable")
    wv = picks["wave"].values[order]
    units = picks["units"].values[order]
    starts = np.r_[0, np.flatnonzero(np.diff(wv)) + 1]
    ends = np.r_[starts[1:], len(wv)]
    wave_ids = wv[starts]

    rows = []
    cache: dict[tuple[int, ...], list[int]] = {}

    for scen, (loc_arr, routings) in scen_locs.items():
        la = np.asarray(loc_arr)[order]
        for w, st, en in zip(wave_ids, starts, ends):
            ids, u = la[st:en], units[st:en]
            ok = ids >= 0
            base = {
                "wave": int(w),
                "scenario": scen,
                "units": float(u[ok].sum()),
                "units_unplaced": float(u[~ok].sum()),
            }
            if not ok.any():
                for r in routings:
                    rows.append({
                        **base,
                        "routing": r,
                        "stops": 0,
                        "aisles": 0,
                        "dist_m": 0.0,
                        "visits": 0,
                    })
                continue

            idv = ids[ok]
            uniq, inv_idx = np.unique(idv, return_inverse=True)
            nodes = np.r_[IO, uniq]
            D = net.matrix(nodes)
            n_aisles = len(set(net.aisle[uniq]))

            for r in routings:
                if r == "recorded":
                    seq = inv_idx + 1
                    keep = np.r_[True, seq[1:] != seq[:-1]]
                    tour = [0] + list(seq[keep]) + [0]
                elif r == "serpentine":
                    tour = tour_serpentine(D, nodes, net)
                else:  # nn2opt
                    ck = tuple(uniq)
                    if ck in cache:
                        tour = cache[ck]
                    else:
                        tour = tour_nn_2opt(D, max_passes)
                        cache[ck] = tour

                length = tour_len(D, tour)
                rows.append({
                    **base,
                    "routing": r,
                    "stops": len(uniq),
                    "aisles": n_aisles,
                    "dist_m": length,
                    "visits": len(tour) - 2,
                })

    res = pd.DataFrame(rows)

    # Time model
    res["walk_s"] = res["dist_m"] / walk_speed_mps
    res["stop_s"] = res["stops"] * time_per_stop_s
    res["pick_s"] = res["units"] * time_per_unit_s
    res["setup_s"] = wave_setup_s
    res["time_s"] = res["walk_s"] + res["stop_s"] + res["pick_s"] + res["setup_s"]
    res["minutes"] = res["time_s"] / 60.0

    # Add train/test set flag if waves_df is provided
    if waves_df is not None and "set" in waves_df.columns:
        set_map = dict(zip(waves_df.index, waves_df["set"]))
        res["set"] = res["wave"].map(set_map)

    return res


def scenario_summary(
    res_df: pd.DataFrame,
    base_key: tuple[str, str] = ("AS-IS (historical)", "recorded"),
) -> pd.DataFrame:
    """Compute aggregate scenario summary metrics across ALL waves and TEST waves."""
    # Find fully placed waves (waves with 0 unplaced units across all evaluated scenarios)
    unplaced_by_wave = res_df.groupby("wave")["units_unplaced"].sum()
    complete_waves = unplaced_by_wave[unplaced_by_wave == 0].index.values

    sub_res = res_df[res_df["wave"].isin(complete_waves)].copy()

    samples = [("ALL waves (fully placed in all scenarios)", sub_res)]
    if "set" in sub_res.columns:
        test_sub = sub_res[sub_res["set"] == "test"]
        if not test_sub.empty:
            samples.append(("TEST waves only (out-of-sample)", test_sub))

    summary_rows = []
    for sample_label, s_df in samples:
        # AS-IS baseline values for this sample
        base_match = s_df[(s_df["scenario"] == base_key[0]) & (s_df["routing"] == base_key[1])]
        base_mean_dist = base_match["dist_m"].mean() if not base_match.empty else 1.0
        base_mean_time = base_match["minutes"].mean() if not base_match.empty else 1.0

        for (scen, rout), grp in s_df.groupby(["scenario", "routing"]):
            n_waves = len(grp)
            tot_units = grp["units"].sum()
            mean_dist = grp["dist_m"].mean()
            median_dist = grp["dist_m"].median()
            p90_dist = grp["dist_m"].quantile(0.90)
            total_km = grp["dist_m"].sum() / 1000.0
            mean_time_min = grp["minutes"].mean()
            total_hours = grp["time_s"].sum() / 3600.0
            walk_share = grp["walk_s"].sum() / max(1.0, grp["time_s"].sum())
            units_per_hour = tot_units / max(0.001, total_hours)
            m_per_unit = grp["dist_m"].sum() / max(1.0, tot_units)

            dist_saving_pct = 100.0 * (1.0 - mean_dist / base_mean_dist)
            time_saving_pct = 100.0 * (1.0 - mean_time_min / base_mean_time)

            summary_rows.append({
                "sample": sample_label,
                "scenario": scen,
                "routing": rout,
                "waves": n_waves,
                "units": tot_units,
                "unplaced_units": grp["units_unplaced"].sum(),
                "mean_stops": grp["stops"].mean(),
                "mean_aisles": grp["aisles"].mean(),
                "mean_dist_m": mean_dist,
                "median_dist_m": median_dist,
                "p90_dist_m": p90_dist,
                "total_km": total_km,
                "mean_time_min": mean_time_min,
                "total_hours": total_hours,
                "walk_share": walk_share,
                "units_per_hour": units_per_hour,
                "m_per_unit": m_per_unit,
                "dist_saving_vs_asis_%": dist_saving_pct,
                "time_saving_vs_asis_%": time_saving_pct,
            })

    return pd.DataFrame(summary_rows)


def statistical_comparison(
    res_df: pd.DataFrame,
    scen_a: tuple[str, str],
    scen_b: tuple[str, str],
) -> dict[str, Any]:
    """Perform a paired Wilcoxon signed-rank test comparing two scenarios on the same waves."""
    a_df = res_df[(res_df["scenario"] == scen_a[0]) & (res_df["routing"] == scen_a[1])].set_index("wave")
    b_df = res_df[(res_df["scenario"] == scen_b[0]) & (res_df["routing"] == scen_b[1])].set_index("wave")

    common = a_df.index.intersection(b_df.index)
    da = a_df.loc[common, "dist_m"].values
    db = b_df.loc[common, "dist_m"].values

    diff = da - db
    med_saving = float(np.median(diff))
    pct_improved = float((diff > 0).mean() * 100.0)

    try:
        w_stat, p_val = stats.wilcoxon(da, db)
    except Exception:
        w_stat, p_val = 0.0, 1.0

    return {
        "scenario_a": f"{scen_a[0]} ({scen_a[1]})",
        "scenario_b": f"{scen_b[0]} ({scen_b[1]})",
        "n_waves": len(common),
        "mean_a_m": float(np.mean(da)),
        "mean_b_m": float(np.mean(db)),
        "median_saving_m": med_saving,
        "waves_improved_pct": pct_improved,
        "wilcoxon_stat": float(w_stat),
        "p_value": float(p_val),
    }
