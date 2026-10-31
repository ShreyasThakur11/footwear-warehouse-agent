from pathlib import Path

import pandas as pd
import pytest

from warehouse_ai.data.loaders import (
    load_locations,
    load_orders,
    load_picks,
    load_products,
    load_storage,
    load_support_points,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_load_orders():
    path = FIXTURES_DIR / "Customer_Order.csv"
    df = load_orders(path)
    assert not df.empty
    expected_cols = [
        "customer_code",
        "order_number",
        "order_to_collect",
        "reference",
        "size_raw",
        "qty",
        "created_at",
        "wave_number",
        "operator",
    ]
    for col in expected_cols:
        assert col in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["created_at"])


def test_load_picks():
    path = FIXTURES_DIR / "Picking_Wave.csv"
    df = load_picks(path)
    assert not df.empty
    expected_cols = ["wave_number", "reference", "size_raw", "qty", "location", "operator"]
    for col in expected_cols:
        assert col in df.columns


def test_load_products():
    path = FIXTURES_DIR / "Product.csv"
    df = load_products(path)
    assert not df.empty
    assert list(df.columns) == ["reference", "abc_code", "sector"]


def test_load_locations():
    path = FIXTURES_DIR / "Storage_Location.csv"
    df = load_locations(path)
    assert not df.empty
    expected_cols = ["location", "position", "x", "y", "z"]
    for col in expected_cols:
        assert col in df.columns


@pytest.mark.parametrize("policy,fixture_name", [
    ("random", "Random_Storage.csv"),
    ("class_based", "Class_Based_Storage.csv"),
    ("dedicated", "Dedicated_Storage.csv"),
    ("hybrid", "Hybrid_Storage.csv"),
])
def test_load_storage(policy, fixture_name):
    path = FIXTURES_DIR / fixture_name
    df = load_storage(policy, path)
    assert not df.empty
    expected_cols = ["location", "slot_index", "reference", "size_raw", "class_code", "policy"]
    assert list(df.columns) == expected_cols
    assert (df["policy"] == policy).all()


def test_load_support_points():
    path = FIXTURES_DIR / "Support_Points_Navigation.csv"
    df = load_support_points(path)
    assert not df.empty
    assert list(df.columns) == ["label", "x", "y", "z"]
    assert len(df) == 44 or len(df) == 45
    # Verify corridor groups
    assert df["label"].str.startswith("LC-").any()
    assert df["label"].str.startswith("CC-").any()
    assert df["label"].str.startswith("RC-").any()
