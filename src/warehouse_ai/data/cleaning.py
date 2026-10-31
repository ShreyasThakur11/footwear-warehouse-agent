"""Data cleaning and transformation pipeline.

Normalizes footwear sizes, parses warehouse coordinate syntax, and compiles
clean Parquet tables for downstream analytics and optimization.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

# Standard half sizes encoded as 2- or 3-digit integers
_HALF_SIZE_INTS = {35.0, 45.0, 55.0, 65.0, 75.0, 85.0, 95.0, 105.0, 115.0, 125.0}


def decode_size(raw_size: Any) -> float | None:
    """Decode a raw footwear size into a standard decimal float.

    Rules
    -----
    - None / NaN / empty string -> None
    - Values in {35, 45, 55, 65, 75, 85, 95, 105, 115, 125} -> raw / 10.0
    - Whole sizes 1.0..16.0 -> float(raw)
    - Mondopoint mm sizes 215..305 -> float(raw)
    - Decimal strings like "10.5" -> 10.5
    """
    if raw_size is None or pd.isna(raw_size):
        return None

    if isinstance(raw_size, str):
        cleaned = raw_size.strip()
        if not cleaned:
            return None
        try:
            val = float(cleaned)
        except (ValueError, TypeError):
            return None
    elif isinstance(raw_size, (int, float, np.number)):
        val = float(raw_size)
    else:
        return None

    if np.isnan(val):
        return None

    if val in _HALF_SIZE_INTS:
        return round(val / 10.0, 1)

    return round(val, 1)


def decode_size_series(series: pd.Series) -> pd.Series:
    """Vectorized / applied size decoder for pandas Series."""
    return series.apply(decode_size)


# Regex pattern for location codes like "A-14-11", "K-02-23", "B-12-40"
_LOC_PATTERN = re.compile(r"^(?P<aisle>[A-Za-z]+)-(?P<bay>\d+)-(?P<level_slot>\d{2})$")


def parse_location(location: str | None) -> dict[str, Any]:
    """Parse a location string into aisle, bay, level, and slot components.

    Example
    -------
    "A-14-11" -> {"aisle": "A", "bay": 14, "level": 1, "slot": 1}
    "A-14-40" -> {"aisle": "A", "bay": 14, "level": 4, "slot": 0}
    """
    if not location or pd.isna(location):
        return {"aisle": None, "bay": None, "level": None, "slot": None}

    cleaned = str(location).strip()
    match = _LOC_PATTERN.match(cleaned)
    if match:
        aisle = match.group("aisle")
        bay = int(match.group("bay"))
        level_slot = match.group("level_slot")
        level = int(level_slot[0])
        slot = int(level_slot[1])
        return {"aisle": aisle, "bay": bay, "level": level, "slot": slot}

    # Non-standard formats (e.g. "C-022", "EX-01", "ZN-COR")
    parts = cleaned.split("-")
    aisle = parts[0] if parts else None
    return {"aisle": aisle, "bay": None, "level": None, "slot": None}


def parse_locations_df(df: pd.DataFrame, col: str = "location") -> pd.DataFrame:
    """Expand a location column into separate aisle, bay, level, slot columns."""
    parsed = df[col].apply(parse_location).tolist()
    parsed_df = pd.DataFrame(parsed, index=df.index)
    return pd.concat([df, parsed_df], axis=1)


# ---------------------------------------------------------------------------
# Table Builders
# ---------------------------------------------------------------------------

def build_products(df_products: pd.DataFrame) -> pd.DataFrame:
    """Build clean products table."""
    df = df_products.copy()
    df = df.rename(columns={"abc_code": "abc"})
    return df[["reference", "abc", "sector"]]


def build_locations(df_locations: pd.DataFrame) -> pd.DataFrame:
    """Build clean locations table with parsed hierarchical components."""
    df = df_locations.copy()
    parsed = df["location"].apply(parse_location).tolist()
    parsed_df = pd.DataFrame(parsed, index=df.index)

    df["aisle"] = parsed_df["aisle"]
    df["bay"] = parsed_df["bay"]
    # Level is taken from z coordinate to guarantee physical spatial alignment
    df["level"] = df["z"]
    df["slot"] = parsed_df["slot"]

    return df[["location", "x", "y", "z", "aisle", "bay", "level", "slot"]]


def build_orders_clean(df_orders: pd.DataFrame) -> pd.DataFrame:
    """Build orders_clean table."""
    df = df_orders.copy()
    df["size_decoded"] = decode_size_series(df["size_raw"])

    # Build sku_size identifier: "REF|SIZE"
    size_str = df["size_decoded"].apply(lambda s: f"{s:.1f}" if pd.notna(s) else "NA")
    df["sku_size"] = df["reference"] + "|" + size_str

    df["date"] = df["created_at"].dt.date
    df["hour"] = df["created_at"].dt.hour
    df["weekday"] = df["created_at"].dt.weekday  # 0=Monday, 6=Sunday

    cols = [
        "customer_code",
        "order_number",
        "order_to_collect",
        "reference",
        "size_raw",
        "size_decoded",
        "sku_size",
        "qty",
        "created_at",
        "date",
        "hour",
        "weekday",
        "wave_number",
        "operator",
    ]
    return df[cols]


def build_picks_clean(df_picks: pd.DataFrame, df_locations: pd.DataFrame) -> pd.DataFrame:
    """Build picks_clean table joined with coordinates and aisle metadata."""
    df = df_picks.copy()
    df["size_decoded"] = decode_size_series(df["size_raw"])

    size_str = df["size_decoded"].apply(lambda s: f"{s:.1f}" if pd.notna(s) else "NA")
    df["sku_size"] = df["reference"] + "|" + size_str

    # Join with Storage_Location on location code
    loc_sub = df_locations[["location", "x", "y", "z"]].drop_duplicates(subset=["location"])
    df = df.merge(loc_sub, on="location", how="left")

    # Parse aisle, bay, level, slot from location code
    parsed = df["location"].apply(parse_location).tolist()
    parsed_df = pd.DataFrame(parsed, index=df.index)

    df["aisle"] = parsed_df["aisle"]
    df["bay"] = parsed_df["bay"]
    df["level"] = df["z"].fillna(parsed_df["level"])
    df["slot"] = parsed_df["slot"]

    cols = [
        "wave_number",
        "reference",
        "size_raw",
        "size_decoded",
        "sku_size",
        "qty",
        "location",
        "x",
        "y",
        "z",
        "aisle",
        "bay",
        "level",
        "slot",
        "operator",
    ]
    return df[cols]


def build_waves(df_orders_clean: pd.DataFrame, df_picks_clean: pd.DataFrame) -> pd.DataFrame:
    """Build waves summary table reconciling order releases with pick travel stops."""
    # Aggregations from orders
    orders_agg = df_orders_clean.groupby("wave_number").agg(
        first_created_at=("created_at", "min"),
        last_created_at=("created_at", "max"),
        n_orders=("order_number", "nunique"),
        n_lines=("order_number", "count"),
        n_units_ordered=("qty", "sum"),
        order_operator=("operator", "first"),
    )

    # Aggregations from picks
    picks_agg = df_picks_clean.groupby("wave_number").agg(
        n_picks=("qty", "count"),
        n_units_picked=("qty", "sum"),
        n_distinct_locations=("location", "nunique"),
        n_aisles=("aisle", "nunique"),
        pick_operator=("operator", "first"),
    )

    # Outer join to capture all waves
    waves_df = orders_agg.join(picks_agg, how="outer").reset_index()
    waves_df = waves_df.rename(columns={"wave_number": "wave_id"})

    waves_df["n_units"] = waves_df["n_units_picked"].fillna(waves_df["n_units_ordered"]).fillna(0).astype(int)
    waves_df["operator"] = waves_df["pick_operator"].fillna(waves_df["order_operator"])
    waves_df["date"] = waves_df["first_created_at"].dt.date

    cols = [
        "wave_id",
        "first_created_at",
        "last_created_at",
        "n_orders",
        "n_lines",
        "n_units",
        "n_distinct_locations",
        "n_aisles",
        "operator",
        "date",
    ]
    return waves_df[cols]


def build_daily(
    df_orders_clean: pd.DataFrame,
    df_picks_clean: pd.DataFrame,
    df_waves: pd.DataFrame,
) -> pd.DataFrame:
    """Build calendar daily table including zero-activity weekend/holiday days."""
    min_date = df_orders_clean["date"].dropna().min()
    max_date = df_orders_clean["date"].dropna().max()
    full_calendar = pd.date_range(min_date, max_date, freq="D").date

    # Daily orders aggregations
    daily_orders = df_orders_clean.groupby("date").agg(
        orders=("order_number", "nunique"),
        lines=("order_number", "count"),
        units=("qty", "sum"),
    )

    # Daily waves aggregations
    daily_waves = df_waves.groupby("date").agg(
        waves=("wave_id", "nunique"),
        active_operators=("operator", "nunique"),
    )

    merged = daily_orders.join(daily_waves, how="outer")

    # Reindex over full continuous calendar range to ensure zero days are captured
    calendar_df = pd.DataFrame(index=pd.Index(full_calendar, name="date"))
    daily_full = calendar_df.join(merged, how="left").fillna(0)

    daily_full = daily_full.reset_index()
    for col in ["orders", "lines", "units", "waves", "active_operators"]:
        daily_full[col] = daily_full[col].astype(int)

    return daily_full[["date", "orders", "lines", "units", "waves", "active_operators"]]


def build_hourly(
    df_orders_clean: pd.DataFrame,
    df_picks_clean: pd.DataFrame,
) -> pd.DataFrame:
    """Build hourly table with date and hour metrics."""
    hourly_df = df_orders_clean.groupby(["date", "hour"]).agg(
        orders=("order_number", "nunique"),
        lines=("order_number", "count"),
        units=("qty", "sum"),
        waves=("wave_number", "nunique"),
        active_operators=("operator", "nunique"),
    ).reset_index()

    for col in ["orders", "lines", "units", "waves", "active_operators"]:
        hourly_df[col] = hourly_df[col].astype(int)

    return hourly_df[["date", "hour", "orders", "lines", "units", "waves", "active_operators"]]


def build_storage_long(storage_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate storage policies in long format with decoded sizes."""
    dfs = []
    for policy_name, df_storage in storage_dfs.items():
        sub = df_storage.copy()
        sub["size_decoded"] = decode_size_series(sub["size_raw"])
        size_str = sub["size_decoded"].apply(lambda s: f"{s:.1f}" if pd.notna(s) else "NA")
        sub["sku_size"] = sub["reference"] + "|" + size_str
        dfs.append(sub)

    combined = pd.concat(dfs, ignore_index=True)
    cols = [
        "location",
        "slot_index",
        "reference",
        "size_raw",
        "size_decoded",
        "sku_size",
        "class_code",
        "policy",
    ]
    return combined[cols]

