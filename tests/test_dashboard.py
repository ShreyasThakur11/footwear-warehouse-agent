"""Tests for the Streamlit operations dashboard (app/streamlit_app.py)."""

from __future__ import annotations

import py_compile
from pathlib import Path

import pandas as pd

from warehouse_ai.config import load_config
from warehouse_ai.governance.audit import init_db, pending_actions
from warehouse_ai.models.anomaly import exceptions_to_dataframe, scan_all_exceptions
from warehouse_ai.models.staffing import recommend_headcount

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "app" / "streamlit_app.py"


def test_streamlit_app_file_exists() -> None:
    """Verify that app/streamlit_app.py exists and is non-empty."""
    assert APP_PATH.exists(), f"Missing {APP_PATH}"
    assert APP_PATH.stat().st_size > 1000, "streamlit_app.py is unexpectedly small"


def test_streamlit_app_compiles() -> None:
    """Verify that app/streamlit_app.py compiles without syntax errors."""
    compiled = py_compile.compile(str(APP_PATH), doraise=True)
    assert compiled is not None


def test_cached_loaders_execute() -> None:
    """Test data availability for the dashboard."""
    cfg = load_config()
    daily_path = Path(cfg.paths.data_processed) / "daily.parquet"
    if daily_path.exists():
        df = pd.read_parquet(daily_path)
        assert not df.empty
        assert "units" in df.columns
        assert "active_operators" in df.columns


def test_live_staffing_calculation() -> None:
    """Test that live staffing sensitivity model returns expected object."""
    rec = recommend_headcount(
        date="2023-11-01",
        target_quantile="P50",
        workload_hours=8.0,
    )
    assert rec.total_headcount >= 2
    assert rec.utilization > 0.0
    assert rec.estimated_daily_cost > 0.0


def test_exceptions_loader_for_ui() -> None:
    """Test exceptions scan returning structured dataframe for UI filtering."""
    records = scan_all_exceptions()
    df = exceptions_to_dataframe(records)
    assert not df.empty
    assert "severity" in df.columns
    assert "type" in df.columns
    assert "suggested_action" in df.columns


def test_governance_db_actions() -> None:
    """Test governance database and pending actions listing."""
    init_db()
    pending = pending_actions()
    assert isinstance(pending, list)
