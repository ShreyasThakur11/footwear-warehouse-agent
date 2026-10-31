"""Unit tests for src/warehouse_ai/agents/tools.py — tool registry and wrappers."""

from __future__ import annotations

from warehouse_ai.agents.tools import registry


def test_registry_has_all_required_tools():
    expected_tools = [
        "get_daily_forecast",
        "get_hourly_profile",
        "get_sku_size_forecast",
        "estimate_workload_hours",
        "recommend_headcount",
        "run_staffing_sensitivity",
        "get_replenishment_plan",
        "get_abc_xyz",
        "compare_storage_policies",
        "recommend_reslotting",
        "plan_waves",
        "list_exceptions",
        "query_data",
    ]
    all_registered = {t.name for t in registry.list_all()}
    for tool_name in expected_tools:
        assert tool_name in all_registered, f"Tool '{tool_name}' missing from registry."


def test_agent_tool_permissions():
    forecast_tools = {t.name for t in registry.get_for_agent("ForecastAgent")}
    assert "get_daily_forecast" in forecast_tools
    assert "query_data" in forecast_tools  # '*' allowed for all agents
    assert "recommend_reslotting" not in forecast_tools  # SlottingAgent only

    copilot_tools = {t.name for t in registry.get_for_agent("CopilotAgent")}
    # CopilotAgent has access to all tools
    assert len(copilot_tools) >= 12


def test_execute_get_daily_forecast():
    res = registry.execute("get_daily_forecast", start_date="2023-09-15", horizon_days=3)
    assert "data" in res
    assert "summary" in res
    assert "assumptions" in res
    assert len(res["data"]) == 3


def test_execute_get_hourly_profile():
    res = registry.execute("get_hourly_profile", weekday=0)
    assert "data" in res
    assert "summary" in res
    assert len(res["data"]) > 0


def test_execute_estimate_workload_hours():
    res = registry.execute("estimate_workload_hours", units=1000, lines=500, orders=150)
    assert "data" in res
    assert "estimated_labor_hours" in res["data"]
    assert res["data"]["estimated_labor_hours"] > 0


def test_execute_recommend_headcount():
    res = registry.execute("recommend_headcount", workload_hours=14.0)
    assert "data" in res
    assert "total_headcount" in res["data"]
    assert res["data"]["total_headcount"] >= 2


def test_execute_run_staffing_sensitivity():
    res = registry.execute("run_staffing_sensitivity", workload_hours=12.0)
    assert "data" in res
    assert len(res["data"]) >= 3


def test_execute_get_abc_xyz():
    res = registry.execute("get_abc_xyz", focus="skus")
    assert "data" in res
    assert len(res["data"]) > 0


def test_execute_recommend_reslotting():
    res = registry.execute("recommend_reslotting", top_n=5)
    assert "data" in res
    assert len(res["data"]) <= 5


def test_execute_list_exceptions():
    res = registry.execute("list_exceptions", limit=10)
    assert "data" in res
    assert len(res["data"]) <= 10


def test_execute_query_data_safe():
    # Safe query
    res = registry.execute("query_data", query="SELECT * FROM products LIMIT 5")
    assert "data" in res
    assert len(res["data"]) == 5

    # Dangerous non-SELECT query must be rejected
    res_drop = registry.execute("query_data", query="DROP TABLE products")
    assert res_drop["data"] is None
    assert "rejected" in res_drop["summary"].lower()
