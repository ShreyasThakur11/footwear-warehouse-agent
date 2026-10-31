"""CLI runner for the warehouse multi-agent daily planning cycle.

Usage
-----
    python -m warehouse_ai.run_daily --date 2023-09-15 [--provider mock] [--weekly]

Outputs
-------
    reports/daily_plan_<date>.json
    reports/daily_plan_<date>.md
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from warehouse_ai.agents.orchestrator import run_daily_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def format_markdown_report(plan: dict) -> str:
    """Format structured DailyPlan output into executive Markdown report."""
    d = plan.get("date", "UNKNOWN")
    status = plan.get("status", "PENDING")
    forecast = plan.get("forecast") or {}
    labor = plan.get("labor") or {}
    replenish = plan.get("replenishment") or {}
    waves = plan.get("waves") or {}
    slotting = plan.get("slotting") or {}
    exceptions = plan.get("exceptions") or {}
    conflict = plan.get("conflict_resolution") or {}

    lines = [
        f"# Warehouse Daily Operations Plan — {d}",
        "",
        f"> **Governance Status**: `{status}`  ",
        f"> **Generated at**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        "",
        "---",
        "",
        "## 1. Demand Forecast & Volume Drivers",
        "",
        f"- **Expected Units (P50)**: **{forecast.get('expected_units_p50', 0):,.0f} units** "
        f"(Interval: {forecast.get('p10_units', 0):,.0f} to {forecast.get('p90_units', 0):,.0f} units)",
        f"- **Expected Order Lines**: {forecast.get('expected_lines', 0):,.0f} lines",
        f"- **Expected Orders**: {forecast.get('expected_orders', 0):,.0f} orders",
        f"- **Summary**: {forecast.get('summary', 'N/A')}",
        "",
        "---",
        "",
        "## 2. Workforce Staffing & Shift Sizing",
        "",
        f"- **Required Workload**: **{labor.get('required_workload_hours', 0):.2f} hours**",
        f"- **Recommended Headcount**: **{labor.get('total_headcount', 0)} operators** "
        f"({labor.get('permanent_headcount', 0)} permanent core + {labor.get('temp_headcount', 0)} temporary flex)",
        f"- **Scheduled Hours**: {labor.get('scheduled_hours', 0):.1f} hours",
        f"- **Expected Utilization**: **{labor.get('expected_utilization', 0):.1%}**",
        f"- **Daily Payroll Cost**: **${labor.get('estimated_daily_cost_cad', 0):,.2f} CAD**",
        f"- **Shortfall Risk**: `{labor.get('shortfall_risk', 'LOW')}`",
        f"- **Recommendation**: {labor.get('recommendation', 'N/A')}",
        "",
        "---",
        "",
        "## 3. Forward Pick-Face Replenishment",
        "",
        f"- **Policy**: `{replenish.get('policy_name', 'abc_xyz_optimized')}`",
        f"- **Total Replenishment Units**: **{replenish.get('total_replenishment_units', 0):,.0f} pairs**",
        f"- **SKUs Requiring Top-Up**: **{replenish.get('skus_to_replenish', 0)} items**",
        f"- **Summary**: {replenish.get('summary', 'N/A')}",
        "",
        "---",
        "",
        "## 4. Pick Wave Batching & Tour Routing",
        "",
        f"- **Batching Algorithm**: `{waves.get('algorithm', 'seed_savings')}`",
        f"- **Planned Waves**: **{waves.get('n_waves', 0)} waves**",
        f"- **Total Units Batched**: {waves.get('total_units', 0):,.0f} units",
        f"- **Estimated Travel**: {waves.get('total_travel_units', 0):,.0f} units",
        f"- **Estimated Picking Duration**: {waves.get('total_picking_hours', 0):.2f} labor-hours",
        f"- **Summary**: {waves.get('summary', 'N/A')}",
        "",
    ]

    if slotting:
        lines += [
            "---",
            "",
            "## 5. Weekly SKU Re-Slotting Proposals",
            "",
            f"- **Proposed Box Moves**: **{slotting.get('top_n_moves', 0)} moves**",
            f"- **Expected Weekly Walking Savings**: **{slotting.get('expected_weekly_travel_saved_m', 0):,.0f} metres**",
            f"- **Summary**: {slotting.get('summary', 'N/A')}",
            "",
        ]

    lines += [
        "---",
        "",
        "## 6. Operational Exceptions & Quality Triage",
        "",
        f"- **Total Exceptions Scanned**: {exceptions.get('total_exceptions', 0):,}",
        f"- **High Severity Incidents**: **{exceptions.get('high_severity_count', 0)}**",
        f"- **Medium Severity Incidents**: {exceptions.get('medium_severity_count', 0)}",
        f"- **Triage Summary**: {exceptions.get('triage_summary', 'N/A')}",
        "",
        "---",
        "",
        "## 7. Cross-Agent Conflict Resolution & Governance",
        "",
        f"- **Labor Conflict Detected**: `{conflict.get('conflict_detected', False)}`",
        f"- **Extra Replenishment Labor**: {conflict.get('extra_replenishment_hours', 0.0):.2f} hours",
        f"- **Action**: {conflict.get('action', 'N/A')}",
        f"- **Final Governance Decision**: `{status}`",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Warehouse AI Daily Multi-Agent Planning Orchestrator")
    parser.add_argument("--date", type=str, default="2023-09-15", help="Target planning date (YYYY-MM-DD)")
    parser.add_argument("--provider", type=str, default="mock", help="LLM Provider (mock | gemini)")
    parser.add_argument("--weekly", action="store_true", help="Include weekly slotting optimization cycle")
    args = parser.parse_args()

    logger.info("Starting Daily Planning cycle for date %s...", args.date)
    t0 = time.perf_counter()

    final_state = run_daily_cycle(
        target_date=args.date,
        provider=args.provider,
        is_weekly=args.weekly,
    )
    elapsed = time.perf_counter() - t0

    plan_dict = final_state.final_plan or {}

    # Write JSON plan
    json_path = REPORTS_DIR / f"daily_plan_{args.date}.json"
    json_path.write_text(json.dumps(plan_dict, indent=2, default=str), encoding="utf-8")
    logger.info("Written JSON plan → %s", json_path)

    # Write Markdown report
    md_content = format_markdown_report(plan_dict)
    md_path = REPORTS_DIR / f"daily_plan_{args.date}.md"
    md_path.write_text(md_content, encoding="utf-8")
    logger.info("Written Markdown report → %s", md_path)

    print(f"\n[Daily Planning Complete in {elapsed:.1f}s]")
    print(f"Status: {final_state.governance_status}")
    print(f"Reports saved to: {md_path}")


if __name__ == "__main__":
    main()
