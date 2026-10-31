"""Unit tests for ABC-XYZ classification models."""

from __future__ import annotations

import pandas as pd
import pytest

from warehouse_ai.models.classification import (
    audit_catalog_abc,
    compute_abc,
    compute_abc_xyz,
    compute_xyz,
)


@pytest.fixture
def sample_orders_df() -> pd.DataFrame:
    # 5 products with known distribution:
    # prod_1: 80 units (A)
    # prod_2: 15 units (B)
    # prod_3: 3 units (C)
    # prod_4: 1 unit (C)
    # prod_5: 1 unit (C)
    # Total = 100 units
    rows = []
    dates = pd.date_range("2023-01-02", periods=10, freq="W-MON")
    for d in dates:
        rows.append({"reference": "prod_1", "date": d, "qty": 8})  # steady CV=0 -> X
        rows.append({"reference": "prod_2", "date": d, "qty": 1.5})
    # Spiky intermittent
    rows.append({"reference": "prod_3", "date": dates[0], "qty": 3})  # one spike -> Z
    rows.append({"reference": "prod_4", "date": dates[1], "qty": 1})
    rows.append({"reference": "prod_5", "date": dates[2], "qty": 1})
    return pd.DataFrame(rows)


def test_compute_abc(sample_orders_df):
    abc = compute_abc(sample_orders_df, entity_col="reference")
    assert len(abc) == 5
    p1 = abc[abc["reference"] == "prod_1"].iloc[0]
    assert p1["abc_class"] == "A"
    assert p1["total_units"] == 80.0

    p2 = abc[abc["reference"] == "prod_2"].iloc[0]
    assert p2["abc_class"] == "B"

    tail = abc[abc["reference"].isin(["prod_3", "prod_4", "prod_5"])]
    assert set(tail["abc_class"]) == {"C"}


def test_compute_xyz(sample_orders_df):
    xyz = compute_xyz(sample_orders_df, entity_col="reference")
    p1 = xyz[xyz["reference"] == "prod_1"].iloc[0]
    # prod_1 had 8 units every single week -> CV = 0.0 -> X
    assert p1["xyz_class"] == "X"
    assert p1["cv"] < 0.1

    p3 = xyz[xyz["reference"] == "prod_3"].iloc[0]
    # prod_3 had 1 spike and 9 zeros -> CV > 1.0 -> Z
    assert p3["xyz_class"] == "Z"


def test_compute_abc_xyz(sample_orders_df):
    matrix = compute_abc_xyz(sample_orders_df, entity_col="reference")
    p1 = matrix[matrix["reference"] == "prod_1"].iloc[0]
    assert p1["abc_xyz"] == "AX"
    assert "strategy" in p1


def test_audit_catalog_abc(sample_orders_df):
    # Catalog claims prod_1 is C, prod_3 is A
    prods = pd.DataFrame({
        "reference": ["prod_1", "prod_2", "prod_3", "prod_4", "prod_5"],
        "abc": ["C", "B", "A", "C", "C"],
    })
    audit = audit_catalog_abc(sample_orders_df, prods)
    assert audit["total_skus"] == 5
    assert audit["agreement_rate"] < 1.0
    assert audit["hidden_fast_movers_count"] == 1  # prod_1
    assert audit["obsolete_fast_movers_count"] == 1  # prod_3

