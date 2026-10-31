"""Governance approval policy evaluator based on configs/governance.yaml."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class GovernancePolicyConfig:
    """Validated governance approval rules."""

    db_path: str = "data/governance.db"
    headcount_max_delta: int = 2
    headcount_baseline: int = 2
    replenishment_require_class_a: bool = True
    replenishment_max_qty_auto: int = 50
    replenishment_auto_class_c: bool = True
    slotting_require_all_moves: bool = True
    slotting_min_savings_threshold_m: float = 100.0
    exceptions_alert_severity: list[str] = field(default_factory=lambda: ["HIGH"])
    exceptions_require_signoff: bool = True


def load_governance_policy(config_path: str | Path | None = None) -> GovernancePolicyConfig:
    """Load governance configuration from YAML file or default fallbacks."""
    if config_path is None:
        config_path = _PROJECT_ROOT / "configs" / "governance.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        logger.warning("Governance config %s not found. Using safe industrial defaults.", config_path)
        return GovernancePolicyConfig()

    with open(config_path, encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    gov = raw.get("governance", {})
    hc = gov.get("headcount", {})
    rep = gov.get("replenishment", {})
    slot = gov.get("slotting", {})
    exc = gov.get("exceptions", {})

    return GovernancePolicyConfig(
        db_path=gov.get("db_path", "data/governance.db"),
        headcount_max_delta=int(hc.get("max_delta_without_approval", 2)),
        headcount_baseline=int(hc.get("baseline_operators", 2)),
        replenishment_require_class_a=bool(rep.get("require_approval_class_a", True)),
        replenishment_max_qty_auto=int(rep.get("max_qty_auto_approved", 50)),
        replenishment_auto_class_c=bool(rep.get("auto_approve_class_c", True)),
        slotting_require_all_moves=bool(slot.get("require_approval_all_moves", True)),
        slotting_min_savings_threshold_m=float(slot.get("min_weekly_savings_threshold_m", 100.0)),
        exceptions_alert_severity=list(exc.get("alert_severity", ["HIGH"])),
        exceptions_require_signoff=bool(exc.get("require_supervisor_signoff", True)),
    )


def evaluate_action_policy(
    action_type: str,
    details: dict[str, Any] | None = None,
    policy: GovernancePolicyConfig | None = None,
) -> tuple[str, str]:
    """Evaluate an action against approval policies.

    Parameters
    ----------
    action_type : str
        Category of the action: 'headcount', 'replenishment', 'slotting', 'exception', etc.
    details : dict[str, Any] | None
        Payload containing proposed parameters (e.g. recommended_headcount, sku_class, qty, moves).
    policy : GovernancePolicyConfig | None
        Policy rules (loaded from configs/governance.yaml if None).

    Returns
    -------
    tuple[str, str]
        (status, reason) where status is either 'pending' (requires human sign-off)
        or 'auto_approved' (safe for automated execution).
    """
    if policy is None:
        policy = load_governance_policy()

    details = details or {}
    act = action_type.lower()

    # 1. Headcount & Staffing
    if "headcount" in act or "staff" in act or "labor" in act:
        rec_count = details.get("recommended_headcount", details.get("total_headcount", details.get("headcount")))
        baseline = details.get("previous_day_headcount", details.get("baseline_headcount", policy.headcount_baseline))

        if rec_count is not None and baseline is not None:
            delta = abs(float(rec_count) - float(baseline))
            if delta > policy.headcount_max_delta:
                return (
                    "pending",
                    f"Headcount change (+/-{delta:.0f} operators vs {baseline:.0f}) exceeds threshold of {policy.headcount_max_delta} operators.",
                )
        return ("auto_approved", "Headcount adjustment within autonomous variance threshold.")

    # 2. Replenishment Task
    elif "replenish" in act:
        sku_class = str(details.get("class", details.get("class_code", "B"))).upper()
        qty = float(details.get("qty", details.get("units", details.get("suggested_order_qty", 0))))

        if policy.replenishment_require_class_a and sku_class == "A":
            return ("pending", "Class A fast-mover replenishment requires supervisor verification.")
        if qty > policy.replenishment_max_qty_auto:
            return (
                "pending",
                f"Replenishment quantity ({qty:.0f} units) exceeds auto-approval threshold ({policy.replenishment_max_qty_auto} units).",
            )
        return ("auto_approved", f"Small Class {sku_class} replenishment ({qty:.0f} units) auto-approved.")

    # 3. Re-Slotting & Physical Box Relocation
    elif "slot" in act or "reslot" in act:
        if policy.slotting_require_all_moves:
            return ("pending", "Physical warehouse re-slotting requires floor supervisor approval.")
        savings = float(details.get("weekly_savings_m", 0.0))
        if savings < policy.slotting_min_savings_threshold_m:
            return ("pending", f"Move savings ({savings:.1f}m) below auto-approval threshold.")
        return ("auto_approved", "Re-slotting proposal auto-approved.")

    # 4. Operational Exceptions & Alerts
    elif "exception" in act or "anomaly" in act:
        sev = str(details.get("severity", "LOW")).upper()
        if sev in policy.exceptions_alert_severity:
            return ("pending", f"High-severity operational exception ({sev}) requires supervisor sign-off.")
        return ("auto_approved", f"Exception severity {sev} logged for informational audit.")

    # Default fallback: safe read-only or small queries auto-approved
    return ("auto_approved", "Standard operational action within baseline parameters.")
