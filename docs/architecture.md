# System Architecture & Technical Specification

## 1. High-Level Architectural Vision

The Footwear Warehouse AI platform is an industrial-grade, multi-agent digital twin and decision-support system designed to solve the physical and operational bottlenecks of modern footwear distribution centers:
1. **Physical Logistics Bottleneck**: Picker walking travel accounts for >60% of total order-picking time. Solved via Cube-per-Order Index (COI) family-based re-slotting and 2-opt TSP tour routing.
2. **Workforce Inefficiency**: High volatility in morning order arrivals (90% EDI release shock at 07:00 AM) leads facilities to schedule excess daily-wage staff. Solved via calibrated engineered labor standards and Mixed-Integer Linear Programming (MILP) workforce right-sizing.
3. **Inventory Service Risk**: Rapid stockouts at manual ground picking tiers. Solved via multi-echelon forward pick-face replenishment simulation with ABC-XYZ safety stock sizing.

---

## 2. Six-Layer System Architecture

```mermaid
flowchart TD
    subgraph L1["Layer 1: Data & Ingestion Lakehouse"]
        D1["Raw CSVs (WMS, Layout, Orders, Picks)"] --> D2["Loaders & Cleaners (loaders.py, cleaning.py)"]
        D2 --> D3["Processed Parquet Tables (data/processed/)"]
        D3 --> D4["Data Validation & Reconciliation (validate.py)"]
    end

    subgraph L2["Layer 2: Scientific & Operations Research Models"]
        M1["Travel & Layout Graph (travel.py)"]
        M2["Calibrated Labor Standard (labor.py)"]
        M3["Demand Forecasting (forecasting.py)"]
        M4["MILP Staffing Optimizer (staffing.py)"]
        M5["Inventory Classification (classification.py)"]
        M6["Multi-Echelon Replenishment (replenishment.py)"]
        M7["COI Slotting Simulator (slotting.py)"]
        M8["Wave Batching & LPT Routing (waves.py)"]
        M9["Anomaly & Outlier Detector (anomaly.py)"]
    end

    subgraph L3["Layer 3: Standardized Tool Registry & LLM Client"]
        T1["Tool Registry (13 Schema-Validated Tools)"]
        T2["Provider-Agnostic LLM Interface (Mock | Gemini)"]
        T3["DuckDB Sandboxed SQL Layer"]
    end

    subgraph L4["Layer 4: Autonomous Specialist Reasoning Agents"]
        A1["ForecastAgent"]
        A2["LaborAgent"]
        A3["ReplenishmentAgent"]
        A4["WaveAgent"]
        A5["SlottingAgent"]
        A6["ExceptionAgent"]
        A7["CopilotAgent"]
    end

    subgraph L5["Layer 5: Orchestrator & Governance Engine"]
        O1["LangGraph StateGraph Cycle (orchestrator.py)"]
        O2["Cross-Agent Conflict Resolution"]
        G1["Policy Gating Engine (configs/governance.yaml)"]
        G2["SQLite Audit Trail & Learning Loop (audit.py)"]
    end

    subgraph L6["Layer 6: Supervisor Presentation & UI Cockpit"]
        U1["Streamlit Supervisor Copilot (app/streamlit_app.py)"]
        U2["Executive Daily Reports (reports/daily_plan_*.md)"]
        U3["CLI Runner (warehouse_ai.run_daily)"]
    end

    D3 --> M1 & M2 & M3 & M4 & M5 & M6 & M7 & M8 & M9
    M1 & M2 & M3 & M4 & M5 & M6 & M7 & M8 & M9 --> T1
    T1 & T2 & T3 --> A1 & A2 & A3 & A4 & A5 & A6 & A7
    A1 & A2 & A3 & A4 & A5 & A6 --> O1
    O1 --> O2 --> G1 --> G2
    G2 --> U1 & U2 & U3
    A7 <--> U1
```

---

## 3. Daily Multi-Agent Planning Flow

Every morning prior to shift dispatch, the autonomous multi-agent state graph executes a coordinated end-to-end planning cycle:

```mermaid
sequenceDiagram
    autonumber
    actor Supervisor as Warehouse Supervisor
    participant Orch as LangGraph Orchestrator
    participant FC as ForecastAgent
    participant LA as LaborAgent
    participant RP as ReplenishmentAgent
    participant WV as WaveAgent
    participant SL as SlottingAgent
    participant EX as ExceptionAgent
    participant Gov as Governance Engine

    Supervisor->>Orch: Trigger Daily Planning Cycle (Target Date)
    activate Orch
    Orch->>FC: Project Demand (P10/P50/P90, Units, Lines, Orders)
    FC-->>Orch: Demand Forecast State
    Orch->>LA: Size Picking Workforce (MILP, Hours, Perm + Temp)
    LA-->>Orch: Staffing Recommendation State
    Orch->>RP: Calculate Pick-Face Drop & Inbound POs
    RP-->>Orch: Forward Replenishment State
    Orch->>WV: Plan Order Batches & Assign Operators (Seed+Savings, LPT)
    WV-->>Orch: Wave Dispatch State
    opt Weekly Cycle
        Orch->>SL: Compute COI Re-Slotting & Relocation Moves
        SL-->>Orch: Re-Slotting Proposal State
    end
    Orch->>EX: Audit Operations for Quality & Integrity Exceptions
    EX-->>Orch: Operational Exceptions State
    Orch->>Orch: Evaluate Cross-Agent Resource Conflicts
    Note over Orch: Verify aisle congestion between forklifts & pickers
    Orch->>Gov: Submit Daily Plan for Policy Evaluation
    Gov-->>Orch: Policy Gating Verdict (Auto-Approved | Pending)
    Orch-->>Supervisor: Structured Plan (daily_plan_date.json / Markdown / Streamlit UI)
    deactivate Orch
```

---

## 4. Layer Specifications

### Layer 1: Data & Ingestion Lakehouse
- **Source**: 9 raw CSV tables representing real operations from a safety footwear distribution center in Quebec, Canada (122,370 order lines, 215,192 pick actions, 2,293 shelf locations across 17 aisles).
- **Processing**: Size decoding algorithm (`cleaning.py`) normalizes whole and fractional shoe sizes with 99.28% exact multiset matching. Location parser breaks alphanumeric codes into hierarchical coordinates (`aisle`, `bay`, `level`, `slot`, $x$, $y$, $z$).
- **Storage**: Parquet format with Snappy compression in `data/processed/` for high-throughput columnar analytics.

### Layer 2: Scientific Models & Operations Research
- **Travel Graph (`travel.py`)**: 44 corridor waypoints, 17 horizontal aisle walkways, 2,292 projected storage locations. Precomputed all-pairs Dijkstra distance matrix.
- **Calibrated Labor Standard (`labor.py`)**: Synthetic activity-based time standard calibrated via scale factor $k = 1.5853$ to match a 7.5-hour productive shift on high-volume days.
- **Demand Forecaster (`forecasting.py`)**: Quantile Histogram Gradient Boosting (P10, P50, P90) + Holt-Winters ETS + Croston-SBA for 70% zero-demand intermittent shoe variants.
- **Staffing Optimizer (`staffing.py`)**: Mixed-Integer Linear Programming (MILP) solving daily temporary flex worker headcount subject to outbound carrier cutoff (17:00).
- **Inventory Classifier (`classification.py`)**: Multi-criteria Pareto ABC classification and XYZ coefficient of demand variation.
- **Replenishment Simulator (`replenishment.py`)**: Dynamic two-tier inventory replay between Levels 3–4 (Reserve) and Levels 1–2 (Forward Pick Face) with periodic (R, S) supplier review.
- **Slotting Simulator (`slotting.py`)**: Cube-per-Order Index (COI) and Optimised-FAMILY layout placing full footwear size runs within golden depot zones.
- **Wave Planner (`waves.py`)**: FCFS, Seed+Savings, and Aisle-Clustering heuristics respecting trolley capacity ($c = 27$ pairs) with Longest Processing Time (LPT) operator workload balancing.
- **Exception Triage (`anomaly.py`)**: 5 rule-based operational checks + IsolationForest unsupervised outlier detection on pick waves.

### Layer 3: Tool Registry & LLM Client
- Provider-agnostic client abstraction supporting zero-network deterministic testing (`MockLLMClient`) and live frontier multimodal models (`GeminiLLMClient`).
- 13 registered tools with JSON-schema input/output contracts, read-only guarantees, and embedded DuckDB SQL querying.

### Layer 4: Autonomous Specialist Agents
- Individual role-prompted agents (`ForecastAgent`, `LaborAgent`, `ReplenishmentAgent`, `WaveAgent`, `SlottingAgent`, `ExceptionAgent`, `CopilotAgent`).
- Strict grounding protocol: Agents are instructed never to hallucinate numbers; every metric must cite an underlying tool calculation.

### Layer 5: Orchestrator & Governance Engine
- **LangGraph StateGraph**: Deterministic sequential state machine chaining agent outputs into a unified `DailyPlan`.
- **Conflict Resolution**: Detects and mitigates spatial bottlenecks (e.g. reserving early morning hours for replenishment forklift transit before high-density order picking commences).
- **Governance Audit Engine (`governance/`)**: SQLite-backed audit trail logging all tool calls and agent actions (`actions`, `executed_actions`, `learning_feedback`). Configurable YAML policy gating for headcount variances, Class A moves, and high-severity incidents.

### Layer 6: Supervisor Presentation Cockpit
- **Streamlit Control Center (`app/streamlit_app.py`)**: 8 interactive operational views with live sensitivity analysis, human-in-the-loop approval actions, and 2D picking heat maps.
- **Automated Reporting**: Production of executive Markdown and JSON deliverables in `reports/`.

