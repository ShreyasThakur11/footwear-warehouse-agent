"""Unit tests for models/anomaly.py — operational anomaly detection and exceptions."""

from __future__ import annotations

import pandas as pd
import pytest

from warehouse_ai.models.anomaly import (
    ExceptionRecord,
    check_forecast_breaches,
    check_operator_productivity_outliers,
    check_policy_location_mismatch,
    check_short_and_over_picks,
    check_unknown_master_data,
    detect_wave_statistical_anomalies,
    exceptions_to_dataframe,
)


@pytest.fixture
def sample_orders_and_picks():
    """Toy orders and picks with intentional discrepancies."""
    orders = pd.DataFrame([
        {"wave_number": 1, "sku_size": "BOOT_A|10.0", "reference": "BOOT_A", "qty": 10, "date": "2023-01-05"},
        {"wave_number": 1, "sku_size": "BOOT_B|9.0", "reference": "BOOT_B", "qty": 5, "date": "2023-01-05"},
        {"wave_number": 2, "sku_size": "BOOT_C|8.5", "reference": "UNKNOWN_REF", "qty": 4, "date": "2023-01-05"},
    ])
    picks = pd.DataFrame([
        {"wave_number": 1, "sku_size": "BOOT_A|10.0", "reference": "BOOT_A", "qty": 8, "location": "A-01-11", "operator": "Op_1", "date": "2023-01-05"},
        {"wave_number": 1, "sku_size": "BOOT_B|9.0", "reference": "BOOT_B", "qty": 7, "location": "A-02-11", "operator": "Op_1", "date": "2023-01-05"},
        {"wave_number": 2, "sku_size": "BOOT_C|8.5", "reference": "BOOT_C", "qty": 4, "location": "UNKNOWN_LOC", "operator": "Op_2", "date": "2023-01-05"},
    ])
    return orders, picks


@pytest.fixture
def sample_master_data():
    """Toy products, locations, and storage tables."""
    products = pd.DataFrame([
        {"reference": "BOOT_A", "abc": "A", "sector": "BOOTS"},
        {"reference": "BOOT_B", "abc": "B", "sector": "BOOTS"},
        {"reference": "BOOT_C", "abc": "C", "sector": "BOOTS"},
    ])
    locations = pd.DataFrame([
        {"location": "A-01-11", "x": 100.0, "y": 100.0, "z": 1.0, "aisle": "A", "bay": 1, "level": 1},
        {"location": "A-02-11", "x": 100.0, "y": 200.0, "z": 1.0, "aisle": "A", "bay": 2, "level": 1},
    ])
    storage = pd.DataFrame([
        {"policy": "random", "sku_size": "BOOT_A|10.0", "location": "A-01-11"},
        {"policy": "random", "sku_size": "BOOT_B|9.0", "location": "A-01-11"},  # Note: A-02-11 not assigned to BOOT_B
    ])
    return products, locations, storage


def test_exception_record_dataclass():
    rec = ExceptionRecord(
        type="TEST_TYPE",
        entity="ENTITY_1",
        date="2023-01-05",
        severity="HIGH",
        evidence="Some evidence",
        suggested_action="Some action",
    )
    d = rec.to_dict()
    assert d["type"] == "TEST_TYPE"
    assert d["severity"] == "HIGH"


def test_check_short_and_over_picks(sample_orders_and_picks):
    orders, picks = sample_orders_and_picks
    records = check_short_and_over_picks(orders, picks)
    assert len(records) == 2

    types = {r.type for r in records}
    assert "SHORT_PICK" in types
    assert "OVER_PICK" in types


def test_check_policy_location_mismatch(sample_orders_and_picks, sample_master_data):
    _, picks = sample_orders_and_picks
    _, _, storage = sample_master_data
    records = check_policy_location_mismatch(picks, storage, policy="random")

    # BOOT_B|9.0 was picked at A-02-11 but storage has it at A-01-11
    # BOOT_C|8.5 was picked at UNKNOWN_LOC
    assert len(records) >= 1
    entities = [r.entity for r in records]
    assert any("BOOT_B|9.0@A-02-11" in e for e in entities)


def test_check_unknown_master_data(sample_orders_and_picks, sample_master_data):
    orders, picks = sample_orders_and_picks
    products, locations, _ = sample_master_data
    records = check_unknown_master_data(picks, orders, products, locations)

    types = [r.type for r in records]
    entities = [r.entity for r in records]
    assert "UNKNOWN_REFERENCE" in types
    assert "UNKNOWN_REF" in entities
    assert "UNKNOWN_LOCATION" in types
    assert "UNKNOWN_LOC" in entities


def test_check_forecast_breaches():
    daily_df = pd.DataFrame([
        {"date": "2023-01-05", "units": 100},
        {"date": "2023-01-06", "units": 5000},  # Surge
        {"date": "2023-01-07", "units": 2},     # Drop
    ])
    p10_p90_df = pd.DataFrame([
        {"date": "2023-01-05", "p10": 80, "p90": 150},
        {"date": "2023-01-06", "p10": 100, "p90": 200},
        {"date": "2023-01-07", "p10": 50, "p90": 120},
    ])
    records = check_forecast_breaches(daily_df, p10_p90_df)
    assert len(records) == 2
    types = {r.type for r in records}
    assert "DEMAND_SURGE_BREACH" in types
    assert "DEMAND_DROP_BREACH" in types


def test_check_operator_productivity_outliers():
    picks = pd.DataFrame([
        {"date": "2023-01-05", "operator": "Op_1", "qty": 100},
        {"date": "2023-01-05", "operator": "Op_2", "qty": 110},
        {"date": "2023-01-05", "operator": "Op_3", "qty": 105},
        {"date": "2023-01-05", "operator": "Op_Slow", "qty": 10},   # Outlier low
        {"date": "2023-01-05", "operator": "Op_Fast", "qty": 600},  # Outlier high (>500)
    ])
    records = check_operator_productivity_outliers(picks)
    types = {r.type for r in records}
    assert "OPERATOR_PRODUCTIVITY_LOW" in types
    assert "OPERATOR_PRODUCTIVITY_HIGH" in types


def test_detect_wave_statistical_anomalies():
    # 30 waves with 1 extreme outlier
    records_data = []
    for i in range(30):
        records_data.append({
            "wave_id": i + 1,
            "date": "2023-01-05",
            "n_units": 24,
            "n_distinct_locations": 18,
            "travel_dist": 1500.0,
            "n_aisles": 5,
        })
    # Extreme outlier wave
    records_data.append({
        "wave_id": 999,
        "date": "2023-01-05",
        "n_units": 250,
        "n_distinct_locations": 150,
        "travel_dist": 45000.0,
        "n_aisles": 17,
    })
    waves_df = pd.DataFrame(records_data)
    records = detect_wave_statistical_anomalies(waves_df, contamination=0.03)
    assert len(records) >= 1
    entities = [r.entity for r in records]
    assert "Wave_999" in entities


def test_exceptions_to_dataframe():
    rec = ExceptionRecord(
        type="TEST", entity="E", date="2023-01-01", severity="LOW", evidence="Ev", suggested_action="Act"
    )
    df = exceptions_to_dataframe([rec])
    assert len(df) == 1
    assert list(df.columns) == ["type", "entity", "date", "severity", "evidence", "suggested_action"]
