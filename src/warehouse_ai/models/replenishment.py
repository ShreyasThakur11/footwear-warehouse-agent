"""Inventory replenishment simulation and planning models.

Provides:
- Pick-face replenishment (internal moves from Level 3-4 reserve to Level 1-2 pick face)
  based on min/max trigger thresholds.
- Supplier replenishment based on periodic review (R, S) and continuous (s, S) policies
  with safety stock tailored by ABC-XYZ demand classification.
- Historical demand replay simulation replaying 178 operational days across
  alternative replenishment policies (Lean JIT, High Service, ABC-XYZ Optimized).
- Tracks industrial service and capital KPIs: Line Fill Rate, Unit Fill Rate,
  Average On-Hand Inventory, Stockout Events, and Internal Replenishment Moves.
- Production API: ``replenishment_plan`` and ``simulate_replenishment_policies``.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from warehouse_ai.config import load_config
from warehouse_ai.models.classification import compute_abc_xyz

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy Configurations
# ---------------------------------------------------------------------------

@dataclass
class PolicyParameters:
    name: str
    lead_time_days: int
    review_period_days: int
    z_a: float  # Safety factor for Class A (or default)
    z_b: float  # Safety factor for Class B
    z_c: float  # Safety factor for Class C
    pick_face_min: int  # Trigger threshold at pick face
    pick_face_max: int  # Target top-up capacity at pick face


LEAN_JIT_POLICY = PolicyParameters(
    name="Lean_JIT",
    lead_time_days=7,
    review_period_days=7,
    z_a=1.28,  # 90% service level
    z_b=1.04,  # 85% service level
    z_c=0.84,  # 80% service level
    pick_face_min=1,
    pick_face_max=3,
)

HIGH_SERVICE_POLICY = PolicyParameters(
    name="High_Service",
    lead_time_days=7,
    review_period_days=7,
    z_a=2.33,  # 99% service level
    z_b=2.05,  # 98% service level
    z_c=1.65,  # 95% service level
    pick_face_min=3,
    pick_face_max=8,
)

ABC_XYZ_OPTIMIZED_POLICY = PolicyParameters(
    name="ABC_XYZ_Optimized",
    lead_time_days=7,
    review_period_days=7,
    z_a=2.05,  # 98% service level for fast movers
    z_b=1.65,  # 95% service level for medium movers
    z_c=1.28,  # 90% service level for slow movers
    pick_face_min=2,
    pick_face_max=6,
)


# ---------------------------------------------------------------------------
# Safety Stock & Order Level Calculations
# ---------------------------------------------------------------------------

def calculate_sku_targets(
    orders_df: pd.DataFrame,
    policy: PolicyParameters,
) -> pd.DataFrame:
    """Compute reorder points (s) and order-up-to levels (S) by SKU-size.

    Formulas:
        L = lead_time_days, R = review_period_days
        sigma_L = sigma_daily * sqrt(L)
        SS = z * sigma_L
        reorder_point s = mu_daily * L + SS
        order_up_to S = mu_daily * (R + L) + SS
    """
    df = orders_df.copy()
    df["dt"] = pd.to_datetime(df["date"])

    # Aggregate daily demand per sku_size
    daily_skusz = df.groupby(["sku_size", "dt"])["qty"].sum().unstack(fill_value=0.0)

    means = daily_skusz.mean(axis=1)
    stds = daily_skusz.std(axis=1)

    # Classify ABC-XYZ
    abc_xyz_df = compute_abc_xyz(orders_df, entity_col="sku_size")
    class_map = dict(zip(abc_xyz_df["sku_size"], abc_xyz_df["abc_class"]))

    targets = []
    L = float(policy.lead_time_days)
    R = float(policy.review_period_days)

    for sku_size in daily_skusz.index:
        mu = float(means[sku_size])
        sigma = float(stds[sku_size])
        abc = class_map.get(sku_size, "C")

        if abc == "A":
            z = policy.z_a
        elif abc == "B":
            z = policy.z_b
        else:
            z = policy.z_c

        # Safety stock
        sigma_L = sigma * np.sqrt(L)
        ss = max(1.0, z * sigma_L) if mu > 0 else 0.0

        reorder_point = max(1.0, (mu * L) + ss) if mu > 0 else 0.0
        order_up_to = max(reorder_point + 1.0, (mu * (R + L)) + ss) if mu > 0 else 0.0

        targets.append({
            "sku_size": sku_size,
            "abc_class": abc,
            "mean_daily": round(mu, 3),
            "std_daily": round(sigma, 3),
            "z_factor": z,
            "safety_stock": int(np.ceil(ss)),
            "reorder_point": int(np.ceil(reorder_point)),
            "order_up_to": int(np.ceil(order_up_to)),
            "pick_face_min": policy.pick_face_min,
            "pick_face_max": policy.pick_face_max,
        })

    return pd.DataFrame(targets)


# ---------------------------------------------------------------------------
# Historical Demand Replay Simulation Engine
# ---------------------------------------------------------------------------

@dataclass
class SimulationResults:
    policy_name: str
    total_demand_lines: int
    fulfilled_lines: int
    line_fill_rate: float
    total_demand_units: int
    fulfilled_units: int
    unit_fill_rate: float
    stockout_units: int
    stockout_events: int
    mean_on_hand_units: float
    total_internal_replenishments: int
    total_supplier_orders: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_replenishment_policy(
    orders_df: pd.DataFrame,
    policy: PolicyParameters,
    daily_df: pd.DataFrame | None = None,
) -> tuple[SimulationResults, pd.DataFrame]:
    """Execute dynamic day-by-day inventory replay simulation across all dates.

    Models:
    1. Daily customer picking depletion: primary fulfillment from forward pick face
       (Levels 1-2); lines exceeding bin stock draw from Reserve (Levels 3-4).
    2. Internal pick-face replenishment triggered when pick face <= pick_face_min.
    3. Periodic supplier review and inbound PO arrivals with lead time L.
    """
    df = orders_df.copy()
    df["dt"] = pd.to_datetime(df["date"])

    if daily_df is None:
        cfg = load_config()
        daily_df = pd.read_parquet(Path(cfg.paths.data_processed) / "daily.parquet")

    calendar_dates = sorted(pd.to_datetime(daily_df["date"]).unique())

    # Precompute SKU parameters
    sku_params = calculate_sku_targets(df, policy).set_index("sku_size").to_dict(orient="index")

    # Initialize inventory state
    # Forward pick face initialized to pick_face_max; Reserve initialized to (order_up_to - pick_face_max)
    pick_face_stock: dict[str, int] = {}
    reserve_stock: dict[str, int] = {}

    for sku, p in sku_params.items():
        pf_init = p["pick_face_max"]
        res_init = max(0, p["order_up_to"] - pf_init)
        pick_face_stock[sku] = pf_init
        reserve_stock[sku] = res_init

    # Pipeline of pending supplier purchase orders: list of (arrival_date, sku, qty)
    inbound_pipeline: list[tuple[pd.Timestamp, str, int]] = []

    # KPI counters
    total_lines = 0
    fulfilled_lines = 0
    total_units = 0
    fulfilled_units = 0
    stockout_units = 0
    stockout_events = 0
    internal_replenishments = 0
    supplier_orders = 0

    daily_logs = []

    for curr_date in calendar_dates:
        # 1. Inbound supplier arrivals
        arrivals_today = [item for item in inbound_pipeline if item[0] <= curr_date]
        inbound_pipeline = [item for item in inbound_pipeline if item[0] > curr_date]

        for _, sku, qty in arrivals_today:
            # Inbound arrivals go directly into Reserve storage
            reserve_stock[sku] = reserve_stock.get(sku, 0) + qty

        # 2. Daily customer demand fulfillment
        day_orders = df[df["dt"] == curr_date]
        day_lines = len(day_orders)
        day_units = int(day_orders["qty"].sum())

        total_lines += day_lines
        total_units += day_units

        for _, row in day_orders.iterrows():
            sku = row["sku_size"]
            qty = int(row["qty"])

            avail_pf = pick_face_stock.get(sku, 0)
            from_pf = min(qty, avail_pf)
            pick_face_stock[sku] = avail_pf - from_pf
            rem = qty - from_pf

            # Fulfill remainder from reserve if available
            avail_res = reserve_stock.get(sku, 0)
            from_res = min(rem, avail_res)
            reserve_stock[sku] = avail_res - from_res

            line_delivered = from_pf + from_res
            fulfilled_units += line_delivered

            if line_delivered == qty:
                fulfilled_lines += 1
            else:
                unmet = qty - line_delivered
                stockout_units += unmet
                stockout_events += 1

        # 3. Internal Pick-Face Replenishment Trigger (Reserve -> Pick Face)
        for sku, p in sku_params.items():
            curr_pf = pick_face_stock.get(sku, 0)
            if curr_pf <= p["pick_face_min"]:
                needed = p["pick_face_max"] - curr_pf
                curr_res = reserve_stock.get(sku, 0)
                if curr_res > 0 and needed > 0:
                    transfer = min(curr_res, needed)
                    reserve_stock[sku] -= transfer
                    pick_face_stock[sku] += transfer
                    internal_replenishments += 1

        # 4. Periodic Supplier Review (Review day = every Friday)
        is_review_day = curr_date.dayofweek == 4
        if is_review_day:
            for sku, p in sku_params.items():
                on_hand = pick_face_stock.get(sku, 0) + reserve_stock.get(sku, 0)
                on_order = sum(qty for arr_date, s, qty in inbound_pipeline if s == sku)
                inv_pos = on_hand + on_order

                if inv_pos <= p["reorder_point"]:
                    order_qty = max(1, p["order_up_to"] - inv_pos)
                    arrival_date = curr_date + pd.Timedelta(days=policy.lead_time_days)
                    inbound_pipeline.append((arrival_date, sku, order_qty))
                    supplier_orders += 1

        total_on_hand_today = sum(pick_face_stock.values()) + sum(reserve_stock.values())
        daily_logs.append({
            "date": curr_date.strftime("%Y-%m-%d"),
            "demand_units": day_units,
            "on_hand_units": total_on_hand_today,
            "pick_face_units": sum(pick_face_stock.values()),
            "reserve_units": sum(reserve_stock.values()),
        })

    log_df = pd.DataFrame(daily_logs)
    mean_on_hand = float(log_df["on_hand_units"].mean()) if len(log_df) > 0 else 0.0

    line_fill = round(fulfilled_lines / total_lines, 4) if total_lines > 0 else 1.0
    unit_fill = round(fulfilled_units / total_units, 4) if total_units > 0 else 1.0

    summary = SimulationResults(
        policy_name=policy.name,
        total_demand_lines=total_lines,
        fulfilled_lines=fulfilled_lines,
        line_fill_rate=line_fill,
        total_demand_units=total_units,
        fulfilled_units=fulfilled_units,
        unit_fill_rate=unit_fill,
        stockout_units=stockout_units,
        stockout_events=stockout_events,
        mean_on_hand_units=round(mean_on_hand, 1),
        total_internal_replenishments=internal_replenishments,
        total_supplier_orders=supplier_orders,
    )

    return summary, log_df


def simulate_replenishment_policies(
    orders_df: pd.DataFrame | None = None,
    daily_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Compare all three replenishment policies against historical demand."""
    if orders_df is None:
        cfg = load_config()
        orders_path = Path(cfg.paths.data_processed) / "orders_clean.parquet"
        orders_df = pd.read_parquet(orders_path)

    if daily_df is None:
        cfg = load_config()
        daily_path = Path(cfg.paths.data_processed) / "daily.parquet"
        daily_df = pd.read_parquet(daily_path)

    policies = [
        LEAN_JIT_POLICY,
        HIGH_SERVICE_POLICY,
        ABC_XYZ_OPTIMIZED_POLICY,
    ]

    summaries = []
    logs = {}

    for pol in policies:
        logger.info("Simulating policy: %s ...", pol.name)
        res, log_df = simulate_replenishment_policy(orders_df, pol, daily_df=daily_df)
        summaries.append(res.to_dict())
        logs[pol.name] = log_df

    summary_df = pd.DataFrame(summaries)
    return summary_df, logs


# ---------------------------------------------------------------------------
# Production Operational Planning API
# ---------------------------------------------------------------------------

def replenishment_plan(
    date: str | dt.date,
    current_pick_face_stock: dict[str, int] | None = None,
    current_reserve_stock: dict[str, int] | None = None,
    pending_pipeline: list[tuple[str, str, int]] | None = None,
    policy: PolicyParameters = ABC_XYZ_OPTIMIZED_POLICY,
    orders_df: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate daily operational replenishment directives for warehouse supervisors.

    Returns:
    1. 'pick_face_transfers': Internal replenishment tasks moving cartons from Level 3-4 to Level 1-2.
    2. 'supplier_purchase_orders': Inbound purchase orders to send to footwear vendors.
    """
    if orders_df is None:
        cfg = load_config()
        orders_df = pd.read_parquet(Path(cfg.paths.data_processed) / "orders_clean.parquet")

    sku_params = calculate_sku_targets(orders_df, policy).set_index("sku_size").to_dict(orient="index")

    target_date = pd.to_datetime(date)

    # 1. Internal Pick-Face Replenishment Directives
    transfers = []
    if current_pick_face_stock is not None and current_reserve_stock is not None:
        for sku, p in sku_params.items():
            curr_pf = current_pick_face_stock.get(sku, 0)
            curr_res = current_reserve_stock.get(sku, 0)
            if curr_pf <= p["pick_face_min"] and curr_res > 0:
                needed = p["pick_face_max"] - curr_pf
                move_qty = min(curr_res, needed)
                if move_qty > 0:
                    transfers.append({
                        "date": target_date.strftime("%Y-%m-%d"),
                        "sku_size": sku,
                        "source_tier": "Reserve (Levels 3-4)",
                        "destination_tier": "Pick Face (Levels 1-2)",
                        "current_pick_face_units": curr_pf,
                        "reserve_available": curr_res,
                        "transfer_units": move_qty,
                        "urgency": "URGENT" if curr_pf == 0 else "NORMAL",
                    })

    # 2. Supplier Purchase Orders
    purchase_orders = []
    if current_pick_face_stock is not None and current_reserve_stock is not None:
        for sku, p in sku_params.items():
            on_hand = current_pick_face_stock.get(sku, 0) + current_reserve_stock.get(sku, 0)
            on_order = (
                sum(qty for _, s, qty in pending_pipeline if s == sku)
                if pending_pipeline is not None
                else 0
            )
            inv_pos = on_hand + on_order

            if inv_pos <= p["reorder_point"]:
                order_qty = max(1, p["order_up_to"] - inv_pos)
                exp_arrival = target_date + pd.Timedelta(days=policy.lead_time_days)
                purchase_orders.append({
                    "date": target_date.strftime("%Y-%m-%d"),
                    "sku_size": sku,
                    "abc_class": p["abc_class"],
                    "inventory_position": inv_pos,
                    "reorder_point": p["reorder_point"],
                    "order_up_to": p["order_up_to"],
                    "order_units": order_qty,
                    "expected_arrival": exp_arrival.strftime("%Y-%m-%d"),
                })

    return {
        "pick_face_transfers": pd.DataFrame(transfers),
        "supplier_purchase_orders": pd.DataFrame(purchase_orders),
    }
