"""Unit tests for src/warehouse_ai/governance/ — SQLite audit log, approval policies, execution, and learning loop."""

from __future__ import annotations

import pytest

from warehouse_ai.governance.audit import (
    ActionRecord,
    approve,
    audit_logged,
    execute_action,
    governance_report,
    init_db,
    pending_actions,
    record_feedback,
    reject,
    submit,
)
from warehouse_ai.governance.policy import (
    GovernancePolicyConfig,
    evaluate_action_policy,
)


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path for isolated test runs."""
    db_file = tmp_path / "test_governance.db"
    init_db(db_file)
    return db_file


def test_init_db(tmp_db):
    assert tmp_db.exists()


def test_policy_headcount_rules():
    policy = GovernancePolicyConfig(headcount_max_delta=2, headcount_baseline=2)

    # Within threshold (+1) -> auto_approved
    status, reason = evaluate_action_policy("headcount", {"recommended_headcount": 3, "baseline_headcount": 2}, policy)
    assert status == "auto_approved"

    # Exceeds threshold (+3) -> pending
    status, reason = evaluate_action_policy("headcount", {"recommended_headcount": 5, "baseline_headcount": 2}, policy)
    assert status == "pending"
    assert "exceeds threshold" in reason


def test_policy_replenishment_rules():
    policy = GovernancePolicyConfig(replenishment_require_class_a=True, replenishment_max_qty_auto=50)

    # Class A item -> pending
    status, reason = evaluate_action_policy("replenish", {"class": "A", "qty": 10}, policy)
    assert status == "pending"
    assert "Class A" in reason

    # Class C small quantity -> auto_approved
    status, reason = evaluate_action_policy("replenish", {"class": "C", "qty": 20}, policy)
    assert status == "auto_approved"

    # Class C large quantity (>50) -> pending
    status, reason = evaluate_action_policy("replenish", {"class": "C", "qty": 80}, policy)
    assert status == "pending"


def test_policy_slotting_and_exception_rules():
    policy = GovernancePolicyConfig(slotting_require_all_moves=True)

    # Any re-slotting -> pending
    status, reason = evaluate_action_policy("reslot_sku", {"moves": 5}, policy)
    assert status == "pending"

    # High severity exception -> pending
    status, reason = evaluate_action_policy("exception_alert", {"severity": "HIGH"}, policy)
    assert status == "pending"

    # Low severity exception -> auto_approved
    status, reason = evaluate_action_policy("exception_alert", {"severity": "LOW"}, policy)
    assert status == "auto_approved"


def test_submit_action(tmp_db):
    action = submit(
        agent="LaborAgent",
        tool="recommend_headcount",
        proposed_action="Scale headcount from 2 to 6 pickers",
        inputs={"recommended_headcount": 6, "baseline_headcount": 2},
        db_path=tmp_db,
    )
    assert isinstance(action, ActionRecord)
    assert action.id > 0
    assert action.status == "pending"
    assert action.agent == "LaborAgent"


def test_approve_and_pending_actions(tmp_db):
    # Submit one pending and one auto-approved
    a1 = submit(
        agent="LaborAgent",
        tool="headcount",
        proposed_action="Scale to 6",
        inputs={"recommended_headcount": 6, "baseline_headcount": 2},
        db_path=tmp_db,
    )
    submit(
        agent="ReplenishAgent",
        tool="replenish",
        proposed_action="Small top-up",
        inputs={"class": "C", "qty": 10},
        db_path=tmp_db,
    )

    pending_list = pending_actions(tmp_db)
    assert len(pending_list) == 1
    assert pending_list[0].id == a1.id

    # Approve a1
    approved = approve(a1.id, user="Supervisor_Dave", reason="Approved for peak shift", db_path=tmp_db)
    assert approved.status == "approved"
    assert approved.approver == "Supervisor_Dave"

    # Now pending should be empty
    assert len(pending_actions(tmp_db)) == 0


def test_reject_action(tmp_db):
    a = submit(
        agent="SlottingAgent",
        tool="reslot",
        proposed_action="Move 50 boxes",
        db_path=tmp_db,
    )
    rejected = reject(a.id, user="Supervisor_Dave", reason="Budget freeze", db_path=tmp_db)
    assert rejected.status == "rejected"
    assert rejected.reason == "Budget freeze"


def test_execute_action_simulation(tmp_db):
    # Cannot execute pending action
    a_pending = submit(
        agent="SlottingAgent",
        tool="reslot",
        proposed_action="Move 10 boxes",
        db_path=tmp_db,
    )
    with pytest.raises(ValueError, match="Cannot execute action"):
        execute_action(a_pending.id, db_path=tmp_db)

    # Approve it
    approve(a_pending.id, user="Supervisor_Dave", db_path=tmp_db)

    # Now execute
    exec_record = execute_action(a_pending.id, user="WMS_Robot_1", details={"status": "moved"}, db_path=tmp_db)
    assert exec_record.id > 0
    assert exec_record.action_id == a_pending.id
    assert exec_record.executor == "WMS_Robot_1"


def test_learning_feedback_and_governance_report(tmp_db):
    record_feedback(
        date="2023-09-15",
        category="headcount",
        entity="shift_morning",
        recommended=4.0,
        actual=3.0,
        notes="Understaffed slightly",
        db_path=tmp_db,
    )
    record_feedback(
        date="2023-09-16",
        category="headcount",
        entity="shift_morning",
        recommended=5.0,
        actual=5.0,
        notes="Exact match",
        db_path=tmp_db,
    )

    rep = governance_report(tmp_db)
    assert "status_counts" in rep
    assert rep["total_actions"] >= 0
    assert len(rep["learning_feedback"]) == 1

    hc_feedback = rep["learning_feedback"][0]
    assert hc_feedback["category"] == "headcount"
    assert hc_feedback["sample_count"] == 2
    assert hc_feedback["mae"] == 0.5  # (|1.0| + |0.0|) / 2 = 0.5


def test_audit_logged_decorator(tmp_db):
    @audit_logged(agent_name="TestAgent", tool_name="test_tool", db_path=tmp_db)
    def sample_func(x: int) -> dict:
        return {"result": x * 2, "summary": "Calculated double."}

    val = sample_func(10)
    assert val["result"] == 20

    rep = governance_report(tmp_db)
    assert rep["total_actions"] == 1
