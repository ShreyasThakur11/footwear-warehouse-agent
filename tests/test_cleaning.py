from pathlib import Path

import numpy as np

from warehouse_ai.data.cleaning import (
    build_orders_clean,
    build_picks_clean,
    build_waves,
    decode_size,
    parse_location,
)
from warehouse_ai.data.loaders import load_locations, load_orders, load_picks

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_decode_size_whole():
    assert decode_size(9) == 9.0
    assert decode_size(10.0) == 10.0
    assert decode_size("12") == 12.0
    assert decode_size(1.0) == 1.0


def test_decode_size_half():
    assert decode_size(105) == 10.5
    assert decode_size(85.0) == 8.5
    assert decode_size(35) == 3.5
    assert decode_size(125) == 12.5
    assert decode_size("95") == 9.5
    assert decode_size("9.5") == 9.5


def test_decode_size_mm_and_special():
    assert decode_size(260.0) == 260.0
    assert decode_size(215) == 215.0
    assert decode_size(None) is None
    assert decode_size(np.nan) is None
    assert decode_size("") is None
    assert decode_size("invalid") is None


def test_parse_location_standard():
    res1 = parse_location("A-14-11")
    assert res1 == {"aisle": "A", "bay": 14, "level": 1, "slot": 1}

    res2 = parse_location("B-02-31")
    assert res2 == {"aisle": "B", "bay": 2, "level": 3, "slot": 1}

    res3 = parse_location("K-16-40")
    assert res3 == {"aisle": "K", "bay": 16, "level": 4, "slot": 0}


def test_parse_location_special():
    res = parse_location("ZN-COR")
    assert res["aisle"] == "ZN"
    assert res["bay"] is None

    res_empty = parse_location(None)
    assert res_empty["aisle"] is None


def test_fixture_wave_totals_reconciliation():
    orders_df = load_orders(FIXTURES_DIR / "Customer_Order.csv")
    picks_df = load_picks(FIXTURES_DIR / "Picking_Wave.csv")
    locations_df = load_locations(FIXTURES_DIR / "Storage_Location.csv")

    orders_clean = build_orders_clean(orders_df)
    picks_clean = build_picks_clean(picks_df, locations_df)
    waves = build_waves(orders_clean, picks_clean)

    assert not waves.empty
    # Wave 43175 is in the fixtures
    wave_43175 = waves[waves["wave_id"] == 43175].iloc[0]
    assert wave_43175["n_orders"] >= 1
    assert wave_43175["n_lines"] >= 1
    assert wave_43175["n_units"] == len(picks_df[picks_df["wave_number"] == 43175])
    assert wave_43175["n_distinct_locations"] == picks_df[picks_df["wave_number"] == 43175]["location"].nunique()
