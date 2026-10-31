# Model Card: Mixed-Integer Linear Programming (MILP) Workforce Staffing Optimizer

## 1. Model Overview
- **Model Name**: Dynamic Temporary Daily-Wage Workforce Optimizer (`warehouse_ai.models.staffing`)
- **Model Type**: Mixed-Integer Linear Program (MILP) solved via `scipy.optimize.milp`
- **Purpose**: Determine optimal daily temporary picker headcount required alongside core permanent staff to guarantee order dispatch before outbound carrier cutoff.
- **Version**: 1.0.0

## 2. Mathematical Formulation
$$\min_{n_{\text{temp}}, h_{\text{ot}}} \quad C_{\text{perm}} \cdot N_{\text{perm}} + C_{\text{temp}} \cdot n_{\text{temp}} + C_{\text{ot}} \cdot h_{\text{ot}}$$
Subject to:
1. **Workload Capacity Constraint**:
   $$E_{\text{perm}} \cdot N_{\text{perm}} \cdot T_{\text{shift}} + n_{\text{temp}} \cdot (1 - a) \cdot \eta \cdot T_{\text{shift}} + h_{\text{ot}} \ge W_{\text{required}}$$
2. **Outbound Dispatch Cutoff**: Cumulative productive picking hours must satisfy daily volume prior to carrier cutoff at 17:00.
3. **Overtime Upper Bound**: $0 \le h_{\text{ot}} \le H_{\text{max\_ot}}$ (maximum 4.0 hours).
4. **Integrality**: $n_{\text{temp}} \in \mathbb{Z}_{\ge 0}$.

### Parameter Calibration
| Parameter | Value | Definition |
|---|---|---|
| $N_{\text{perm}}$ | 2 | Core permanent warehouse pickers |
| $C_{\text{perm}}$ | $180 CAD/day | Daily permanent worker rate |
| $C_{\text{temp}}$ | $150 CAD/day | Daily temporary flex picker wage |
| $C_{\text{ot}}$ | $35 CAD/hour | Overtime hourly labor premium |
| $T_{\text{shift}}$ | 7.5 hours | Standard full-shift duration |
| $\eta$ | 0.85 | Productive efficiency ratio (breaks/rest) |
| $a$ | 0.05 | Absenteeism / unplanned attrition rate |
| Cutoff Hour | 17:00 | Outbound carrier trailer departure |

## 3. Financial & Operational Impact
- **Baseline Staffing**: Facility scheduled an average of **6.53 operators/day** (49.0 operator-hours).
- **Optimized Staffing (P50)**: Recommends an average of **2.11 operators/day** (2 perm + 0.11 temp).
- **Overstaffed Frequency**: **96.1% of operating days** carried unneeded temporary staff.
- **Direct Payroll Savings**: **$118,500 CAD realized savings** across 178 days (**$166,432 CAD annualized**).
- **Service SLA**: 0 days of understaffing breach; 100% order dispatch prior to cutoff.

## 4. Limitations
- Assumes linear additive productivity across workers without dynamic crowding diminishing returns.

