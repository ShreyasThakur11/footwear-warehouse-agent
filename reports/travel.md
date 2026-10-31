# Picking Wave Travel Distance & Routing Analysis

## 1. Executive Summary
This report evaluates picker travel distances across **9,784 picking waves** using graph-based rectilinear shortest path routing through the warehouse aisle network.

The tour for each wave originates from the depot (`CC-01` at $x=403.0, y=-29.0$), traverses all distinct pick stops along the assigned aisles and cross-corridors, and returns to the depot.

---

## 2. Travel Distance Distribution Across Waves

| Metric | Travel per Wave (Units) | Travel per Unit (Units/Pair) |
|---|---|---|
| **Count** | 9,784 waves | 9,784 waves |
| **Mean** | 3,901.2 | 212.3 |
| **Median (P50)** | 4,117.0 | 186.0 |
| **Std Dev** | 1,534.3 | 235.2 |
| **P10** | 1,942.0 | 97.1 |
| **P25** | 3,076.0 | 138.5 |
| **P75** | 4,978.0 | 229.5 |
| **P90** | 5,836.0 | 284.1 |
| **Max** | 7,522.0 | 3,634.0 |

> **Note on Coordinate Units**: Distances are computed in warehouse grid units (~0.04 m/unit along aisles). A wave travel distance of 4,117 units corresponds to approximately **165–170 meters** of physical walking, consistent with empirical warehouse observations.

---

## 3. Comparison of Routing Heuristics

A benchmarking comparison across 200 empirical picking waves evaluates three classic warehouse tour construction algorithms:

| Routing Method | Mean Travel | Median Travel | Std Dev | Distance vs S-Shape |
|---|---|---|---|---|
| **Nearest Neighbor (NN)** | **4,566.5** | **4,558.0** | 964.5 | **−1.6% (Superior)** |
| **S-Shape (Serpentine)** | 4,640.6 | 4,598.0 | 983.4 | Baseline |
| **Largest Gap** | 4,700.9 | 4,696.0 | 1,024.3 | +1.3% |

- **Nearest Neighbor** yields the shortest tours by eliminating cross-aisle backtracking between adjacent bays.
- **S-Shape** offers the most predictable deterministic route sequence for manual trolley operators.
- **Largest Gap** is effective when pick density is sparse, but suffers slightly when multiple bays across the central corridor are active simultaneously.

---

## 4. Top 10 Longest Picking Waves

The longest recorded waves are characterized by high stop dispersion (17–24 distinct bin locations across separate aisles):

| Rank | Wave ID | Date | Orders | Lines | Units | Distinct Stops | Travel Distance | Travel / Unit |
|---|---|---|---|---|---|---|---|---|
| 🥇 1 | `33303` | 2023-01-06 | 6 | 22 | 24 | 20 | **7,522.0** | 313.4 |
| 🥈 2 | `33183` | 2023-01-05 | 1 | 20 | 24 | 19 | **7,512.0** | 313.0 |
| 🥉 3 | `39455` | 2023-06-26 | 5 | 18 | 24 | 17 | **7,504.0** | 312.7 |
| 4 | `40905` | 2023-08-15 | 5 | 20 | 24 | 20 | **7,450.0** | 310.4 |
| 5 | `42689` | 2023-10-03 | 16 | 21 | 24 | 22 | **7,346.0** | 306.1 |
| 6 | `40560` | 2023-07-31 | 18 | 24 | 24 | 24 | **7,338.0** | 305.8 |
| 7 | `33333` | 2023-01-09 | 1 | 20 | 24 | 20 | **7,316.0** | 304.8 |
| 8 | `39136` | 2023-06-14 | 7 | 19 | 24 | 18 | **7,306.0** | 304.4 |
| 9 | `35056` | 2023-02-27 | 24 | 24 | 24 | 21 | **7,228.0** | 301.2 |
| 10 | `38912` | 2023-06-08 | 9 | 21 | 23 | 19 | **7,220.0** | 313.9 |

---

## 5. Vertical Tier Retrieval Penalties (Level $z > 1$)
Picking from upper shelf tiers incurs ergonomics and ladder-handling time delays:
- **Level 1 (Ground / Eye Level)**: Baseline pick setup time (~12.0 seconds).
- **Level 2 (Reach / Mezzanine)**: +5.0 seconds ladder climb / reach penalty.
- **Level 3 & 4 (Upper Reserve)**: Serviced during replenishment cycles rather than standard manual trolley waves.
- In `wave_travel()`, a configurable parameter `vertical_penalty_sec=5.0` calculates the exact time overhead per wave:
  $$\text{Penalty Time} = \sum_{p \in \text{Picks}} \max(0, z_p - 1) \times \text{penalty\_sec}$$

