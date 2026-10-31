#!/usr/bin/env python3
"""Build clean, validated Parquet tables in data/processed/.

Executes end-to-end data ingestion, size decoding, location syntax parsing,
and generates the data quality audit report (reports/data_quality.md).

Usage
-----
    python scripts/build_processed.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from warehouse_ai.config import get_config
from warehouse_ai.data.cleaning import (
    build_daily,
    build_hourly,
    build_locations,
    build_orders_clean,
    build_picks_clean,
    build_products,
    build_storage_long,
    build_waves,
)
from warehouse_ai.data.loaders import (
    load_locations,
    load_orders,
    load_picks,
    load_products,
    load_storage,
)
from warehouse_ai.data.validate import validate_data


def main() -> None:
    t0 = time.time()
    cfg = get_config()

    raw_dir = _ROOT / cfg.paths.data_raw
    processed_dir = _ROOT / cfg.paths.data_processed
    processed_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("  Footwear Warehouse Optimisation – Data Ingestion & Cleaning")
    print("=" * 72)
    print(f"Reading raw data from:       {raw_dir}")
    print(f"Writing Parquet tables to:   {processed_dir}\n")

    # 1. Ingest raw data
    print("--> [1/5] Ingesting raw CSV files...")
    orders_raw = load_orders()
    picks_raw = load_picks()
    products_raw = load_products()
    locations_raw = load_locations()

    storage_policies = {
        "random": load_storage("random"),
        "class_based": load_storage("class_based"),
        "dedicated": load_storage("dedicated"),
        "hybrid": load_storage("hybrid"),
    }
    print(f"    Loaded {len(orders_raw):,} orders, {len(picks_raw):,} picks, "
          f"{len(products_raw)} products, {len(locations_raw)} rack locations.")

    # 2. Build core entity tables
    print("\n--> [2/5] Building clean entity tables...")
    products = build_products(products_raw)
    products_path = processed_dir / "products.parquet"
    products.to_parquet(products_path, index=False)
    print(f"    [OK] products.parquet        shape: {products.shape}")

    locations = build_locations(locations_raw)
    locations_path = processed_dir / "locations.parquet"
    locations.to_parquet(locations_path, index=False)
    print(f"    [OK] locations.parquet       shape: {locations.shape}")

    storage_long = build_storage_long(storage_policies)
    storage_path = processed_dir / "storage_long.parquet"
    storage_long.to_parquet(storage_path, index=False)
    print(f"    [OK] storage_long.parquet     shape: {storage_long.shape}")

    # 3. Clean operational logs (orders & picks)
    print("\n--> [3/5] Cleaning operational logs & decoding footwear sizes...")
    orders_clean = build_orders_clean(orders_raw)
    orders_path = processed_dir / "orders_clean.parquet"
    orders_clean.to_parquet(orders_path, index=False)
    print(f"    [OK] orders_clean.parquet    shape: {orders_clean.shape}")

    picks_clean = build_picks_clean(picks_raw, locations_raw)
    picks_path = processed_dir / "picks_clean.parquet"
    picks_clean.to_parquet(picks_path, index=False)
    print(f"    [OK] picks_clean.parquet     shape: {picks_clean.shape}")

    # 4. Build analytical summaries (waves, daily, hourly)
    print("\n--> [4/5] Building wave, daily, and hourly aggregates...")
    waves = build_waves(orders_clean, picks_clean)
    waves_path = processed_dir / "waves.parquet"
    waves.to_parquet(waves_path, index=False)
    print(f"    [OK] waves.parquet           shape: {waves.shape}")

    daily = build_daily(orders_clean, picks_clean, waves)
    daily_path = processed_dir / "daily.parquet"
    daily.to_parquet(daily_path, index=False)
    print(f"    [OK] daily.parquet           shape: {daily.shape} (includes zero-demand days)")

    hourly = build_hourly(orders_clean, picks_clean)
    hourly_path = processed_dir / "hourly.parquet"
    hourly.to_parquet(hourly_path, index=False)
    print(f"    [OK] hourly.parquet          shape: {hourly.shape}")

    # 5. Validation suite
    print("\n--> [5/5] Running industrial validation suite...")
    report_file = _ROOT / "reports" / "data_quality.md"
    results = validate_data(orders_raw, picks_raw, products_raw, locations_raw, report_path=report_file)
    print(f"    [OK] Audit report generated at: {report_file}")
    print(f"    - Overlapping wave unit match rate: {results['waves_exact_unit_match_pct']}%")
    print(f"    - Total units picked:              {results['total_units_picked']:,}")
    print(f"    - Days with volume > 3-sigma:      {results['outliers_3std_count']}")

    elapsed = time.time() - t0
    print("\n" + "=" * 72)
    print(f"  Pipeline completed successfully in {elapsed:.2f} seconds!")
    print("=" * 72)


if __name__ == "__main__":
    main()
