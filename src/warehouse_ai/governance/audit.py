"""SQLite audit log and governance execution engine for warehouse AI actions.

Provides:
- SQLite database tables:
    - actions: audit trail of every tool call and agent proposal.
    - executed_actions: simulated execution log of approved actions.
    - learning_feedback: recommended vs actual tracking for accuracy learning.
- Submission, approval, rejection, and simulated execution lifecycle.
- Policy-driven autonomous gating vs supervisor sign-off requirements.
- @audit_logged decorator for automatic instrumentation.
- Learning loop accuracy tracking and governance reporting.
"""

from __future__ import annotations

import functools
import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from warehouse_ai.governance.policy import (
    GovernancePolicyConfig,
    evaluate_action_policy,
    load_governance_policy,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """Audit log entry for an agent tool call or operational proposal."""

    id: int
    ts: str
    agent: str
    tool: str
    inputs_json: str
    outputs_json: str
    proposed_action: str
    status: str  # 'auto_approved', 'pending', 'approved', 'rejected', 'executed'
    approver: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        try:
            d["inputs"] = json.loads(self.inputs_json)
        except Exception:
            d["inputs"] = self.inputs_json
        try:
            d["outputs"] = json.loads(self.outputs_json)
        except Exception:
            d["outputs"] = self.outputs_json
        return d


@dataclass
class ExecutedActionRecord:
    """Record of an action dispatched to simulated warehouse floor execution."""

    id: int
    action_id: int
    executed_at: str
    executor: str
    details_json: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        try:
            d["details"] = json.loads(self.details_json)
        except Exception:
            d["details"] = self.details_json
        return d


@dataclass
class FeedbackRecord:
    """Learning loop record comparing model recommendations against actual observed values."""

    id: int
    ts: str
    date: str
    category: str
    entity: str
    recommended_val: float
    actual_val: float
    error_val: float
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Database Schema & Initialization
# ---------------------------------------------------------------------------

def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve full filesystem path for the governance SQLite database."""
    if db_path is None:
        policy = load_governance_policy()
        db_path = policy.db_path

    path = Path(db_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def init_db(db_path: str | Path | None = None) -> Path:
    """Initialize governance database schema if not present."""
    path = _resolve_db_path(db_path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()

        # 1. Actions Table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                agent TEXT NOT NULL,
                tool TEXT NOT NULL,
                inputs_json TEXT,
                outputs_json TEXT,
                proposed_action TEXT,
                status TEXT NOT NULL,
                approver TEXT,
                reason TEXT
            );
            """
        )

        # 2. Executed Actions Table (Simulated WMS Execution)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS executed_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id INTEGER NOT NULL,
                executed_at TEXT NOT NULL,
                executor TEXT NOT NULL,
                details_json TEXT,
                FOREIGN KEY (action_id) REFERENCES actions(id)
            );
            """
        )

        # 3. Learning Feedback Table (Accuracy Tracking)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                entity TEXT,
                recommended_val REAL,
                actual_val REAL,
                error_val REAL,
                notes TEXT
            );
            """
        )
        conn.commit()

    return path


# ---------------------------------------------------------------------------
# Lifecycle API: Submit, Approve, Reject, Execute
# ---------------------------------------------------------------------------

def submit(
    agent: str,
    tool: str,
    proposed_action: str,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    policy: GovernancePolicyConfig | None = None,
) -> ActionRecord:
    """Submit an action proposal into the governance audit log.

    Evaluates approval policy: if action requires human oversight, status is set
    to 'pending'. Otherwise, it is marked 'auto_approved'.
    """
    path = init_db(db_path)
    policy = policy or load_governance_policy()

    # Determine status based on policy
    status, reason = evaluate_action_policy(
        action_type=f"{tool}_{proposed_action}",
        details=details or inputs or {},
        policy=policy,
    )

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    inputs_str = json.dumps(inputs or {}, default=str)
    outputs_str = json.dumps(outputs or {}, default=str)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO actions (ts, agent, tool, inputs_json, outputs_json, proposed_action, status, approver, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (ts, agent, tool, inputs_str, outputs_str, proposed_action, status, None, reason),
        )
        conn.commit()
        action_id = cursor.lastrowid

    logger.info("Governance action #%d submitted [%s]: %s (reason: %s)", action_id, status, proposed_action, reason)
    return ActionRecord(
        id=int(action_id),
        ts=ts,
        agent=agent,
        tool=tool,
        inputs_json=inputs_str,
        outputs_json=outputs_str,
        proposed_action=proposed_action,
        status=status,
        approver=None,
        reason=reason,
    )


def approve(
    action_id: int,
    user: str,
    reason: str = "Supervisor manual approval",
    db_path: str | Path | None = None,
) -> ActionRecord:
    """Approve a pending action proposal."""
    path = _resolve_db_path(db_path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM actions WHERE id = ?", (action_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Action #{action_id} not found in governance audit log.")

        cursor.execute(
            """
            UPDATE actions
            SET status = 'approved', approver = ?, reason = ?
            WHERE id = ?;
            """,
            (user, reason, action_id),
        )
        conn.commit()

        cursor.execute("SELECT id, ts, agent, tool, inputs_json, outputs_json, proposed_action, status, approver, reason FROM actions WHERE id = ?", (action_id,))
        updated = cursor.fetchone()

    logger.info("Governance action #%d APPROVED by %s (reason: %s)", action_id, user, reason)
    return ActionRecord(*updated)


def reject(
    action_id: int,
    user: str,
    reason: str = "Supervisor manual rejection",
    db_path: str | Path | None = None,
) -> ActionRecord:
    """Reject a pending action proposal."""
    path = _resolve_db_path(db_path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM actions WHERE id = ?", (action_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Action #{action_id} not found in governance audit log.")

        cursor.execute(
            """
            UPDATE actions
            SET status = 'rejected', approver = ?, reason = ?
            WHERE id = ?;
            """,
            (user, reason, action_id),
        )
        conn.commit()

        cursor.execute("SELECT id, ts, agent, tool, inputs_json, outputs_json, proposed_action, status, approver, reason FROM actions WHERE id = ?", (action_id,))
        updated = cursor.fetchone()

    logger.info("Governance action #%d REJECTED by %s (reason: %s)", action_id, user, reason)
    return ActionRecord(*updated)


def execute_action(
    action_id: int,
    user: str = "system",
    details: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> ExecutedActionRecord:
    """Simulate execution of an approved or auto-approved governance action."""
    path = _resolve_db_path(db_path)
    details = details or {}

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status, proposed_action FROM actions WHERE id = ?", (action_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Action #{action_id} not found.")

        current_status = row[1]
        if current_status not in ("approved", "auto_approved"):
            raise ValueError(f"Cannot execute action #{action_id}: current status is '{current_status}'. Must be 'approved' or 'auto_approved'.")

        exec_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        details_str = json.dumps(details, default=str)

        # Record in executed_actions
        cursor.execute(
            """
            INSERT INTO executed_actions (action_id, executed_at, executor, details_json)
            VALUES (?, ?, ?, ?);
            """,
            (action_id, exec_ts, user, details_str),
        )
        exec_id = cursor.lastrowid

        # Update action status to 'executed'
        cursor.execute("UPDATE actions SET status = 'executed' WHERE id = ?", (action_id,))
        conn.commit()

    logger.info("Action #%d simulated executed (Execution ID: #%d by %s)", action_id, exec_id, user)
    return ExecutedActionRecord(
        id=int(exec_id),
        action_id=action_id,
        executed_at=exec_ts,
        executor=user,
        details_json=details_str,
    )


def pending_actions(db_path: str | Path | None = None) -> list[ActionRecord]:
    """Retrieve all actions currently awaiting supervisor approval."""
    path = init_db(db_path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, ts, agent, tool, inputs_json, outputs_json, proposed_action, status, approver, reason
            FROM actions
            WHERE status = 'pending'
            ORDER BY id ASC;
            """
        )
        rows = cursor.fetchall()

    return [ActionRecord(*r) for r in rows]


# ---------------------------------------------------------------------------
# Learning Loop: Accuracy Tracking
# ---------------------------------------------------------------------------

def record_feedback(
    date: str,
    category: str,
    entity: str,
    recommended: float,
    actual: float,
    notes: str = "",
    db_path: str | Path | None = None,
) -> FeedbackRecord:
    """Store recommended vs actual observed operational metrics to track model calibration."""
    path = init_db(db_path)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    error_val = round(recommended - actual, 3)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO learning_feedback (ts, date, category, entity, recommended_val, actual_val, error_val, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (ts, date, category, entity, float(recommended), float(actual), error_val, notes),
        )
        conn.commit()
        fb_id = cursor.lastrowid

    logger.info("Recorded learning feedback #%d [%s/%s]: rec=%.2f, act=%.2f, err=%.2f", fb_id, category, entity, recommended, actual, error_val)
    return FeedbackRecord(
        id=int(fb_id),
        ts=ts,
        date=date,
        category=category,
        entity=entity,
        recommended_val=float(recommended),
        actual_val=float(actual),
        error_val=error_val,
        notes=notes,
    )


def governance_report(db_path: str | Path | None = None) -> dict[str, Any]:
    """Compile audit metrics, approval rates, and learning loop accuracy tracking."""
    path = init_db(db_path)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()

        # Action status breakdown
        cursor.execute("SELECT status, COUNT(*) FROM actions GROUP BY status")
        status_counts = dict(cursor.fetchall())

        # Executed actions total
        cursor.execute("SELECT COUNT(*) FROM executed_actions")
        executed_count = cursor.fetchone()[0]

        # Learning loop metrics
        cursor.execute(
            """
            SELECT category, COUNT(*), AVG(ABS(error_val)), AVG(error_val)
            FROM learning_feedback
            GROUP BY category
            """
        )
        learning_stats = []
        for row in cursor.fetchall():
            learning_stats.append({
                "category": row[0],
                "sample_count": row[1],
                "mae": round(row[2], 3),
                "bias": round(row[3], 3),
            })

    total_actions = sum(status_counts.values())
    pending_cnt = status_counts.get("pending", 0)
    approved_cnt = status_counts.get("approved", 0)
    auto_cnt = status_counts.get("auto_approved", 0)
    rejected_cnt = status_counts.get("rejected", 0)
    exec_cnt = status_counts.get("executed", 0)

    summary_str = (
        f"Governance audit summary: {total_actions} total actions recorded "
        f"({auto_cnt} auto-approved, {approved_cnt} approved, {rejected_cnt} rejected, {pending_cnt} pending, {exec_cnt} executed). "
        f"Total simulated executions: {executed_count}."
    )

    return {
        "status_counts": status_counts,
        "total_actions": total_actions,
        "simulated_executions": executed_count,
        "learning_feedback": learning_stats,
        "summary": summary_str,
    }


# ---------------------------------------------------------------------------
# Decorator: Automatically Audit Tool Calls & Agent Proposals
# ---------------------------------------------------------------------------

def audit_logged(
    agent_name: str = "System",
    tool_name: str | None = None,
    proposed_action: str | None = None,
    db_path: str | Path | None = None,
) -> Callable:
    """Decorator to automatically log tool execution into SQLite governance audit trail."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            effective_tool = tool_name or func.__name__
            effective_action = proposed_action or f"Execute {effective_tool}"

            # Capture inputs
            inputs_dict = dict(kwargs)
            if args:
                inputs_dict["_args"] = [str(a) for a in args]

            # Execute function
            t0 = time.perf_counter()
            try:
                res = func(*args, **kwargs)
                outputs_dict = res if isinstance(res, dict) else {"result": str(res)}
            except Exception as e:
                outputs_dict = {"error": str(e)}
                submit(
                    agent=agent_name,
                    tool=effective_tool,
                    proposed_action=effective_action,
                    inputs=inputs_dict,
                    outputs=outputs_dict,
                    details={"error": True},
                    db_path=db_path,
                )
                raise

            elapsed = time.perf_counter() - t0
            outputs_dict["_latency_s"] = round(elapsed, 4)

            # Submit to audit log
            submit(
                agent=agent_name,
                tool=effective_tool,
                proposed_action=effective_action,
                inputs=inputs_dict,
                outputs=outputs_dict,
                details=inputs_dict,
                db_path=db_path,
            )

            return res
        return wrapper
    return decorator
