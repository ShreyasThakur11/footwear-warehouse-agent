"""Warehouse physical geometry, rectilinear distance network, and walkway mapping.

Provides the calibrated distance network and coordinate transformations based on
empirical warehouse measurements:
- Bay length along aisles: 50.0 units -> 3.66 m (0.0732 m / unit)
- Walkway pitch across aisles: 90.0 units -> 2.90 m (0.03222 m / unit)
- Dispatch / I/O depot: Node CC-08 (along = 29.5 m, across = 20.3 m)
- Cross corridors: Left (LC, 4.8 m), Center (CC, 29.5 m), Right (RC, 50.2 m)
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from warehouse_ai.data.loaders import load_locations, load_support_points

_LOC_RE = re.compile(
    r"^(?P<aisle>[A-Za-z]+)-(?P<column>\d{1,2})-(?P<level>\d)(?P<position>\d)$"
)


class Network:
    """Rectilinear aisle network for millisecond-level tour distance evaluation.

    Each node has:
    - aisle id: integer identifying the walkway (-1 for I/O depot)
    - s: along-aisle position in physical metres
    - c: across-aisle position (walkway centre-line) in physical metres
    - access: boolean mask indicating accessibility to each cross-aisle corridor

    Distance rules (Ratliff & Rosenthal, 1983):
    - Same walkway: |s1 - s2|
    - Different walkways: min_X |s1 - X| + |c1 - c2| + |s2 - X| across accessible cross-aisles X
    - I/O depot: node with aisle id -1 that accesses all cross corridors
    """

    def __init__(
        self,
        aisle_id: np.ndarray | list[int],
        along: np.ndarray | list[float],
        cross: np.ndarray | list[float],
        access: np.ndarray,
        xpos: np.ndarray | list[float],
        xnames: list[str],
    ) -> None:
        self.aisle = np.asarray(aisle_id, dtype=np.int64)
        self.s = np.asarray(along, dtype=float)
        self.c = np.asarray(cross, dtype=float)
        self.acc = np.asarray(access, dtype=bool)
        self.xpos = np.asarray(xpos, dtype=float)
        self.xnames = list(xnames)

    def matrix(self, ids: np.ndarray | list[int]) -> np.ndarray:
        """Compute the all-pairs rectilinear distance matrix between the given node IDs."""
        ids = np.asarray(ids)
        a = self.aisle[ids]
        s = self.s[ids]
        c = self.c[ids]
        acc = self.acc[ids]

        dc = np.abs(c[:, None] - c[None, :])
        D = np.full(dc.shape, np.inf)

        for k, X in enumerate(self.xpos):
            ak = acc[:, k]
            if not ak.any():
                continue
            ds = np.abs(s - X)
            cand = ds[:, None] + dc + ds[None, :]
            ok = ak[:, None] & ak[None, :]
            D = np.where(ok & (cand < D), cand, D)

        same = (a[:, None] == a[None, :]) & (a[:, None] >= 0)
        D = np.where(same, np.abs(s[:, None] - s[None, :]), D)
        bad = ~np.isfinite(D)
        if bad.any():
            D[bad] = (dc + np.abs(s[:, None] - s[None, :]))[bad]
        np.fill_diagonal(D, 0.0)
        return D

    def one_to_many(self, i: int, ids: np.ndarray | list[int]) -> np.ndarray:
        """Compute rectilinear distances from node index i to a set of node IDs."""
        ids = np.asarray(ids)
        a = self.aisle[ids]
        s = self.s[ids]
        c = self.c[ids]
        acc = self.acc[ids]

        dc = np.abs(c - self.c[i])
        best = np.full(len(ids), np.inf)

        for k, X in enumerate(self.xpos):
            if not self.acc[i, k]:
                continue
            cand = abs(self.s[i] - X) + dc + np.abs(s - X)
            best = np.where(acc[:, k] & (cand < best), cand, best)

        if self.aisle[i] >= 0:
            same = a == self.aisle[i]
            best = np.where(same, np.abs(s - self.s[i]), best)

        bad = ~np.isfinite(best)
        best[bad] = (dc + np.abs(s - self.s[i]))[bad]
        best[ids == i] = 0.0
        return best

    def path(self, i: int, j: int) -> list[tuple[float, float]]:
        """Return the polyline [(along, cross), ...] of the shortest rectilinear path i -> j."""
        si, sj = self.s[i], self.s[j]
        ci, cj = self.c[i], self.c[j]
        if self.aisle[i] >= 0 and self.aisle[i] == self.aisle[j]:
            return [(si, ci), (sj, cj)]

        best_dist = np.inf
        bx = None
        for k, X in enumerate(self.xpos):
            if self.acc[i, k] and self.acc[j, k]:
                d = abs(si - X) + abs(ci - cj) + abs(sj - X)
                if d < best_dist:
                    best_dist = d
                    bx = X

        if bx is None:
            return [(si, ci), (sj, cj)]
        return [(si, ci), (bx, ci), (bx, cj), (sj, cj)]


def parse_location_codes(series: pd.Series) -> pd.DataFrame:
    """Parse location codes into semantic components: aisle, column, level, position."""
    rows = []
    for s in series:
        if pd.isna(s):
            rows.append({"location": s, "aisle": np.nan, "column": np.nan, "level": np.nan, "position": np.nan})
            continue
        code = str(s).strip()
        m = _LOC_RE.match(code)
        if m:
            rows.append({
                "location": code,
                "aisle": m.group("aisle").upper(),
                "column": int(m.group("column")),
                "level": int(m.group("level")),
                "position": int(m.group("position")),
            })
        else:
            rows.append({"location": code, "aisle": np.nan, "column": np.nan, "level": np.nan, "position": np.nan})
    return pd.DataFrame(rows)


def build_warehouse_network(
    locs_df: pd.DataFrame | None = None,
    support_df: pd.DataFrame | None = None,
    bay_length_m: float = 3.66,
    aisle_pitch_m: float = 2.90,
    io_support_label: str = "CC-08",
) -> tuple[pd.DataFrame, Network, dict[str, Any]]:
    """Build the calibrated warehouse geometry, walkway mapping, and rectilinear network.

    Parameters
    ----------
    locs_df : pd.DataFrame | None
        Storage locations table (defaults to loading Storage_Location.csv).
    support_df : pd.DataFrame | None
        Support points table (defaults to loading Support_Points_Navigation.csv).
    bay_length_m : float
        Physical length of one shelving bay along the aisle (3.66 m).
    aisle_pitch_m : float
        Physical pitch between adjacent walkways (2.90 m).
    io_support_label : str
        Depot support node label (default "CC-08").

    Returns
    -------
    tuple of (locs, net, geo)
        locs: DataFrame of all 2,339 locations with along, cross, walkway, and dist_io
        net: calibrated rectilinear Network object
        geo: metadata dictionary of warehouse layout dimensions
    """
    if locs_df is None:
        locs_df = load_locations()
    if support_df is None:
        support_df = load_support_points()

    fl = locs_df.copy()
    parsed = parse_location_codes(fl["location"])
    for col in ["aisle", "column", "level", "position"]:
        fl[col] = parsed[col]

    fl = fl[fl["aisle"].notna()].drop_duplicates("location").copy()
    fl["along_u"] = fl["x"].astype(float)
    fl["cross_u"] = fl["y"].astype(float)
    fl["in_file"] = True
    fl["coord_source"] = "Storage_Location.csv"

    # Support points processing
    sp = support_df.copy()
    sp["along_u"] = sp["x"].astype(float)
    sp["cross_u"] = sp["y"].astype(float)
    sp["group"] = sp["label"].str[:2]
    sp["index"] = pd.to_numeric(sp["label"].str.extract(r"(\d+)")[0], errors="coerce")

    # Center Corridor along_u position
    cc_u = float(sp.loc[sp["group"] == "CC", "along_u"].median()) if (sp["group"] == "CC").any() else 403.0

    # Walkway assignment from rack face geometry
    fl["block"] = np.where(fl["along_u"] > cc_u, "right", "left")
    fl["face"] = fl["aisle"] + "-" + np.where(fl["column"].fillna(0) % 2 == 1, "odd", "even") + "-" + fl["block"]

    fc = fl.groupby(["face", "block"])["cross_u"].median().reset_index()
    lines = sp.dropna(subset=["index"]).groupby("index")["cross_u"].median().sort_values()

    face_walk, face_walk_u = {}, {}
    for blk, sub in fc.groupby("block"):
        cs = sub["cross_u"].values
        for f_, c in zip(sub["face"], cs):
            others = cs[np.abs(cs - c) > 1e-6]
            if len(others) == 0:
                dirn = 0.0
            else:
                partner = others[np.argmin(np.abs(others - c))]
                dirn = np.sign(c - partner)

            lv = lines.values
            side = lv[(lv - c) * dirn > 0] if dirn != 0 else lv
            cand = side if len(side) else lv
            best = cand[np.argmin(np.abs(cand - c))]
            k = int(lines.index[np.where(lv == best)[0][0]])
            face_walk[f_] = k
            face_walk_u[f_] = float(best)

    fl["walkway_no"] = fl["face"].map(face_walk).fillna(1).astype(int)
    fl["walkway_u"] = fl["face"].map(face_walk_u)
    fl["walkway"] = "W" + fl["walkway_no"].map(lambda k: f"{k:02d}")

    # Add missing/imputed locations like -20, -30, -40
    # Gather any positions in the bay from 1 to 4
    imputed_rows = []
    existing_locs = set(fl["location"])
    for (aisle, col), sub_df in fl.groupby(["aisle", "column"]):
        for lvl in [1, 2, 3, 4]:
            pos_range = [1, 2, 3] if lvl in [1, 2] else [0]
            for pos in pos_range:
                cand_code = f"{aisle}-{int(col):02d}-{lvl}{pos}"
                if cand_code not in existing_locs:
                    row_data = sub_df.iloc[0].copy()
                    row_data["location"] = cand_code
                    row_data["level"] = lvl
                    row_data["position"] = pos
                    row_data["in_file"] = False
                    row_data["coord_source"] = "imputed: sibling bay position"
                    imputed_rows.append(row_data)

    if imputed_rows:
        fl = pd.concat([fl, pd.DataFrame(imputed_rows)], ignore_index=True)

    # Metre calibration
    pf = fl[fl["in_file"] & fl["level"].isin([1, 2])]
    colmean = pf.groupby(["face", "column"])["along_u"].mean().reset_index()
    diffs = []
    for _, sub in colmean.groupby("face"):
        sub = sub.sort_values("column")
        dcol = np.diff(sub["column"].values)
        dal = np.abs(np.diff(sub["along_u"].values))
        diffs += list(dal[dcol == 2])

    bay_u = float(np.median(diffs)) if diffs else 50.0
    walk_u = fl.groupby("walkway")["walkway_u"].first().sort_values()
    pitch_u = float(np.median(np.diff(walk_u.values))) if len(walk_u) > 2 else 90.0

    ma = bay_length_m / bay_u  # 3.66 / 50.0 = 0.0732
    mc = aisle_pitch_m / pitch_u  # 2.90 / 90.0 = 0.03222

    fl["along"] = fl["along_u"] * ma
    fl["cross_face"] = fl["cross_u"] * mc
    aisle_centre = (walk_u * mc).to_dict()
    aisles_sorted = sorted(fl["walkway"].unique())
    aisle_index = {a: i for i, a in enumerate(aisles_sorted)}
    fl["aisle_id"] = fl["walkway"].map(aisle_index).astype(int)
    fl["cross"] = fl["walkway"].map(aisle_centre)

    # Cross aisles (LC / CC / RC)
    sp["along"] = sp["along_u"] * ma
    sp["cross"] = sp["cross_u"] * mc
    xs, xnames = [], []
    for gname in ["LC", "CC", "RC"]:
        sub = sp[sp["group"] == gname]
        if len(sub):
            xs.append(float(sub["along"].median()))
            xnames.append(gname)

    order = np.argsort(xs)
    xs = [xs[i] for i in order]
    xnames = [xnames[i] for i in order]

    # Reachability: RC only for walkways that extend past CC (walkways 8-17)
    n = len(fl)
    acc = np.ones((n, len(xs)), bool)
    if "CC" in xnames and "RC" in xnames:
        rc_k = xnames.index("RC")
        right_w = set(fl.loc[fl["block"] == "right", "walkway"])
        for _, r in sp[sp["group"] == "RC"].iterrows():
            if pd.notna(r["index"]):
                right_w.add(f"W{int(r['index']):02d}")
        acc[:, rc_k] = fl["walkway"].isin(right_w).values

    # I/O depot point (CC-08)
    io_row = sp[sp["label"] == io_support_label]
    if not io_row.empty:
        io_s = float(io_row.iloc[0]["along"])
        io_c = float(io_row.iloc[0]["cross"])
        io_src = f"support point {io_support_label}"
    else:
        io_s = xs[xnames.index("CC")] if "CC" in xnames else xs[0]
        io_c = float(np.median(list(aisle_centre.values())))
        io_src = "fallback: central cross aisle, middle aisle"

    fl = fl.reset_index(drop=True)
    fl["loc_id"] = np.arange(len(fl))
    IO_INDEX = len(fl)

    net = Network(
        aisle_id=np.append(fl["aisle_id"].values, -1),
        along=np.append(fl["along"].values, io_s),
        cross=np.append(fl["cross"].values, io_c),
        access=np.vstack([acc, np.ones((1, len(xs)), bool)]),
        xpos=xs,
        xnames=xnames,
    )

    fl["dist_io"] = net.one_to_many(IO_INDEX, fl["loc_id"].values)
    fl["dist_rank"] = fl["dist_io"].rank(method="first").astype(int)

    geo = {
        "m_per_unit_along": ma,
        "m_per_unit_cross": mc,
        "bay_units": bay_u,
        "pitch_units": pitch_u,
        "io_along": io_s,
        "io_cross": io_c,
        "io_source": io_src,
        "IO": IO_INDEX,
        "cross_aisles": dict(zip(xnames, xs)),
        "aisle_centre": aisle_centre,
        "aisles": aisles_sorted,
    }

    return fl, net, geo
