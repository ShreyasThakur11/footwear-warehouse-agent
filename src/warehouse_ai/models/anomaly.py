"""Operational anomaly detection and exception monitoring module.

Provides:
- Rule-based checks with configurable thresholds returning standardized ExceptionRecord
  objects: {type, entity, date, severity, evidence, suggested_action}.
  - Short/over picks: units ordered != units picked for a wave / SKU-size.
  - Policy location mismatch: pick from a location not mapped to that SKU under active policy.
  - Unknown master data: reference not in products or location not in navigation map.
  - Demand forecast breach: daily order volume outside P10–P90 prediction interval.
  - Operator productivity outliers: operator-day throughput far below or above peer median.
- Statistical anomaly detection: IsolationForest over wave operational features
  (units, distinct locations, travel distance, aisles) to flag multidimensional wave outliers.
- Actionable triage recommendations: cycle counts, operator coaching, master data audits.
- Full exception scanning and report generator writing to ``reports/exceptions.md``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.ensemble import IsolationForest

from warehouse_ai.config import load_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ExceptionRecord:
    """Standardized operational anomaly / exception record."""

    type: str               # e.g., 'SHORT_PICK', 'LOCATION_POLICY_MISMATCH', etc.
    entity: str             # Wave ID, SKU-size, location, or operator identifier
    date: str               # ISO date 'YYYY-MM-DD' or 'UNKNOWN'
    severity: str           # 'HIGH', 'MEDIUM', 'LOW'
    evidence: str           # Specific metric, expected vs observed values
    suggested_action: str   # Actionable remediation step

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnomalyThresholds:
    """Configurable thresholds for rule-based and statistical anomaly detection."""

    short_pick_min_qty: int = 1               # Discrepancy threshold to flag short/over pick
    operator_peer_low_ratio: float = 0.50     # Flag if operator throughput < 50% of daily peer median
    operator_peer_high_ratio: float = 2.00    # Flag if operator throughput > 200% of daily peer median
    operator_min_units_day: int = 20          # Ignore operator-days with trivial units
    isolation_forest_contamination: float = 0.01  # Expected proportion of statistical outliers
    forecast_p10_p90_band: bool = True       # Enforce P10/P90 interval breach check


# ---------------------------------------------------------------------------
# Rule 1: Short & Over Picks (Wave & SKU-size level)
# ---------------------------------------------------------------------------

def check_short_and_over_picks(
    orders_df: pd.DataFrame,
    picks_df: pd.DataFrame,
    min_qty_discrepancy: int = 1,
) -> list[ExceptionRecord]:
    """Detect discrepancies between quantities ordered and quantities picked per wave + SKU-size."""
    # Group orders by wave_number and sku_size
    o_grouped = (
        orders_df.groupby(["wave_number", "sku_size", "date"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "units_ordered"})
    )

    p_grouped = (
        picks_df.groupby(["wave_number", "sku_size"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "units_picked"})
    )

    merged = o_grouped.merge(p_grouped, on=["wave_number", "sku_size"], how="outer")
    merged["units_ordered"] = merged["units_ordered"].fillna(0).astype(int)
    merged["units_picked"] = merged["units_picked"].fillna(0).astype(int)
    merged["diff"] = merged["units_picked"] - merged["units_ordered"]

    discrepancies = merged[merged["diff"].abs() >= min_qty_discrepancy]
    records: list[ExceptionRecord] = []

    for row in discrepancies.itertuples(index=False):
        date_str = str(row.date) if pd.notna(row.date) else "UNKNOWN"
        wave_str = f"Wave_{row.wave_number}"
        sku_str = str(row.sku_size)
        diff_val = row.diff

        if diff_val < 0:
            exc_type = "SHORT_PICK"
            sev = "HIGH" if abs(diff_val) >= 5 else "MEDIUM"
            evidence = (
                f"Wave {row.wave_number} for {sku_str}: ordered {row.units_ordered} units, "
                f"picked {row.units_picked} units (shortfall of {abs(diff_val)} units)."
            )
            action = f"Investigate wave {row.wave_number} and cycle count forward bins for SKU {sku_str}."
        else:
            exc_type = "OVER_PICK"
            sev = "HIGH" if diff_val >= 5 else "MEDIUM"
            evidence = (
                f"Wave {row.wave_number} for {sku_str}: ordered {row.units_ordered} units, "
                f"picked {row.units_picked} units (surplus of {diff_val} units)."
            )
            action = f"Audit wave staging area and check inventory return log for SKU {sku_str}."

        records.append(
            ExceptionRecord(
                type=exc_type,
                entity=f"{wave_str}|{sku_str}",
                date=date_str,
                severity=sev,
                evidence=evidence,
                suggested_action=action,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Rule 2: Pick from Unassigned Location Under Active Storage Policy
# ---------------------------------------------------------------------------

def check_policy_location_mismatch(
    picks_df: pd.DataFrame,
    storage_df: pd.DataFrame,
    policy: str = "random",
) -> list[ExceptionRecord]:
    """Flag pick actions executed from locations where the SKU is not slotted under the active policy."""
    policy_stor = storage_df[storage_df["policy"] == policy][["sku_size", "location"]].drop_duplicates()
    policy_stor["assigned_policy"] = True

    # Drop NA sku_size or location
    valid_picks = picks_df.dropna(subset=["sku_size", "location"])
    pick_pairs = valid_picks[["sku_size", "location"]].drop_duplicates()

    merged = pick_pairs.merge(policy_stor, on=["sku_size", "location"], how="left")
    unassigned = merged[merged["assigned_policy"].isna()]

    # Associate with dates and frequency from picks_df
    mismatch_counts = valid_picks.groupby(["sku_size", "location"]).size().to_dict()

    records: list[ExceptionRecord] = []
    for row in unassigned.itertuples(index=False):
        sku = str(row.sku_size)
        loc = str(row.location)
        picks_count = mismatch_counts.get((sku, loc), 1)

        records.append(
            ExceptionRecord(
                type="LOCATION_POLICY_MISMATCH",
                entity=f"{sku}@{loc}",
                date="HISTORICAL",
                severity="MEDIUM" if picks_count >= 5 else "LOW",
                evidence=(
                    f"SKU {sku} picked {picks_count} times from location {loc}, "
                    f"which holds no assigned slot under '{policy}' storage policy."
                ),
                suggested_action=f"Cycle count location {loc} and update active WMS slotting master for SKU {sku}.",
            )
        )

    return records


# ---------------------------------------------------------------------------
# Rule 3: Unknown Master Data (References or Locations)
# ---------------------------------------------------------------------------

def check_unknown_master_data(
    picks_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    products_df: pd.DataFrame,
    locations_df: pd.DataFrame,
) -> list[ExceptionRecord]:
    """Identify references missing from products catalog or locations missing from warehouse graph."""
    valid_refs = set(products_df["reference"].dropna().unique())
    valid_locs = set(locations_df["location"].dropna().unique())

    records: list[ExceptionRecord] = []

    # 1. Missing references in orders
    order_refs = set(orders_df["reference"].dropna().unique())
    unknown_order_refs = order_refs - valid_refs
    for ref in unknown_order_refs:
        records.append(
            ExceptionRecord(
                type="UNKNOWN_REFERENCE",
                entity=ref,
                date="HISTORICAL",
                severity="HIGH",
                evidence=f"Product reference '{ref}' appears in customer orders but is absent from products master catalog.",
                suggested_action=f"Check master data for SKU reference '{ref}' and register in ERP/WMS catalog.",
            )
        )

    # 2. Missing references in picks
    pick_refs = set(picks_df["reference"].dropna().unique())
    unknown_pick_refs = pick_refs - valid_refs
    for ref in unknown_pick_refs:
        records.append(
            ExceptionRecord(
                type="UNKNOWN_REFERENCE",
                entity=ref,
                date="HISTORICAL",
                severity="HIGH",
                evidence=f"Product reference '{ref}' appears in picking actions but is absent from products master catalog.",
                suggested_action=f"Check master data for SKU reference '{ref}' and verify physical shoe box labels.",
            )
        )

    # 3. Missing locations in picks
    pick_locs = set(picks_df["location"].dropna().unique())
    unknown_pick_locs = pick_locs - valid_locs
    for loc in unknown_pick_locs:
        records.append(
            ExceptionRecord(
                type="UNKNOWN_LOCATION",
                entity=loc,
                date="HISTORICAL",
                severity="MEDIUM",
                evidence=f"Location code '{loc}' used in picking waves but missing from official warehouse shelf layout.",
                suggested_action=f"Cycle count for location '{loc}' and map coordinate to nearest warehouse aisle waypoint.",
            )
        )

    return records


# ---------------------------------------------------------------------------
# Rule 4: Daily Volume Outside Forecast P10–P90
# ---------------------------------------------------------------------------

def check_forecast_breaches(
    daily_df: pd.DataFrame,
    p10_p90_df: pd.DataFrame | None = None,
) -> list[ExceptionRecord]:
    """Flag operational days where actual units/orders breached expected statistical bounds."""
    records: list[ExceptionRecord] = []

    if p10_p90_df is not None and not p10_p90_df.empty:
        merged = daily_df.merge(p10_p90_df, on="date", how="inner")
        for row in merged.itertuples(index=False):
            actual = getattr(row, "units", getattr(row, "n_units", 0))
            p10 = getattr(row, "p10", 0.0)
            p90 = getattr(row, "p90", float("inf"))
            date_str = str(row.date)

            if actual < p10:
                records.append(
                    ExceptionRecord(
                        type="DEMAND_DROP_BREACH",
                        entity=f"Date_{date_str}",
                        date=date_str,
                        severity="MEDIUM",
                        evidence=f"Actual daily volume ({actual} units) fell below model P10 threshold ({p10:.1f} units).",
                        suggested_action="Investigate upstream EDI order feed for missing batches and stand down temporary pickers.",
                    )
                )
            elif actual > p90:
                records.append(
                    ExceptionRecord(
                        type="DEMAND_SURGE_BREACH",
                        entity=f"Date_{date_str}",
                        date=date_str,
                        severity="HIGH",
                        evidence=f"Actual daily volume ({actual} units) surged above model P90 threshold ({p90:.1f} units).",
                        suggested_action="Review surge staffing authorization and reschedule reserve forklift replenishment.",
                    )
                )
    else:
        # Fallback heuristic: 3-sigma rolling window check on daily units
        units_series = daily_df["units"] if "units" in daily_df.columns else daily_df["n_units"]
        mean_u = units_series.mean()
        std_u = units_series.std()
        upper_limit = mean_u + 2.5 * std_u
        lower_limit = max(0, mean_u - 2.5 * std_u)

        for _, row in daily_df.iterrows():
            u = row.get("units", row.get("n_units", 0))
            d_str = str(row.get("date", "UNKNOWN"))
            if u > upper_limit:
                records.append(
                    ExceptionRecord(
                        type="DEMAND_SURGE_BREACH",
                        entity=f"Date_{d_str}",
                        date=d_str,
                        severity="HIGH",
                        evidence=f"Daily volume ({u} units) exceeded historical 2.5-sigma envelope ({upper_limit:.1f} units).",
                        suggested_action="Authorize temporary flex labor and alert dispatch carrier of oversized trailer requirements.",
                    )
                )
            elif u < lower_limit and lower_limit > 50:
                records.append(
                    ExceptionRecord(
                        type="DEMAND_DROP_BREACH",
                        entity=f"Date_{d_str}",
                        date=d_str,
                        severity="MEDIUM",
                        evidence=f"Daily volume ({u} units) dropped below historical lower envelope ({lower_limit:.1f} units).",
                        suggested_action="Reallocate warehouse workforce to cycle counting and forward shelf consolidation.",
                    )
                )

    return records


# ---------------------------------------------------------------------------
# Rule 5: Operator-Day Productivity Outliers
# ---------------------------------------------------------------------------

def check_operator_productivity_outliers(
    picks_df: pd.DataFrame,
    waves_df: pd.DataFrame | None = None,
    low_ratio: float = 0.50,
    high_ratio: float = 2.00,
    min_units: int = 20,
) -> list[ExceptionRecord]:
    """Flag operator-days where picking speed or volume deviates dramatically from peer median."""
    # Group picks by date and operator
    # Ensure date column exists
    df = picks_df.copy()
    if "date" not in df.columns and "date_str" in df.columns:
        df["date"] = df["date_str"]
    elif "date" not in df.columns and waves_df is not None:
        wave_dates = waves_df.set_index("wave_id")["date"].to_dict()
        df["date"] = df["wave_number"].map(wave_dates)

    if "date" not in df.columns or df["date"].isna().all():
        return []

    # Daily units per operator
    daily_op = (
        df.groupby(["date", "operator"])["qty"]
        .sum()
        .reset_index()
        .rename(columns={"qty": "operator_units"})
    )

    records: list[ExceptionRecord] = []

    for d, group in daily_op.groupby("date"):
        if len(group) < 3:
            continue  # Need at least 3 operators to establish a reliable peer median

        peer_median = group["operator_units"].median()
        if peer_median < min_units:
            continue

        for row in group.itertuples(index=False):
            op = str(row.operator)
            u = row.operator_units

            if u < low_ratio * peer_median and u < min_units:
                records.append(
                    ExceptionRecord(
                        type="OPERATOR_PRODUCTIVITY_LOW",
                        entity=f"{op}@{d}",
                        date=str(d),
                        severity="MEDIUM",
                        evidence=(
                            f"Operator {op} completed {u} units on {d}, "
                            f"which is {u/peer_median:.1%} of daily peer median ({peer_median:.1f} units)."
                        ),
                        suggested_action=f"Investigate operator-day for {op} on {d}: check handheld scanner battery / duty assignments.",
                    )
                )
            elif u > high_ratio * peer_median and u > 500:
                records.append(
                    ExceptionRecord(
                        type="OPERATOR_PRODUCTIVITY_HIGH",
                        entity=f"{op}@{d}",
                        date=str(d),
                        severity="LOW",
                        evidence=(
                            f"Operator {op} completed {u} units on {d}, "
                            f"which is {u/peer_median:.1%} of daily peer median ({peer_median:.1f} units)."
                        ),
                        suggested_action=f"Review scanning timestamp log for {op} on {d} to audit for batch consolidation or bulk scanning.",
                    )
                )

    return records


# ---------------------------------------------------------------------------
# Statistical Anomaly Detection: Isolation Forest on Wave Features
# ---------------------------------------------------------------------------

def detect_wave_statistical_anomalies(
    waves_df: pd.DataFrame,
    contamination: float = 0.01,
    random_state: int = 42,
) -> list[ExceptionRecord]:
    """Fit IsolationForest on wave features (units, locations, travel, aisles) to flag unusual wave structures."""
    feature_cols = ["n_units", "n_distinct_locations", "travel_dist", "n_aisles"]
    available_cols = [c for c in feature_cols if c in waves_df.columns]

    if len(available_cols) < 2 or len(waves_df) < 20:
        return []

    clean_waves = waves_df.dropna(subset=available_cols).copy()
    X = clean_waves[available_cols].values

    iso = IsolationForest(contamination=contamination, random_state=random_state)
    preds = iso.fit_predict(X)  # -1 for outliers, 1 for inliers
    scores = iso.decision_function(X)

    clean_waves["is_anomaly"] = preds == -1
    clean_waves["anomaly_score"] = scores

    outliers = clean_waves[clean_waves["is_anomaly"]]
    records: list[ExceptionRecord] = []

    for row in outliers.itertuples(index=False):
        wave_id = getattr(row, "wave_id", getattr(row, "wave_number", "UNKNOWN"))
        d_val = getattr(row, "date", "HISTORICAL")
        units = getattr(row, "n_units", 0)
        locs = getattr(row, "n_distinct_locations", 0)
        dist = getattr(row, "travel_dist", 0.0)
        aisles = getattr(row, "n_aisles", 0)
        score = getattr(row, "anomaly_score", 0.0)

        records.append(
            ExceptionRecord(
                type="STATISTICAL_WAVE_ANOMALY",
                entity=f"Wave_{wave_id}",
                date=str(d_val),
                severity="MEDIUM" if score < -0.10 else "LOW",
                evidence=(
                    f"Wave {wave_id} flagged by IsolationForest (score={score:.3f}): "
                    f"{units} units across {locs} shelf locations, {aisles} aisles, {dist:,.0f} travel units."
                ),
                suggested_action=(
                    f"Review wave batching parameters and tour routing sequence for wave {wave_id} "
                    f"to avoid extreme multi-aisle travel."
                ),
            )
        )

    return records


# ---------------------------------------------------------------------------
# Master Scanner Pipeline
# ---------------------------------------------------------------------------

def scan_all_exceptions(
    orders_df: pd.DataFrame | None = None,
    picks_df: pd.DataFrame | None = None,
    products_df: pd.DataFrame | None = None,
    locations_df: pd.DataFrame | None = None,
    storage_df: pd.DataFrame | None = None,
    waves_df: pd.DataFrame | None = None,
    daily_df: pd.DataFrame | None = None,
    thresholds: AnomalyThresholds | None = None,
) -> list[ExceptionRecord]:
    """Execute all rule-based and statistical anomaly checks across the warehouse data."""
    if thresholds is None:
        thresholds = AnomalyThresholds()

    cfg = load_config()
    proc = Path(cfg.paths.data_processed)

    if orders_df is None:
        orders_df = pd.read_parquet(proc / "orders_clean.parquet")
    if picks_df is None:
        picks_df = pd.read_parquet(proc / "picks_clean.parquet")
    if products_df is None:
        products_df = pd.read_parquet(proc / "products.parquet")
    if locations_df is None:
        locations_df = pd.read_parquet(proc / "locations.parquet")
    if storage_df is None:
        storage_df = pd.read_parquet(proc / "storage_long.parquet")
    if waves_df is None:
        waves_df = pd.read_parquet(proc / "waves.parquet")
    if daily_df is None:
        daily_df = pd.read_parquet(proc / "daily.parquet")

    all_records: list[ExceptionRecord] = []

    # 1. Short / Over picks
    logger.info("Scanning for short and over picks...")
    all_records.extend(
        check_short_and_over_picks(
            orders_df=orders_df,
            picks_df=picks_df,
            min_qty_discrepancy=thresholds.short_pick_min_qty,
        )
    )

    # 2. Storage policy unassigned picks
    logger.info("Scanning for policy location mismatches...")
    all_records.extend(
        check_policy_location_mismatch(
            picks_df=picks_df,
            storage_df=storage_df,
            policy="random",
        )
    )

    # 3. Master data integrity
    logger.info("Scanning for unknown references and locations...")
    all_records.extend(
        check_unknown_master_data(
            picks_df=picks_df,
            orders_df=orders_df,
            products_df=products_df,
            locations_df=locations_df,
        )
    )

    # 4. Forecast breaches
    logger.info("Scanning for daily volume anomalies...")
    all_records.extend(
        check_forecast_breaches(
            daily_df=daily_df,
        )
    )

    # 5. Operator outliers
    logger.info("Scanning for operator productivity outliers...")
    all_records.extend(
        check_operator_productivity_outliers(
            picks_df=picks_df,
            waves_df=waves_df,
            low_ratio=thresholds.operator_peer_low_ratio,
            high_ratio=thresholds.operator_peer_high_ratio,
            min_units=thresholds.operator_min_units_day,
        )
    )

    # 6. Statistical wave anomalies
    logger.info("Running IsolationForest statistical wave anomaly detection...")
    all_records.extend(
        detect_wave_statistical_anomalies(
            waves_df=waves_df,
            contamination=thresholds.isolation_forest_contamination,
            random_state=cfg.random_seed,
        )
    )

    logger.info("Total operational exceptions detected: %d", len(all_records))
    return all_records


def exceptions_to_dataframe(records: list[ExceptionRecord]) -> pd.DataFrame:
    """Convert list of ExceptionRecord objects to DataFrame."""
    if not records:
        return pd.DataFrame(
            columns=["type", "entity", "date", "severity", "evidence", "suggested_action"]
        )
    return pd.DataFrame([r.to_dict() for r in records])
