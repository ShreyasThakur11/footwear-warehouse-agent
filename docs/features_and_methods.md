# Footwear Warehouse Operations Guide: Core Capabilities & Algorithms

This technical manual details how the autonomous warehouse optimization engine operates, covering the exact mathematical models, algorithms, detection mechanisms, and operational workflows used across every module.

---

## 1. Demand Forecasting Engine

### The Operational Challenge
In footwear distribution, demand forecasting operates across two distinct dimensions:
1. **Macro Aggregate Volume**: Predicting total daily pairs, order lines, and EDI orders so supervisors know overall facility labor requirements.
2. **Micro SKU-Size Intermittency**: Predicting specific footwear style and size combinations (e.g. Reference 102, Size 9.5). Over **69.8%** of SKU-size pairs exhibit zero demand on any given day, making traditional continuous time-series models fail due to sporadic order bursts.

### Mathematical Methods & Algorithms

#### A. Supervised Quantile Regression (`HistGradientBoostingRegressor`)
- **Method**: Quantile Gradient Tree Boosting minimizing the asymmetric **Pinball Loss** function:
  $$L_\alpha(y, \hat{y}) = \max\Big(\alpha(y - \hat{y}), (1 - \alpha)(\hat{y} - y)\Big)$$
- **Quantiles Computed**:
  - $\alpha = 0.50$ (P50): Median unbiased expected demand.
  - $\alpha = 0.10$ (P10): Lower-bound estimate (base workload).
  - $\alpha = 0.90$ (P90): Upper-bound safety buffer to absorb demand surges without missing carrier cutoff times.
- **Engineered Features**:
  - **Autoregressive Lags**: Lags at $t-1$, $t-7$, and $t-14$ days to capture daily autocorrelation and weekly cycles.
  - **Rolling Windows**: 7-day and 14-day rolling moving averages ($\mu$) and standard deviations ($\sigma$).
  - **Calendar Indicators**: Day-of-week one-hot encoding, day-of-month, week-of-year, and month.
  - **Statutory Holiday Calendar**: Explicit Canadian/Quebec statutory holidays (Good Friday, Easter Monday, Patriots' Day, Saint-Jean-Baptiste, Labour Day, Thanksgiving) preventing artificial post-holiday forecasting overhangs.

#### B. Intermittent Demand Engine: Croston's Method with Syntetos-Boylan Approximation (Croston-SBA)
- **Method**: Traditional exponential smoothing over-forecasts intermittent items because it updates during non-zero periods and decays during zero periods, causing positive bias. Croston-SBA decomposes sporadic demand into two distinct components:
  1. Demand size when non-zero ($z_t$ updated via smoothing parameter $\alpha = 0.10$).
  2. Inter-arrival time between non-zero demand intervals ($p_t$).
- **Syntetos-Boylan Correction Factor**:
  $$\hat{D}_{t+1} = \left(1 - \frac{\alpha}{2}\right) \frac{z_t}{p_t}$$
  This factor debiases slow-moving extreme shoe sizes (e.g. Size 7.0 and Size 13.0) and avoids over-allocating forward shelf slots.

#### C. Intra-Day Hourly Arrival Profile
- **Method**: Empirical Dirichlet probability distribution over operating hours (07:00 to 17:00).
- **Finding**: Over **90%** of order volume arrives in the 07:00 AM EDI release drop, transitioning into steady outbound processing throughout the shift.

---

## 2. Quality & Operational Exceptions Engine

### What is a Quality Exception?
In a warehouse, an **operational exception** is any physical, inventory, or execution discrepancy between what the WMS planned and what occurred on the floor. Unresolved exceptions create lost inventory, shipping delays, picker confusion, and mis-picks (e.g. sending a customer two left shoes or the wrong size).

### Detection Architecture & Algorithms

The system executes a dual-layer scanner combining **5 deterministic rule-based checks** and **multivariate unsupervised anomaly detection**:

```
                       WMS Transactional Logs
                  (Orders, Picks, Waves, Locations)
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
┌──────────────────────────────┐        ┌──────────────────────────────┐
│  Deterministic Rule Scanners │        │ Statistical Outlier Detector │
│  (Exact Threshold Matching)  │        │  (IsolationForest Algorithm) │
└──────────────┬───────────────┘        └──────────────┬───────────────┘
               │                                       │
               └───────────────────┬───────────────────┘
                                   ▼
               Triage Engine: Severity & Prescriptive Action
```

#### Layer 1: Deterministic Rule Scanners
1. **Fulfillment Discrepancies (`SHORT_PICK` / `OVER_PICK`)**:
   - *Logic*: Flags whenever $\text{Picked Units} \ne \text{Ordered Units}$ for a wave reference.
   - *Severity*: **High** when short; **Medium** when over.
   - *Action*: Triggers immediate forward pick-face cycle count and re-checks bin physical stock.
2. **Policy Location Mismatches (`LOCATION_POLICY_MISMATCH`)**:
   - *Logic*: Compares pick location against active catalog storage slotting (e.g. picking a fast-moving Size 10 from reserve Level 4 rather than ground Level 1).
   - *Severity*: **Medium**.
   - *Action*: Audits slotting master data and schedules bin consolidation moves.
3. **Unmapped Locations (`UNKNOWN_LOCATION`)**:
   - *Logic*: Checks coordinates against the 2,292 physical shelf rack definitions. Flags staging areas (`ZN-COR`, `EX-01`, dock staging).
   - *Severity*: **High**.
   - *Action*: Verifies physical aisle barcode placards and updates graph network coordinates.
4. **Demand Volatility Breaches (`DEMAND_SURGE_BREACH`)**:
   - *Logic*: Flags days where order units fall outside the P10–P90 forecast confidence envelope.
   - *Severity*: **Medium**.
   - *Action*: Alerts floor management to authorize temp flex labor or flex overtime.
5. **Operator Productivity Outliers (`OPERATOR_PRODUCTIVITY_DEV`)**:
   - *Logic*: Computes units-per-labor-hour ($UPH$) per operator-day. Flags any operator deviating $> 2.0\sigma$ from peer cohort mean:
     $$|UPH_i - \mu_{UPH}| > 2 \cdot \sigma_{UPH}$$
   - *Severity*: **Low** (ergonomic/fatigue check for surge operators; coaching check for slow operators).

#### Layer 2: Multivariate Statistical Anomaly Detection (`IsolationForest`)
- **Method**: Fits an ensemble of 100 Isolation Trees on 4 geometric wave features:
  1. `total_units`: Units picked in wave.
  2. `n_locations`: Distinct shelf stops visited.
  3. `n_aisles`: Distinct warehouse aisles traversed.
  4. `travel_dist`: Total Dijkstra walking distance.
- **Why it matters**: A rule cannot easily flag a wave that has normal units (25 pairs) but visits 15 aisles because the batching algorithm fragmented the orders. `IsolationForest` isolates these multi-aisle geometric outliers, scoring the top 1.0% most anomalous waves for supervisor review.

---

## 3. Forward Replenishment Engine

### The Operational Challenge
The facility has 5 vertical shelf tiers:
- **Tiers 1–2 (Ground & Mid)**: 30,456 forward pick-face bin slots directly accessible to manual pickers without ladders.
- **Tiers 3–4 (Reserve Overhead)**: 10,800 storage slots holding bulk inventory, requiring reach-truck forklifts to retrieve.

If a fast-moving shoe runs out on Level 1, pickers must stop, wait for a forklift, or walk past the empty bin, causing short-picks. The Replenishment Engine ensures Level 1–2 pick-face bins are restocked from Levels 3–4 **before** pickers enter the aisle.

### Mathematical Methods & Policies

```
             ┌──────────────────────────────────────────┐
             │       External Supplier Purchase Orders   │
             │       (Review Period R=7d, Lead Time L=7d)│
             └────────────────────┬─────────────────────┘
                                  ▼
             ┌──────────────────────────────────────────┐
             │   Tier 2: Reserve Overhead (Levels 3–4)  │
             │   10,800 bulk storage slots (Forklifts)  │
             └────────────────────┬─────────────────────┘
                                  ▼  Internal Top-Up Move
             ┌──────────────────────────────────────────┐
             │   Tier 1: Forward Pick-Face (Levels 1–2) │
             │   30,456 pick slots (Manual Trolleys)    │
             └────────────────────┬─────────────────────┘
                                  ▼  Wave Picking
                             Customer EDI
```

#### A. Forward Pick-Face Min/Max Policy
- **Min Trigger ($s$)**: Set to 2 pairs. When forward on-hand stock falls to $\le 2$ pairs:
  $$\text{On-Hand}_{\text{Level 1-2}} \le s \implies \text{Issue Forklift Let-Down Task}$$
- **Max Target ($S$)**: Set to 6 pairs. The forklift driver lowers exactly:
  $$\Delta Q = \min\Big(\text{Reserve Available}, S - \text{On-Hand}\Big)$$
- **Result**: Eliminates pick-face starvation while avoiding overfilling narrow shelf bins.

#### B. Periodic External Supplier Replenishment: $(R, S)$ Order-Up-To Model
- **Review Period ($R$)**: 7 days.
- **Supplier Lead Time ($L$)**: 7 days.
- **Order-Up-To Level ($S$)**:
  $$S = \mu_D \cdot (R + L) + z_{\alpha} \cdot \sigma_D \cdot \sqrt{R + L}$$
  Where:
  - $\mu_D$ is mean daily demand from the forecasting engine.
  - $\sigma_D$ is standard deviation of daily demand.
  - $z_{\alpha}$ is safety factor calibrated to customer service targets:
    - **Class A**: $98\%$ service level ($z = 2.05$).
    - **Class B**: $95\%$ service level ($z = 1.65$).
    - **Class C**: $90\%$ service level ($z = 1.28$).

#### C. Multi-Agent Conflict Resolution
When the Replenishment Agent schedules forklift moves, it communicates with the Wave Agent. Heavy forklift operations in narrow aisles during the 07:00–09:00 AM morning peak picking window create safety and congestion conflicts. The orchestrator re-routes replenishment tasks to pre-shift or off-peak hours.

---

## 4. Labor Sizing & Workforce Optimization

### Mathematical Method: Mixed-Integer Linear Programming (MILP)
To determine exact operator headcount, the system solves a daily **Mixed-Integer Linear Program** using `scipy.optimize.milp`:

$$\min_{N_{\text{perm}}, N_{\text{temp}}, H_{\text{ot}}} \quad C_{\text{perm}} \cdot N_{\text{perm}} + C_{\text{temp}} \cdot N_{\text{temp}} + C_{\text{ot}} \cdot H_{\text{ot}}$$

**Subject to:**
1. **Capacity Requirement**: Total productive hours must satisfy the engineered picking workload ($W_{\text{req}}$):
   $$\Big(N_{\text{perm}} + N_{\text{temp}}\Big) \cdot H_{\text{shift}} \cdot \eta_{\text{prod}} \cdot (1 - \lambda_{\text{absent}}) + H_{\text{ot}} \ge W_{\text{req}}$$
   Where:
   - $H_{\text{shift}} = 7.5\text{ hours}$
   - $\eta_{\text{prod}} = 0.85$ (Productivity ratio accounting for breaks and staging drop-offs)
   - $\lambda_{\text{absent}} = 0.05$ (Expected daily absenteeism)
2. **Carrier Cutoff Deadline**: Cumulative completed picking hours by 17:00 must meet or exceed the day's total demand.
3. **Integer Constraints**: $N_{\text{perm}}, N_{\text{temp}} \in \mathbb{Z}_{\ge 0}$.

---

## 5. Warehouse Travel & Route Optimization

### Mathematical Methods
1. **Warehouse Network Graph**: 44 corridor waypoints + 2,292 projected shelf locations modeled as a bidirected NetworkX graph with precomputed all-pairs Dijkstra distance matrices.
2. **Order Batching (Seed + Savings)**:
   - Groups orders into picking carts bounded by trolley physical limits (**27 pairs maximum**).
   - Selects a seed order with the farthest aisle coordinate, then iteratively merges orders that minimize added detour travel distance.
3. **Pick Routing (TSP Local Search 2-Opt)**:
   - Re-orders stops along the picking tour using a 2-opt uncrossing heuristic to eliminate backtracking across aisles, reducing picker walking distance by **14.6% to 64.7%** without moving inventory.

---

## 6. Complete System Feature & Method Summary

| System Module | Operational Feature | Mathematical / Engineering Method | Primary Output |
| :--- | :--- | :--- | :--- |
| **Demand Forecasting** | Aggregate Volume (1–14 days) | Quantile Gradient Boosting (`HistGradientBoostingRegressor`) with Pinball Loss | P10, P50, P90 daily pairs, lines, orders |
| | Intermittent SKU-Size Demand | Croston's Method with Syntetos-Boylan Approximation (SBA) | Debiased demand rates for slow-moving sizes |
| | Intra-Day Workload Profile | Dirichlet empirical arrival probability distribution | Hourly workload curve (07:00–17:00) |
| **Labor & Staffing** | Engineered Labor Standard | Calibrated activity standard: setup, travel, stop, pick, vertical penalty | Exact required picker labor-hours |
| | Workforce Headcount Sizing | SciPy Mixed-Integer Linear Programming (MILP) | Optimal Permanent vs. Temp headcount |
| **Replenishment** | Forward Pick-Face Top-Up | $(s, S)$ Min/Max Inventory Control ($s=2, S=6$) | Forklift let-down task lists |
| | Supplier Reordering | Periodic Review $(R, S)$ with ABC-calibrated safety stock | Weekly supplier purchase orders |
| **Routing & Slotting** | Travel Matrix & Distance | All-pairs Dijkstra on 44-waypoint NetworkX navigation graph | Precise metric distance per wave |
| | Order Batching | Seed + Savings heuristic + trolley capacity constraints (27 pairs) | Clustered 27-pair wave pick lists |
| | Stop Routing (TSP) | Nearest Neighbor + 2-opt uncrossing heuristic | Sequential shortest-path tour |
| | Storage Re-Slotting | Cube-per-Order Index (COI) & Footwear Family Co-Location | Minimum-move SKU relocation proposals |
| **Anomaly Detection** | Deterministic Quality Audit | 5 rule-based comparison scanners | Flagged short-picks, mismatches, dock bays |
| | Wave Geometric Anomalies | Multivariate Unsupervised `IsolationForest` (100 estimators) | Flagged multi-aisle wandering waves |
| **Governance & UI** | Audit & Decision Logging | SQLite ACID-compliant 3-table audit engine (`audit.db`) | Complete compliance history & learning loop |
| | Supervisor Cockpit | Streamlit interactive reactive dashboard | 8 operational pages with Approve/Reject gates |
