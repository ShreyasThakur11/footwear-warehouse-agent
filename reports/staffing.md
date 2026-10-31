# Dynamic Workforce Staffing Optimization Report

## Executive Summary
This report presents the mathematical optimization and economic evaluation for right-sizing the
daily-wage order picking workforce. By coupling the calibrated engineered labor standard
($R^2 = 0.9746$, 0.0055 h/unit) with Mixed-Integer Linear Programming (MILP), we optimize daily headcount
to fulfill customer orders prior to the 17:00 outbound dispatch cutoff while eliminating excess payroll.

### Key Financial & Operational Results:
- **Baseline Scheduling**: Warehouse management scheduled an average of **6.53 operators/day** (49.0 operator-hours/day).
- **Optimized Recommendation (P50)**: An average of **2.11 total operators/day** (2 permanent core + 0.11 temp pickers) satisfies picking volume at **59.0% average utilization**.
- **Buffer Recommendation (P90)**: Even under a conservative P90 demand buffer (+25% volume safety margin), only **2.23 total operators/day** are required.
- **Overstaffed Frequency**: **171 of 178 active operational days (96.1%)** carried excess picking staff.
- **Hard Cost Savings**: Right-sizing the daily-wage workforce yields **$118,500.00 CAD** in savings across the 178 observed days, representing **$166,432.58 CAD annualized savings** (assuming $150 CAD/day temporary picker rate).

---

## 1. Historical Staffing Comparison Table (Sample Operating Dates)

| Date | Units | Orders | Needed Workload (h) | Actual Pickers | P50 Recommended | P90 Buffer | Excess Staff | Daily Savings (CAD) |
|------|-------|--------|---------------------|----------------|-----------------|------------|--------------|---------------------|
| 2023-01-05 | 2254 | 270 | 14.7 h | 8 | **2** (0 temp) | 3 | +6 | **$900** |
| 2023-01-23 | 856 | 180 | 6.3 h | 7 | **2** (0 temp) | 2 | +5 | **$750** |
| 2023-02-08 | 975 | 204 | 6.3 h | 7 | **2** (0 temp) | 2 | +5 | **$750** |
| 2023-02-27 | 1496 | 486 | 10.6 h | 8 | **2** (0 temp) | 2 | +6 | **$900** |
| 2023-03-15 | 384 | 91 | 2.2 h | 4 | **2** (0 temp) | 2 | +2 | **$300** |
| 2023-04-13 | 3489 | 446 | 20.8 h | 8 | **3** (1 temp) | 4 | +5 | **$750** |
| 2023-05-02 | 1145 | 149 | 7.5 h | 6 | **2** (0 temp) | 2 | +4 | **$600** |
| 2023-05-23 | 1866 | 279 | 12.9 h | 8 | **2** (0 temp) | 2 | +6 | **$900** |
| 2023-06-09 | 708 | 131 | 4.9 h | 8 | **2** (0 temp) | 2 | +6 | **$900** |
| 2023-06-28 | 636 | 137 | 4.4 h | 9 | **2** (0 temp) | 2 | +7 | **$1050** |
| 2023-07-18 | 1697 | 141 | 8.9 h | 5 | **2** (0 temp) | 2 | +3 | **$450** |
| 2023-08-04 | 235 | 26 | 1.5 h | 3 | **2** (0 temp) | 2 | +1 | **$150** |
| 2023-08-23 | 150 | 1 | 0.6 h | 2 | **2** (0 temp) | 2 | +0 | **$0** |
| 2023-09-12 | 2188 | 308 | 15.3 h | 7 | **2** (0 temp) | 3 | +5 | **$750** |
| 2023-10-05 | 2341 | 267 | 16.1 h | 7 | **2** (0 temp) | 3 | +5 | **$750** |

---

## 2. Sensitivity Analysis across Operating Scenarios

We evaluate staffing sensitivity against ±10% worker productivity shifts, variable absenteeism rates,
and risk postures (P50 vs P90 demand targets):

| Operating Scenario | Average Workload (h) | Recommended Temp | Total Staff | Productive Capacity (h) | Utilization (%) | Daily Cost (CAD) | Annualized Payroll (CAD) |
|--------------------|----------------------|------------------|-------------|-------------------------|-----------------|------------------|--------------------------|
| **Baseline (P50)** | 7.8 h | 0 | 2 | 12.1 h | 64.6% | $360 | **$64,080.00** |
| **High Demand (P90)** | 9.8 h | 0 | 2 | 12.1 h | 80.8% | $360 | **$64,080.00** |
| **Low Productivity (-10%)** | 8.7 h | 0 | 2 | 10.9 h | 79.8% | $360 | **$64,080.00** |
| **High Productivity (+10%)** | 7.1 h | 0 | 2 | 13.3 h | 53.4% | $360 | **$64,080.00** |
| **Zero Absenteeism (0%)** | 7.8 h | 0 | 2 | 12.8 h | 61.4% | $360 | **$64,080.00** |
| **High Absenteeism (10%)** | 7.8 h | 0 | 2 | 11.5 h | 68.2% | $360 | **$64,080.00** |

---

## 3. Operational Policy Recommendations

1. **Shift Core Permanent Staff to Cross-Docking & Putaway**:
   - Order picking requires an average of ~1.66 to 2.11 productive FTEs.
   - Core permanent operators (2 FTE) should handle early morning EDI wave staging and high-speed picking.
2. **On-Demand Call-In Strategy for Daily-Wage Workers**:
   - Call in temporary daily-wage pickers only when morning EDI orders (arriving at 07:00 AM) project workload exceeding 12.1 productive hours.
   - On peak days (>1,800 units), schedule 1–2 temporary pickers to guarantee 17:00 dispatch cutoff compliance.
3. **Automated Cutoff Monitoring**:
   - If EDI volume releases exceed P90 thresholds after 11:00 AM, the system triggers automated overtime authorization or expedited batch grouping.
