"""ExceptionAgent: triages operational anomalies, short picks, and inventory mismatches."""

from __future__ import annotations

from warehouse_ai.agents.base import BaseAgent
from warehouse_ai.agents.schemas import ExceptionOutput
from warehouse_ai.agents.tools import registry
from warehouse_ai.llm.client import LLMClient


class ExceptionAgent(BaseAgent):
    """Specialist agent for operational quality control and anomaly remediation."""

    def __init__(self, llm_client: LLMClient | None = None, provider: str | None = None) -> None:
        super().__init__(
            name="ExceptionAgent",
            role="Operational Quality & Anomaly Triage Specialist",
            prompt_filename="exception.md",
            llm_client=llm_client,
            provider=provider,
        )

    def triage_exceptions(self, target_date: str | None = None) -> ExceptionOutput:
        """Scan exceptions and extract high-priority actionable incidents."""
        res = registry.execute("list_exceptions", date=target_date, limit=50)
        recs = res.get("data", [])
        assumptions = res.get("assumptions", [])

        high = [r for r in recs if r.get("severity") == "HIGH"]
        med = [r for r in recs if r.get("severity") == "MEDIUM"]
        low = [r for r in recs if r.get("severity") == "LOW"]

        return ExceptionOutput(
            total_exceptions=len(recs),
            high_severity_count=len(high),
            medium_severity_count=len(med),
            low_severity_count=len(low),
            critical_exceptions=high[:10],
            triage_summary=res.get("summary", f"Triaged {len(recs)} operational exceptions."),
            assumptions=assumptions,
        )
