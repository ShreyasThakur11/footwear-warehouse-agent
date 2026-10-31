"""Data loaders for the 9 raw CSV files.

Each public function returns a cleaned ``pandas.DataFrame`` with:
- Whitespace stripped from all string columns and column names.
- Columns renamed to snake_case conventions.

Separator and encoding quirks are handled per-file as documented in the
raw data README.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pandas as pd

from warehouse_ai.config import get_config

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raw_dir() -> Path:
    """Return the resolved path to ``data/raw``."""
    cfg = get_config()
    root = Path(__file__).resolve().parents[3]
    return root / cfg.paths.data_raw


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Strip leading/trailing whitespace from column names and all object cols."""
    df.columns = [c.strip() for c in df.columns]
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()
    return df


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_orders(path: str | Path | None = None) -> pd.DataFrame:
    """Load ``Customer_Order.csv`` → cleaned DataFrame.

    Columns returned
    ----------------
    customer_code, order_number, order_to_collect, reference, size_raw,
    qty, created_at (datetime), wave_number, operator
    """
    path = Path(path) if path else _raw_dir() / "Customer_Order.csv"
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    df = _strip_strings(df)

    df = df.rename(columns={
        "codCustomer": "customer_code",
        "orderNumber": "order_number",
        "orderToCollect": "order_to_collect",
        "Reference": "reference",
        "Size (US)": "size_raw",
        "quantity (units)": "qty",
        "creationDate": "created_at",
        "waveNumber": "wave_number",
        "operator": "operator",
    })

    df["created_at"] = pd.to_datetime(df["created_at"], dayfirst=True)
    return df


def load_picks(path: str | Path | None = None) -> pd.DataFrame:
    """Load ``Picking_Wave.csv`` → cleaned DataFrame.

    Columns returned
    ----------------
    wave_number, reference, size_raw, qty, location, operator
    """
    path = Path(path) if path else _raw_dir() / "Picking_Wave.csv"
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    df = _strip_strings(df)

    df = df.rename(columns={
        "waveNumber": "wave_number",
        "reference": "reference",
        "Size (US)": "size_raw",
        "quantityToPick (units)": "qty",
        "locations": "location",
        "operator": "operator",
    })
    return df


def load_products(path: str | Path | None = None) -> pd.DataFrame:
    """Load ``Product.csv`` → cleaned DataFrame.

    Columns returned
    ----------------
    reference, abc_code, sector
    """
    path = Path(path) if path else _raw_dir() / "Product.csv"
    df = pd.read_csv(path, sep=";", encoding="utf-8")
    df = _strip_strings(df)

    df = df.rename(columns={
        "Reference": "reference",
        "ABCCOD": "abc_code",
        "Sector": "sector",
    })
    return df


def load_locations(path: str | Path | None = None) -> pd.DataFrame:
    """Load ``Storage_Location.csv`` → cleaned DataFrame.

    Columns returned
    ----------------
    location, position, x, y, z
    """
    path = Path(path) if path else _raw_dir() / "Storage_Location.csv"
    df = pd.read_csv(path, sep=",", encoding="utf-8")
    df = _strip_strings(df)

    df = df.rename(columns={
        "originalLocation": "location",
        "position": "position",
    })
    return df


def _load_wide_storage(
    path: Path,
    sep: str,
    encoding: str,
    class_col: str | None,
    policy: str,
) -> pd.DataFrame:
    """Load a wide-format storage CSV and melt to long format.

    Returns one row per (location, slot_index, reference, size_raw, class_code, policy).
    """
    df = pd.read_csv(path, sep=sep, encoding=encoding, dtype=str)
    df = _strip_strings(df)

    # Identify the location column (first col) and class column (second col, if any)
    loc_col = df.columns[0]

    id_vars = [loc_col]
    if class_col and class_col in df.columns:
        id_vars.append(class_col)

    # Slot columns are the numbered ones (1..18) or col_1..col_18
    slot_cols = [c for c in df.columns if c not in id_vars]

    df_long = df.melt(id_vars=id_vars, value_vars=slot_cols, var_name="slot_index", value_name="ref_size")

    # Parse compound "Reference;Size" values
    # For comma-delimited files (Random_Storage), the format is "REF;SIZE" without quotes
    # For semicolon-delimited files, the format is quoted "REF;SIZE"
    df_long["ref_size"] = df_long["ref_size"].str.strip().str.strip('"')
    split = df_long["ref_size"].str.split(";", n=1, expand=True)
    df_long["reference"] = split[0].str.strip() if 0 in split.columns else None
    df_long["size_raw"] = split[1].str.strip() if 1 in split.columns else None

    # Rename columns
    df_long = df_long.rename(columns={loc_col: "location"})
    if class_col and class_col in df_long.columns:
        df_long = df_long.rename(columns={class_col: "class_code"})
    else:
        df_long["class_code"] = None

    df_long["policy"] = policy
    df_long["slot_index"] = df_long["slot_index"].astype(str)

    # Drop rows where ref_size was empty / NaN
    df_long = df_long.dropna(subset=["reference"])
    df_long = df_long[df_long["reference"] != ""]

    return df_long[["location", "slot_index", "reference", "size_raw", "class_code", "policy"]]


def load_storage(
    policy: Literal["random", "class_based", "dedicated", "hybrid"] = "random",
    path: str | Path | None = None,
) -> pd.DataFrame:
    """Load a storage allocation CSV in **long format**.

    Parameters
    ----------
    policy : str
        One of ``"random"``, ``"class_based"``, ``"dedicated"``, ``"hybrid"``.
    path : str | Path | None
        Override path; otherwise resolved from ``data/raw/``.

    Returns
    -------
    pd.DataFrame
        Columns: ``location, slot_index, reference, size_raw, class_code, policy``
    """
    file_map = {
        "random": ("Random_Storage.csv", ",", "utf-8", None),
        "class_based": ("Class_Based_Storage.csv", ";", "utf-8-sig", "ABCCOD"),
        "dedicated": ("Dedicated_Storage.csv", ";", "utf-8-sig", "XYZCOD"),
        "hybrid": ("Hybrid_Storage.csv", ";", "utf-8-sig", "XYZCOD"),
    }

    if policy not in file_map:
        raise ValueError(f"Unknown policy '{policy}'. Choose from: {list(file_map.keys())}")

    fname, sep, enc, class_col = file_map[policy]
    path = Path(path) if path else _raw_dir() / fname
    return _load_wide_storage(path, sep=sep, encoding=enc, class_col=class_col, policy=policy)


def load_support_points(path: str | Path | None = None) -> pd.DataFrame:
    """Load ``Support_Points_Navigation.csv`` → cleaned DataFrame.

    The file uses CR-only (``\\r``) line terminators and a semicolon delimiter.
    Each row has the format: ``(x, y, z);LABEL``

    The label appears **AFTER** its coordinate tuple. For example:
    ``(66.0, -29.0, 1.0);LC-01`` means label LC-01 is at (66, -29, 1).

    Three corridor families exist:
    - **LC** (Left Corridor):  x ≈ 66  — 17 points (LC-01 .. LC-17)
    - **CC** (Center Corridor): x ≈ 403 — 17 points (CC-01 .. CC-17, reversed y order)
    - **RC** (Right Corridor):  x ≈ 686 — 10 points (RC-08 .. RC-17, reversed y order)

    Note: RC only has 10 points (08–17); the warehouse is physically narrower
    on the right side, so RC-01 through RC-07 do not exist.

    Returns
    -------
    pd.DataFrame
        Columns: ``label, x, y, z``
    """
    path = Path(path) if path else _raw_dir() / "Support_Points_Navigation.csv"

    raw = Path(path).read_bytes().decode("utf-8")

    # The file uses \r as line separator (old Mac style), with a final \r\n
    # Split on \r, filter blanks, skip header
    lines = [ln.strip() for ln in raw.replace("\r\n", "\r").split("\r") if ln.strip()]

    # First line is the header "points_specified;labels" — skip it
    data_lines = lines[1:]

    # Pattern: (x, y, z);LABEL  — label comes AFTER the coordinate tuple
    pattern = re.compile(
        r"\(\s*(?P<x>-?[\d.]+)\s*,\s*(?P<y>-?[\d.]+)\s*,\s*(?P<z>-?[\d.]+)\s*\)"
        r"\s*;\s*(?P<label>\S+)"
    )

    records = []
    for line in data_lines:
        m = pattern.match(line)
        if m:
            records.append({
                "label": m.group("label"),
                "x": float(m.group("x")),
                "y": float(m.group("y")),
                "z": float(m.group("z")),
            })

    df = pd.DataFrame(records, columns=["label", "x", "y", "z"])
    return df

