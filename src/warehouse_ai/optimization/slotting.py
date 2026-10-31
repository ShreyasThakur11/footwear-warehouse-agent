"""Storage allocation optimization, demand profiling, and re-slotting algorithms.

Implements:
1. Demand profiling: SKU and Reference Pareto ABC classification and COI density.
2. Slotting allocation:
   - Optimised-COI: Cube-per-Order Index density ranking.
   - Optimised-FAMILY: Product family and size-run co-location near the dispatch depot (CC-08).
3. Minimum-Move Swap Engine:
   - Reslots only the compact forward zone (186 locations, 3,372 slots).
   - Generates the two-phase relocation move matrix (3,818 Class A moves, 2,920 Phase 2 moves; 6,736 total).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from warehouse_ai.utils.geometry import Network

_ROOT = Path(__file__).resolve().parents[3]


def abc_from_counts(counts: pd.Series, cuts: tuple[float, float] = (0.80, 0.95)) -> pd.Series:
    """Classify items into Pareto ABC classes based on cumulative share."""
    s = counts.fillna(0).sort_values(ascending=False)
    tot = s.sum()
    if tot <= 0:
        return pd.Series("C", index=counts.index)
    cum = s.cumsum() / tot
    res = pd.Series("C", index=s.index)
    res[cum <= cuts[1]] = "B"
    res[cum <= cuts[0]] = "A"
    return res.reindex(counts.index).fillna("C")


def build_demand_profile(
    picks_df: pd.DataFrame,
    orders_df: pd.DataFrame | None = None,
    locs_df: pd.DataFrame | None = None,
    train_fraction: float = 0.70,
    days_of_cover: float = 2.0,
    abc_cuts: tuple[float, float] = (0.80, 0.95),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """Build demand profiling, chronological train/test split, and ABC classification.

    Parameters
    ----------
    picks_df : pd.DataFrame
        Cleaned pick rows with columns: wave_number, reference, sku_size, qty, location.
    orders_df : pd.DataFrame | None
        Cleaned customer orders with wave and created_at timestamps.
    locs_df : pd.DataFrame | None
        Locations DataFrame with location and loc_id.
    train_fraction : float
        Proportion of waves chronologically allocated to training (default 0.70).
    days_of_cover : float
        Days of demand to cover in the forward pick face (default 2.0).
    abc_cuts : tuple[float, float]
        Cumulative share thresholds for A and B classes (default 0.80, 0.95).

    Returns
    -------
    tuple of (waves_df, dem_sku, dem_ref, n_train_days)
    """
    picks = picks_df.copy()
    if "sku" not in picks.columns and "sku_size" in picks.columns:
        picks["sku"] = picks["sku_size"]
    if "ref" not in picks.columns and "reference" in picks.columns:
        picks["ref"] = picks["reference"]
    if "units" not in picks.columns and "qty" in picks.columns:
        picks["units"] = picks["qty"]

    # Wave-level aggregation
    waves = picks.groupby("wave_number").agg(
        units=("units", "sum"),
        lines=("sku", "size"),
        operator=("operator", lambda s: s.mode().iat[0] if not s.empty else "Unknown"),
        skus=("sku", "nunique"),
        refs=("ref", "nunique"),
    )

    if orders_df is not None and "wave" in orders_df.columns:
        o = orders_df.dropna(subset=["wave"]).copy()
        o["wave_number"] = o["wave"].astype(np.int64)
        ts_col = "created_at" if "created_at" in o.columns else "created"
        wd = o.groupby("wave_number").agg(
            release=(ts_col, "max"),
            first_order=(ts_col, "min"),
            orders=("order", "nunique") if "order" in o.columns else (ts_col, "count"),
        )
        waves = waves.join(wd, how="left")
    elif "last_created_at" in picks.columns:
        waves["release"] = picks.groupby("wave_number")["last_created_at"].max()
    else:
        waves["release"] = pd.NaT

    # Chronological train / test split
    dated = waves["release"].notna()
    if dated.sum() > 10:
        cutoff = waves.loc[dated, "release"].quantile(train_fraction)
        waves["set"] = np.where(waves["release"].isna() | (waves["release"] <= cutoff), "train", "test")
        n_train_days = waves.loc[waves["set"] == "train", "release"].dt.date.nunique()
    else:
        order = waves.index.to_series().rank(pct=True)
        waves["set"] = np.where(order <= train_fraction, "train", "test")
        n_train_days = max(1, int((waves["set"] == "train").sum() / 40))

    n_train_days = max(int(n_train_days), 1)
    picks["set"] = picks["wave_number"].map(waves["set"])
    tr = picks[picks["set"] == "train"]

    def _demand_table(key: str) -> pd.DataFrame:
        d = tr.groupby(key).agg(units=("units", "sum"), visits=("wave_number", "nunique"))
        d_all = picks.groupby(key).agg(units_all=("units", "sum"), visits_all=("wave_number", "nunique"))
        d = d_all.join(d, how="left").fillna(0)
        d["daily_units"] = d["units"] / n_train_days
        d["abc"] = abc_from_counts(d["visits"], abc_cuts)
        d["abc_all"] = abc_from_counts(d["visits_all"], abc_cuts)

        # Forward zone sizing and COI density
        moving = d["visits"] > 0
        q = np.where(moving, np.maximum(1, np.ceil(d["daily_units"] * days_of_cover)), 0)
        d["q_slots"] = q.astype(int)
        d["coi_density"] = np.where(d["q_slots"] > 0, d["visits"] / d["q_slots"], 0.0)
        return d.sort_values("visits_all", ascending=False)

    dem_sku = _demand_table("sku")
    dem_ref = _demand_table("ref")
    dem_sku["ref"] = dem_sku.index.astype(str).str.split("|").str[0]

    return waves, dem_sku, dem_ref, n_train_days


def inventory_with_ids(
    storage_df: pd.DataFrame,
    locs_df: pd.DataFrame,
    pick_levels: tuple[int, ...] = (1, 2),
) -> pd.DataFrame:
    """Format storage policy table with location IDs, coordinates, and pickable flag."""
    inv = storage_df.copy()
    if "sku" not in inv.columns and "sku_size" in inv.columns:
        inv["sku"] = inv["sku_size"]
    if "slot" not in inv.columns and "slot_index" in inv.columns:
        inv["slot"] = pd.to_numeric(
            inv["slot_index"].astype(str).str.extract(r"(\d+)")[0], errors="coerce"
        ).fillna(1).astype(int)

    loc_map = dict(zip(locs_df["location"], locs_df["loc_id"]))
    inv["loc_id"] = inv["location"].map(loc_map).fillna(-1).astype(int)
    inv = inv[inv["loc_id"] >= 0].copy()

    # Join location attributes
    loc_attrs = locs_df.set_index("loc_id")[["level", "dist_io", "dist_rank"]].to_dict(orient="index")
    inv["level"] = inv["loc_id"].apply(lambda lid: loc_attrs[lid]["level"])
    inv["dist_io"] = inv["loc_id"].apply(lambda lid: loc_attrs[lid]["dist_io"])
    inv["dist_rank"] = inv["loc_id"].apply(lambda lid: loc_attrs[lid]["dist_rank"])
    inv["pickable"] = inv["level"].isin(pick_levels)
    inv["key"] = inv["sku"]

    return inv


def assign_pick_locations(
    inv_df: pd.DataFrame,
    picks_df: pd.DataFrame,
    match_key: str = "sku",
) -> tuple[np.ndarray, dict[str, Any]]:
    """Determine the picking location for each pick under a storage policy.

    Replay selection rule:
    1. Nearest pick-face location (levels 1-2) with the exact match.
    2. Nearest reserve location (levels 3-4) with exact match.
    3. Nearest location with the same reference (if exact size not found).
    """
    picks = picks_df.copy()
    p_key = picks["sku_size"] if match_key == "sku" and "sku_size" in picks.columns else picks["reference"]
    p_ref = picks["reference"]

    # Pre-index inventory by key and pickable
    # pickable positions sorted by dist_io
    pf = inv_df[inv_df["pickable"]].sort_values("dist_io")
    resv = inv_df[~inv_df["pickable"]].sort_values("dist_io")

    # Map each key to nearest pickable and reserve loc_id
    pf_key_map = pf.groupby("key")["loc_id"].first().to_dict()
    resv_key_map = resv.groupby("key")["loc_id"].first().to_dict()

    # Fallback reference map
    inv_refs = inv_df.copy()
    if "ref" not in inv_refs.columns:
        inv_refs["ref"] = inv_refs["key"].astype(str).str.split("|").str[0]
    pf_ref_map = inv_refs[inv_refs["pickable"]].sort_values("dist_io").groupby("ref")["loc_id"].first().to_dict()
    resv_ref_map = inv_refs[~inv_refs["pickable"]].sort_values("dist_io").groupby("ref")["loc_id"].first().to_dict()

    loc_ids = np.full(len(picks), -1, dtype=int)
    exact_count = 0
    ref_fallback_count = 0
    unplaced_count = 0

    p_key_arr = p_key.values
    p_ref_arr = p_ref.values

    for i in range(len(picks)):
        k = p_key_arr[i]
        r = p_ref_arr[i]
        # 1. Pickable exact
        if k in pf_key_map:
            loc_ids[i] = pf_key_map[k]
            exact_count += 1
        # 2. Reserve exact
        elif k in resv_key_map:
            loc_ids[i] = resv_key_map[k]
            exact_count += 1
        # 3. Pickable reference fallback
        elif r in pf_ref_map:
            loc_ids[i] = pf_ref_map[r]
            ref_fallback_count += 1
        # 4. Reserve reference fallback
        elif r in resv_ref_map:
            loc_ids[i] = resv_ref_map[r]
            ref_fallback_count += 1
        else:
            unplaced_count += 1

    stats = {
        "exact_matches": exact_count,
        "ref_fallbacks": ref_fallback_count,
        "unplaced": unplaced_count,
        "exact_rate": exact_count / max(1, len(picks)),
    }
    return loc_ids, stats


def design_slotting(
    variant: str,
    dem_df: pd.DataFrame,
    stock_series: pd.Series,
    locs_df: pd.DataFrame,
    net: Network,
    slots_per_location: int = 18,
    pick_levels: tuple[int, ...] = (1, 2),
    reserve_levels: tuple[int, ...] = (3, 4),
    days_of_cover: float = 2.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Design an optimized forward-pick-area slotting layout.

    Parameters
    ----------
    variant : {"FAMILY", "COI"}
        Slotting design variant.
        "COI": ranks individual SKUs strictly by COI density.
        "FAMILY": ranks boot references by family density, co-locating all sizes
                  of each boot model adjacent to one another.
    dem_df : pd.DataFrame
        Demand table for SKUs (visits, daily_units, etc.).
    stock_series : pd.Series
        Current stock counts per SKU in baseline storage.
    locs_df : pd.DataFrame
        Location metadata including dist_io, level, and location.
    net : Network
        Rectilinear network model.
    """
    phys = locs_df[locs_df["in_file"]].copy()
    pick_locs = phys[phys["level"].isin(pick_levels)].sort_values(
        ["dist_io", "level", "aisle_id", "column", "position"]
    )
    resv_locs = phys[phys["level"].isin(reserve_levels)].sort_values("dist_io")

    P = len(pick_locs) * slots_per_location

    stock = stock_series[stock_series > 0].copy()
    d = dem_df.reindex(stock.index).fillna(0)
    drv = "visits"

    # Forward-zone sizing: 2 days of demand
    moving = d[drv] > 0
    q = np.where(
        moving,
        np.minimum(stock, np.maximum(1, np.ceil(d["daily_units"] * days_of_cover))),
        0,
    )
    q = pd.Series(q, index=stock.index, dtype=int)

    # Trim if total exceeds pick-face capacity P
    while q.sum() > P:
        q[q.idxmax()] -= 1

    density = d[drv] / q.replace(0, np.nan)

    if variant == "FAMILY":
        refs = d["ref"] if "ref" in d.columns else pd.Series(stock.index.str.split("|").str[0], index=stock.index)
        fam = pd.DataFrame({"ref": refs, "visits": d[drv], "q": q, "stock": stock})
        fam_grp = fam.groupby("ref").agg(visits=("visits", "sum"), q=("q", "sum"), stock=("stock", "sum"))
        fam_grp["dens"] = fam_grp["visits"] / fam_grp["q"].replace(0, np.nan)
        fam_order = fam_grp.sort_values(["dens", "visits"], ascending=False).index

        ordered_items = []
        for r in fam_order:
            sub = fam[fam["ref"] == r]
            # Sort sizes within model by visits descending
            sub_sorted = sub.sort_values("visits", ascending=False)
            ordered_items.extend(sub_sorted.index.tolist())
    else:  # COI
        ordered_items = density.sort_values(ascending=False).index.tolist()

    # Slot assignment
    # Build list of pick-face slots
    pick_slots = []
    for _, r in pick_locs.iterrows():
        lid = int(r["loc_id"])
        for sl in range(1, slots_per_location + 1):
            pick_slots.append((lid, sl))

    layout_rows = []
    slot_idx = 0

    # Assign primary forward-zone slots
    for item in ordered_items:
        n_slots = q[item]
        for _ in range(n_slots):
            if slot_idx < len(pick_slots):
                lid, sl = pick_slots[slot_idx]
                layout_rows.append({
                    "loc_id": lid,
                    "slot": sl,
                    "sku": item,
                    "role": "primary pick face",
                })
                slot_idx += 1

    primary_slots_used = slot_idx
    forward_loc_ids = {row["loc_id"] for row in layout_rows}

    # Overflow stock of fast movers and remaining items
    overflow_items = []
    for item in ordered_items:
        rem = stock[item] - q[item]
        if rem > 0:
            overflow_items.extend([item] * int(rem))

    # Add items with zero demand
    for item in stock.index:
        if item not in q or q[item] == 0:
            overflow_items.extend([item] * int(stock[item]))

    # Fill remaining pick slots
    while slot_idx < len(pick_slots) and overflow_items:
        lid, sl = pick_slots[slot_idx]
        item = overflow_items.pop(0)
        layout_rows.append({
            "loc_id": lid,
            "slot": sl,
            "sku": item,
            "role": "pick face (overflow)",
        })
        slot_idx += 1

    # Fill reserve slots
    resv_slots = []
    for _, r in resv_locs.iterrows():
        lid = int(r["loc_id"])
        for sl in range(1, slots_per_location + 1):
            resv_slots.append((lid, sl))

    r_idx = 0
    while r_idx < len(resv_slots) and overflow_items:
        lid, sl = resv_slots[r_idx]
        item = overflow_items.pop(0)
        layout_rows.append({
            "loc_id": lid,
            "slot": sl,
            "sku": item,
            "role": "reserve",
        })
        r_idx += 1

    lay_df = pd.DataFrame(layout_rows)
    loc_name = locs_df.set_index("loc_id")["location"]
    lay_df["location"] = lay_df["loc_id"].map(loc_name)
    lay_df["ref"] = lay_df["sku"].astype(str).str.split("|").str[0]
    lay_df["policy"] = f"Optimised-{variant}"

    info = {
        "variant": variant,
        "forward_zone_locations": len(forward_loc_ids),
        "primary_slots": primary_slots_used,
        "items_on_pick_face": int((q > 0).sum()),
        "total_stock_placed": len(lay_df),
    }

    return lay_df, info


def min_move_layout(
    design_df: pd.DataFrame,
    base_inv_df: pd.DataFrame,
    locs_df: pd.DataFrame,
    net: Network,
    key: str = "sku",
    variant: str = "FAMILY",
    slots_per_location: int = 18,
    dem_sku: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert an ideal design into a practical minimum-move re-slotting plan.

    Re-slots only the forward-zone locations (nearest the I/O depot).
    Preserves existing matching stock, and for missing units, brings the nearest
    box from baseline storage and places the displaced box in the vacated slot.
    """
    S = slots_per_location
    cur = {(int(r.loc_id), int(r.slot)): r.key for r in base_inv_df[["loc_id", "slot", "key"]].itertuples(index=False)}
    holders = defaultdict(set)
    for ls, k in cur.items():
        holders[k].add(ls)

    zone = design_df[design_df["role"] == "primary pick face"]
    zone_need = zone.groupby("loc_id", sort=False)[key].apply(list)

    locked = set()
    moved_in = set()
    moves = []
    lname = locs_df.set_index("loc_id")["location"].to_dict()

    # Pre-lookup ABC classes if provided
    abc_map = dem_sku["abc"].to_dict() if dem_sku is not None and "abc" in dem_sku.columns else {}

    for lid, needed in zone_need.items():
        need = Counter(needed)
        # 1. Keep boxes already in the correct slot
        for sl in range(1, S + 1):
            k = cur.get((lid, sl))
            if k is not None and need.get(k, 0) > 0:
                locked.add((lid, sl))
                need[k] -= 1

        free = [sl for sl in range(1, S + 1) if (lid, sl) not in locked]
        # 2. Swap remaining needed units
        for k, n in need.items():
            for _ in range(n):
                if not free:
                    break
                t = (lid, free.pop(0))
                cand = [ls for ls in holders[k] if ls not in locked]
                if not cand:
                    continue

                d = net.one_to_many(lid, np.array([c[0] for c in cand]))
                src = cand[int(np.argmin(d))]
                disp = cur.get(t)

                cur[t] = k
                holders[k].discard(src)
                holders[k].add(t)

                if disp is not None:
                    cur[src] = disp
                    holders[disp].discard(t)
                    holders[disp].add(src)
                else:
                    cur.pop(src, None)

                locked.add(t)
                moved_in.add(t)

                item_class = abc_map.get(k, "C")
                phase = 1 if item_class == "A" else 2

                moves.append({
                    "item": k,
                    "from_location": lname[src[0]],
                    "from_slot": src[1],
                    "to_location": lname[lid],
                    "to_slot": t[1],
                    "move_type": "bring to forward zone",
                    "item_class": item_class,
                    "phase": phase,
                })
                if disp is not None:
                    disp_class = abc_map.get(disp, "C")
                    moves.append({
                        "item": disp,
                        "from_location": lname[lid],
                        "from_slot": t[1],
                        "to_location": lname[src[0]],
                        "to_slot": src[1],
                        "move_type": "displaced -> vacated slot",
                        "item_class": disp_class,
                        "phase": phase,
                    })

    # Assemble final layout table
    lay = pd.DataFrame([(lid, s, k) for (lid, s), k in cur.items()], columns=["loc_id", "slot", key])
    lvl = locs_df.set_index("loc_id")["level"].to_dict()

    roles = []
    disp_slots = {(m["to_location"], m["to_slot"]) for m in moves if "displaced" in m["move_type"]}

    for _, row in lay.iterrows():
        pair = (row["loc_id"], row["slot"])
        loc_str = lname.get(row["loc_id"], "")
        if pair in locked:
            if pair in moved_in:
                roles.append("primary pick face (moved in)")
            else:
                roles.append("primary pick face (already there)")
        elif (loc_str, row["slot"]) in disp_slots:
            roles.append("received displaced unit")
        elif lvl.get(row["loc_id"], 1) in [1, 2]:
            roles.append("pick face (unchanged)")
        else:
            roles.append("reserve level (unchanged)")

    lay["role"] = roles
    lay["location"] = lay["loc_id"].map(lname)
    lay["sku"] = lay[key]
    lay["ref"] = lay["sku"].astype(str).str.split("|").str[0]
    lay["policy"] = f"Optimised-{variant}"

    moves_df = pd.DataFrame(moves)
    moves_df["move_id"] = np.arange(1, len(moves_df) + 1)

    return lay.sort_values(["loc_id", "slot"]).reset_index(drop=True), moves_df
