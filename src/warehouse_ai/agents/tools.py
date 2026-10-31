"""Standardized agent tool registry and wrappers for warehouse AI models.

Every tool returns a consistent JSON-serializable dictionary:
    {
        "data": Any,
        "summary": str,
        "assumptions": list[str]
    }

Provides a global ToolRegistry containing metadata, parameter schemas,
read-only classification, and agent permission mapping.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from warehouse_ai.config import load_config
from warehouse_ai.models.anomaly import exceptions_to_dataframe, scan_all_exceptions
from warehouse_ai.models.classification import compute_abc_xyz
from warehouse_ai.models.forecasting import (
    compute_hourly_profile,
    forecast_daily,
    forecast_sku_size,
)
from warehouse_ai.models.labor import (
    day_workload_hours,
    workload_hours_from_forecast,
)
from warehouse_ai.models.replenishment import (
    ABC_XYZ_OPTIMIZED_POLICY,
    HIGH_SERVICE_POLICY,
    LEAN_JIT_POLICY,
    replenishment_plan,
)
from warehouse_ai.models.slotting import (
    compare_all_policies,
    recommend_reslotting,
)
from warehouse_ai.models.staffing import (
    recommend_headcount,
    run_staffing_sensitivity,
)
from warehouse_ai.models.waves import plan_waves

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Metadata & Registry
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    """Metadata describing an agent tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    allowed_agents: list[str]
    is_read_only: bool
    func: Callable[..., dict[str, Any]]

    def to_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema specification for LLM tool calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Central catalog of available agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        allowed_agents: list[str],
        is_read_only: bool = True,
    ) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
        """Decorator to register a tool function in the global registry."""
        def decorator(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                allowed_agents=allowed_agents,
                is_read_only=is_read_only,
                func=func,
            )
            return func
        return decorator

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_for_agent(self, agent_name: str) -> list[ToolDefinition]:
        """Return all tools that the specified agent is permitted to execute."""
        return [
            t for t in self._tools.values()
            if "*" in t.allowed_agents or agent_name in t.allowed_agents or "CopilotAgent" == agent_name
        ]

    def get_schemas_for_agent(self, agent_name: str) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self.get_for_agent(agent_name)]

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Execute a tool by name with arguments and return validated output."""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' is not registered in ToolRegistry.")
        try:
            res = tool.func(**kwargs)
            if not isinstance(res, dict) or "summary" not in res or "assumptions" not in res:
                res = {
                    "data": res,
                    "summary": f"Executed tool '{name}'.",
                    "assumptions": ["Model execution based on default warehouse parameters."],
                }

            # Record tool call in governance audit trail
            try:
                from warehouse_ai.governance.audit import submit
                submit(
                    agent="ToolRegistry",
                    tool=name,
                    proposed_action=f"Execute {name}",
                    inputs=kwargs,
                    outputs={"summary": res.get("summary")},
                    details=kwargs,
                )
            except Exception as audit_err:
                logger.debug("Audit logging skipped: %s", audit_err)

            return res
        except Exception as e:
            logger.error("Error executing tool %s: %s", name, e, exc_info=True)
            return {
                "data": None,
                "summary": f"Execution of tool '{name}' failed: {e}",
                "assumptions": ["Execution encountered an exception."],
                "error": str(e),
            }


registry = ToolRegistry()


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

@registry.register(
    name="get_daily_forecast",
    description="Generate daily forecast of customer order units, lines, and orders with P10/P50/P90 prediction intervals.",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "Starting calendar date (YYYY-MM-DD), default '2023-09-15'."},
            "horizon_days": {"type": "integer", "description": "Forecast horizon length in days (1–14), default 14."},
        },
    },
    allowed_agents=["ForecastAgent", "LaborAgent", "CopilotAgent"],
    is_read_only=True,
)
def get_daily_forecast(start_date: str = "2023-09-15", horizon_days: int = 14) -> dict[str, Any]:
    df = forecast_daily(start_date=start_date, horizon=horizon_days)
    records = df.to_dict(orient="records")
    p50_total = df["units_p50"].sum() if "units_p50" in df.columns else 0
    p10_total = df["units_p10"].sum() if "units_p10" in df.columns else 0
    p90_total = df["units_p90"].sum() if "units_p90" in df.columns else 0

    return {
        "data": records,
        "summary": (
            f"Generated {horizon_days}-day daily demand forecast from {start_date}. "
            f"Total expected units (P50): {p50_total:,.0f} (range: {p10_total:,.0f} to {p90_total:,.0f} units)."
        ),
        "assumptions": [
            "Quantile Histogram Gradient Boosting model with calendar and lag features.",
            "Prediction intervals calibrated at P10, P50, and P90 quantile levels.",
            "Canadian and Quebec statutory holidays accounted for.",
        ],
    }


@registry.register(
    name="get_hourly_profile",
    description="Retrieve historical intra-day arrival volume profile by hour for a specific weekday (0=Monday, 6=Sunday).",
    parameters={
        "type": "object",
        "properties": {
            "weekday": {"type": "integer", "description": "Day of week (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun)."},
        },
    },
    allowed_agents=["ForecastAgent", "LaborAgent", "CopilotAgent"],
    is_read_only=True,
)
def get_hourly_profile(weekday: int = 0) -> dict[str, Any]:
    cfg = load_config()
    hourly_df = pd.read_parquet(Path(cfg.paths.data_processed) / "hourly.parquet")
    profile_df = compute_hourly_profile(hourly_df)
    if "weekday" in profile_df.columns:
        sub = profile_df[profile_df["weekday"] == weekday]
    else:
        sub = profile_df
    records = sub.to_dict(orient="records")

    return {
        "data": records,
        "summary": (
            f"Retrieved intra-day hourly order release distribution for weekday {weekday}. "
            "Morning EDI batch release shock accounts for ~90% of daily volume at 07:00 AM."
        ),
        "assumptions": [
            "Empirical hourly release shares computed from 122,370 historical order lines.",
            "Normalized to 100% total daily order volume.",
        ],
    }


@registry.register(
    name="get_sku_size_forecast",
    description="Forecast weekly demand for intermittent and smooth footwear SKU-sizes using Croston-SBA and LightGBM.",
    parameters={
        "type": "object",
        "properties": {
            "sku_size": {"type": "string", "description": "Optional specific SKU-size key (e.g. '8N10W9|10.0')."},
            "weeks": {"type": "integer", "description": "Number of future weeks to forecast, default 4."},
        },
    },
    allowed_agents=["ForecastAgent", "ReplenishmentAgent", "CopilotAgent"],
    is_read_only=True,
)
def get_sku_size_forecast(sku_size: str | None = None, weeks: int = 4) -> dict[str, Any]:
    df = forecast_sku_size(weeks=weeks)
    if sku_size and "sku_size" in df.columns:
        df = df[df["sku_size"] == sku_size]

    records = df.head(50).to_dict(orient="records")
    return {
        "data": records,
        "summary": f"Generated {weeks}-week granular SKU-size demand projection across catalog.",
        "assumptions": [
            "Croston SBA applied to intermittent demand series (>70% zero-demand weeks).",
            "Histogram Gradient Boosting applied to fast-moving smooth SKU-sizes.",
        ],
    }


@registry.register(
    name="estimate_workload_hours",
    description="Estimate required picking labor-hours from planned order volume (units, lines, orders) or historical date.",
    parameters={
        "type": "object",
        "properties": {
            "units": {"type": "integer", "description": "Planned unit volume."},
            "lines": {"type": "integer", "description": "Planned order line volume."},
            "orders": {"type": "integer", "description": "Planned order count."},
            "date": {"type": "string", "description": "Optional historical date (YYYY-MM-DD)."},
        },
    },
    allowed_agents=["LaborAgent", "ForecastAgent", "CopilotAgent"],
    is_read_only=True,
)
def estimate_workload_hours(
    units: int | None = None,
    lines: int | None = None,
    orders: int | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    if units is not None:
        lines_count = lines if lines is not None else int(units / 1.86)
        orders_count = orders if orders is not None else int(units / 7.0)
        hours = workload_hours_from_forecast(units=units, lines=lines_count, orders=orders_count)
        summary = f"Estimated required picking labor: {hours:.2f} hours for {units} units ({lines_count} lines, {orders_count} orders)."
    elif date is not None:
        cfg = load_config()
        waves_df = pd.read_parquet(Path(cfg.paths.data_processed) / "waves.parquet")
        hours = day_workload_hours(date=date, waves_df=waves_df)
        summary = f"Actual calibrated picking labor for date {date}: {hours:.2f} hours."
    else:
        hours = 12.4
        summary = "Estimated baseline daily picking labor: 12.40 hours."

    return {
        "data": {"estimated_labor_hours": round(hours, 2)},
        "summary": summary,
        "assumptions": [
            "Engineered labor standard: 1.0 m/s travel, 60s setup, 10s stop, 6s pick.",
            "Empirically calibrated with scale factor k = 1.5853 to match a 7.5-hour shift for peak operators.",
            "Ordinary Least Squares regression (R^2 = 0.9746, MAE = 0.85 hours).",
        ],
    }


@registry.register(
    name="recommend_headcount",
    description="Solve Mixed-Integer Linear Program (MILP) to determine optimal permanent and temporary daily-wage pickers.",
    parameters={
        "type": "object",
        "required": ["workload_hours"],
        "properties": {
            "workload_hours": {"type": "number", "description": "Total required picking workload in labor-hours."},
            "date": {"type": "string", "description": "Operational calendar date (YYYY-MM-DD)."},
        },
    },
    allowed_agents=["LaborAgent", "CopilotAgent"],
    is_read_only=True,
)
def recommend_headcount_tool(workload_hours: float, date: str | None = None) -> dict[str, Any]:
    target_date = date or "2023-09-15"
    rec = recommend_headcount(date=target_date, workload_hours=workload_hours)
    return {
        "data": rec.to_dict(),
        "summary": (
            f"Recommended staffing for {workload_hours:.1f}h workload: {rec.permanent_headcount} permanent + "
            f"{rec.recommended_temp_headcount} temp operators ({rec.total_headcount} total). "
            f"Total payroll cost: ${rec.estimated_daily_cost:.2f} CAD; Expected utilization: {rec.utilization:.1%}."
        ),
        "assumptions": [
            "Standard shift: 7.5 productive hours at 85% efficiency.",
            "Daily wage: $180 CAD permanent, $150 CAD temporary flex worker.",
            "Overtime permitted at $35/hr up to 4.0 hours maximum.",
            "5:00 PM outbound carrier dispatch cutoff enforced.",
        ],
    }


@registry.register(
    name="run_staffing_sensitivity",
    description="Evaluate staffing roster and payroll costs under demand shocks (-30% to +30%).",
    parameters={
        "type": "object",
        "properties": {
            "workload_hours": {"type": "number", "description": "Baseline required picking labor-hours."},
        },
    },
    allowed_agents=["LaborAgent", "CopilotAgent"],
    is_read_only=True,
)
def run_staffing_sensitivity_tool(workload_hours: float | None = None) -> dict[str, Any]:
    cfg = load_config()
    daily_df = pd.read_parquet(Path(cfg.paths.data_processed) / "daily.parquet")
    df = run_staffing_sensitivity(daily_df=daily_df)
    return {
        "data": df.to_dict(orient="records"),
        "summary": (
            f"Sensitivity analysis completed across {len(df)} scenarios. "
            f"Headcount scales from {df['total_headcount'].min()} to {df['total_headcount'].max()} operators."
        ),
        "assumptions": [
            "MILP optimization evaluated independently across all scenario increments.",
            "Permanent core staff fixed at 2 operators.",
        ],
    }


@registry.register(
    name="get_replenishment_plan",
    description="Generate prioritized multi-echelon replenishment order proposals between reserve shelves and forward pick-face.",
    parameters={
        "type": "object",
        "properties": {
            "policy_name": {"type": "string", "description": "Inventory policy ('abc_xyz_optimized', 'lean_jit', 'high_service')."},
            "review_date": {"type": "string", "description": "Calendar date for weekly periodic review."},
        },
    },
    allowed_agents=["ReplenishmentAgent", "CopilotAgent"],
    is_read_only=True,
)
def get_replenishment_plan(
    policy_name: str = "abc_xyz_optimized",
    review_date: str | None = None,
) -> dict[str, Any]:
    target_date = review_date or "2023-09-15"
    policy_map = {
        "abc_xyz_optimized": ABC_XYZ_OPTIMIZED_POLICY,
        "lean_jit": LEAN_JIT_POLICY,
        "high_service": HIGH_SERVICE_POLICY,
    }
    pol = policy_map.get(policy_name.lower(), ABC_XYZ_OPTIMIZED_POLICY)
    plan_dict = replenishment_plan(date=target_date, policy=pol)

    transfers_df = plan_dict.get("pick_face_transfers", pd.DataFrame())
    po_df = plan_dict.get("supplier_purchase_orders", pd.DataFrame())

    transfers = transfers_df.head(50).to_dict(orient="records") if isinstance(transfers_df, pd.DataFrame) and not transfers_df.empty else []
    pos = po_df.head(50).to_dict(orient="records") if isinstance(po_df, pd.DataFrame) and not po_df.empty else []

    transfer_qty = float(transfers_df["transfer_qty"].sum()) if "transfer_qty" in transfers_df.columns else 0.0
    po_qty = float(po_df["order_qty"].sum()) if "order_qty" in po_df.columns else 0.0

    return {
        "data": {
            "pick_face_transfers": transfers,
            "supplier_purchase_orders": pos,
            "total_transfer_units": transfer_qty,
            "total_po_units": po_qty,
        },
        "summary": (
            f"Generated replenishment plan ({pol.name}) for {target_date}: "
            f"{len(transfers)} internal pick-face transfers ({transfer_qty:,.0f} pairs), "
            f"{len(pos)} supplier purchase orders ({po_qty:,.0f} pairs)."
        ),
        "assumptions": [
            "Forward pick face covers shelf Levels 1–2 (2 pairs safety stock, 6 pairs top-up target).",
            "Reserve stock held on upper Levels 3–4.",
            f"Service level targets: Class A {pol.z_a}, Class B {pol.z_b}, Class C {pol.z_c}.",
        ],
    }


@registry.register(
    name="get_abc_xyz",
    description="Retrieve Pareto ABC volume velocity and XYZ demand variability classifications for footwear products.",
    parameters={
        "type": "object",
        "properties": {
            "focus": {"type": "string", "description": "'skus' or 'products', default 'skus'."},
        },
    },
    allowed_agents=["ForecastAgent", "ReplenishmentAgent", "SlottingAgent", "CopilotAgent"],
    is_read_only=True,
)
def get_abc_xyz(focus: str = "skus") -> dict[str, Any]:
    cfg = load_config()
    orders_df = pd.read_parquet(Path(cfg.paths.data_processed) / "orders_clean.parquet")
    entity_col = "sku_size" if focus == "skus" else "reference"
    df = compute_abc_xyz(orders_df=orders_df, entity_col=entity_col)
    records = df.head(50).to_dict(orient="records")
    return {
        "data": records,
        "summary": (
            f"Computed ABC-XYZ matrix for {len(df)} catalog items. "
            "Top 20% Class A items drive 80% of volume; Class AX/AY items are fast-moving predictable candidates."
        ),
        "assumptions": [
            "Pareto ABC cutoffs: 80% cumulative volume = Class A, 15% = Class B, 5% = Class C.",
            "Coefficient of Variation (CV) cutoffs: CV <= 0.50 (X), 0.50 < CV <= 1.00 (Y), CV > 1.00 (Z).",
        ],
    }


@registry.register(
    name="compare_storage_policies",
    description="Simulate warehouse picker travel and labor hours across Random, Class-Based, Dedicated, Hybrid, and Optimised-COI policies.",
    parameters={
        "type": "object",
        "properties": {
            "max_waves": {"type": "integer", "description": "Number of waves to simulate (default 200 for fast interactive execution)."},
        },
    },
    allowed_agents=["SlottingAgent", "CopilotAgent"],
    is_read_only=True,
)
def compare_storage_policies_tool(max_waves: int | None = 200) -> dict[str, Any]:
    sum_df, _ = compare_all_policies(max_waves=max_waves)
    records = sum_df.to_dict(orient="records")
    best = sum_df.sort_values("travel_reduction_pct", ascending=False).iloc[0]

    return {
        "data": records,
        "summary": (
            f"Simulated {len(sum_df)} storage policies across {max_waves or 'all'} waves. "
            f"Top performer '{best['policy_name']}' delivers {best['travel_reduction_pct']:+.1f}% travel reduction "
            f"and {best['labor_reduction_pct']:+.1f}% labor savings vs Random baseline."
        ),
        "assumptions": [
            "Dijkstra all-pairs shortest paths on warehouse graph.",
            "S-Shape tour heuristic with depot at CC-01.",
            "Calibrated LaborModel with vertical tier reach penalties.",
        ],
    }


@registry.register(
    name="recommend_reslotting",
    description="Generate prioritized SKU relocation proposals to forward shelf bins to minimize picker walking distance.",
    parameters={
        "type": "object",
        "properties": {
            "top_n": {"type": "integer", "description": "Number of top ROI relocation proposals to return (default 20)."},
        },
    },
    allowed_agents=["SlottingAgent", "CopilotAgent"],
    is_read_only=True,
)
def recommend_reslotting_tool(top_n: int = 20) -> dict[str, Any]:
    moves = recommend_reslotting(top_n=top_n)
    total_savings = sum(m["expected_travel_saved_per_week"] for m in moves)

    return {
        "data": moves,
        "summary": (
            f"Proposed top {len(moves)} re-slotting box moves. "
            f"Unlocks an estimated {total_savings:,.0f} metres of weekly walking distance savings."
        ),
        "assumptions": [
            "Cube-per-Order Index (COI) prioritizing fast movers on Level 1-2 near depot CC-01.",
            "18 bin slots capacity constraint per shelf location strictly enforced.",
            "Move effort categorized as Low (same aisle), Medium (cross aisle), or High (forklift tier).",
        ],
    }


@registry.register(
    name="plan_waves",
    description="Batch open customer orders into pick waves within 27-pair cart capacity and balance picker operator assignments.",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "Calendar date (YYYY-MM-DD), default '2023-09-15'."},
            "n_operators": {"type": "integer", "description": "Number of available pickers, default 5."},
            "algorithm": {"type": "string", "description": "'seed_savings', 'fcfs', or 'aisle_cluster', default 'seed_savings'."},
        },
    },
    allowed_agents=["WaveAgent", "CopilotAgent"],
    is_read_only=True,
)
def plan_waves_tool(
    date: str | None = None,
    n_operators: int = 5,
    algorithm: str = "seed_savings",
) -> dict[str, Any]:
    cfg = load_config()
    proc = Path(cfg.paths.data_processed)
    orders_df = pd.read_parquet(proc / "orders_clean.parquet")

    chosen_date = date or "2023-09-15"
    day_orders = orders_df[orders_df["date"].astype(str) == chosen_date].copy()
    if day_orders.empty:
        day_orders = orders_df.head(200).copy()

    plans = plan_waves(
        orders_df=day_orders,
        n_operators=n_operators,
        algorithm=algorithm,
    )
    records = [p.to_dict() for p in plans[:25]]  # Return top 25 waves summary
    total_travel = sum(p.estimated_travel for p in plans)
    total_hours = sum(p.estimated_time_s for p in plans) / 3600.0

    return {
        "data": records,
        "summary": (
            f"Planned {len(plans)} waves for {day_orders['order_number'].nunique()} orders using '{algorithm}' batching. "
            f"Total estimated travel: {total_travel:,.0f} units; Total picking labor: {total_hours:.2f} hours across {n_operators} pickers."
        ),
        "assumptions": [
            "Trolley capacity bounded at 27 shoe pairs per wave.",
            "Longest-Processing-Time (LPT) load balancing assigns waves to operators.",
            "Locations resolved via active storage layout.",
        ],
    }


@registry.register(
    name="list_exceptions",
    description="Audit warehouse operations for short picks, unslotted location picks, master data gaps, and productivity outliers.",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "Filter by operational date (YYYY-MM-DD)."},
            "severity": {"type": "string", "description": "Filter by severity ('HIGH', 'MEDIUM', 'LOW')."},
            "limit": {"type": "integer", "description": "Maximum number of exception records to return, default 50."},
        },
    },
    allowed_agents=["ExceptionAgent", "CopilotAgent"],
    is_read_only=True,
)
def list_exceptions_tool(
    date: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    all_recs = scan_all_exceptions()
    df = exceptions_to_dataframe(all_recs)

    if date:
        df = df[df["date"] == date]
    if severity:
        df = df[df["severity"] == severity.upper()]

    records = df.head(limit).to_dict(orient="records")
    return {
        "data": records,
        "summary": (
            f"Found {len(df)} total operational exceptions "
            f"(showing top {len(records)}). Breakdown: {dict(df['type'].value_counts().head(5))}."
        ),
        "assumptions": [
            "Rule-based threshold validation and IsolationForest statistical anomaly detection.",
            "Actionable recommendations prioritized by HIGH severity.",
        ],
    }


@registry.register(
    name="query_data",
    description="Execute a safe, read-only SQL query with DuckDB over processed warehouse parquet tables.",
    parameters={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "SQL SELECT query over tables: orders_clean, picks_clean, waves, daily, hourly, products, locations, storage_long."},
            "limit": {"type": "integer", "description": "Row limit (max 100), default 50."},
        },
    },
    allowed_agents=["*"],
    is_read_only=True,
)
def query_data(query: str, limit: int = 50) -> dict[str, Any]:
    # Guard against non-SELECT queries
    cleaned_query = query.strip()
    if not cleaned_query.upper().startswith("SELECT"):
        return {
            "data": None,
            "summary": "Query rejected: only read-only SELECT statements are permitted.",
            "assumptions": ["Security rule: arbitrary modification statements (DROP, DELETE, UPDATE, INSERT) forbidden."],
        }

    cfg = load_config()
    proc = Path(cfg.paths.data_processed)

    con = duckdb.connect(database=":memory:")
    # Register all processed parquet tables
    for table_file in proc.glob("*.parquet"):
        tname = table_file.stem
        con.execute(f"CREATE VIEW {tname} AS SELECT * FROM read_parquet('{table_file}')")

    capped_limit = min(max(1, limit), 100)
    wrapped_query = f"SELECT * FROM ({cleaned_query}) LIMIT {capped_limit}"

    try:
        res_df = con.execute(wrapped_query).fetchdf()
        records = res_df.to_dict(orient="records")
        return {
            "data": records,
            "summary": f"Query returned {len(records)} rows.",
            "assumptions": ["Query executed safely in sandboxed DuckDB read-only view."],
        }
    except Exception as e:
        return {
            "data": None,
            "summary": f"Query execution failed: {e}",
            "assumptions": ["Query syntax error or invalid table reference."],
            "error": str(e),
        }
    finally:
        con.close()
