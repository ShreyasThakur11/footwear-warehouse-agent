#!/usr/bin/env python3
"""Inspect all raw data files: shape, dtypes, head, null counts.

Usage
-----
    python scripts/inspect_data.py
    python scripts/inspect_data.py --raw-dir path/to/csv/folder
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the package is importable when running from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warehouse_ai.data.loaders import (
    load_locations,
    load_orders,
    load_picks,
    load_products,
    load_storage,
    load_support_points,
)


def _banner(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def inspect(raw_dir: str | None = None) -> None:
    """Load every raw file and print diagnostic info."""

    loaders = [
        ("Customer_Order (orders)", lambda: load_orders(Path(raw_dir) / "Customer_Order.csv" if raw_dir else None)),
        ("Picking_Wave (picks)",    lambda: load_picks(Path(raw_dir) / "Picking_Wave.csv" if raw_dir else None)),
        ("Product",                 lambda: load_products(Path(raw_dir) / "Product.csv" if raw_dir else None)),
        ("Storage_Location",        lambda: load_locations(Path(raw_dir) / "Storage_Location.csv" if raw_dir else None)),
        ("Random_Storage",          lambda: load_storage("random", Path(raw_dir) / "Random_Storage.csv" if raw_dir else None)),
        ("Class_Based_Storage",     lambda: load_storage("class_based", Path(raw_dir) / "Class_Based_Storage.csv" if raw_dir else None)),
        ("Dedicated_Storage",       lambda: load_storage("dedicated", Path(raw_dir) / "Dedicated_Storage.csv" if raw_dir else None)),
        ("Hybrid_Storage",          lambda: load_storage("hybrid", Path(raw_dir) / "Hybrid_Storage.csv" if raw_dir else None)),
        ("Support_Points",          lambda: load_support_points(Path(raw_dir) / "Support_Points_Navigation.csv" if raw_dir else None)),
    ]

    for name, loader_fn in loaders:
        _banner(name)
        try:
            df = loader_fn()
            print(f"Shape : {df.shape}")
            print(f"\nDtypes:\n{df.dtypes}")
            print(f"\nHead (5 rows):\n{df.head().to_string()}")
            print(f"\nNull counts:\n{df.isnull().sum()}")
        except Exception as exc:
            print(f"  ⚠ ERROR: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect raw warehouse CSV files.")
    parser.add_argument("--raw-dir", type=str, default=None, help="Path to folder with raw CSVs.")
    args = parser.parse_args()
    inspect(args.raw_dir)


if __name__ == "__main__":
    main()

