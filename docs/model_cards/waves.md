# Model Card: Order Wave Batching Algorithms & Operator Workload Balancer

## 1. Model Overview
- **Model Name**: Dynamic Order Batching & Longest Processing Time (LPT) Wave Dispatcher (`warehouse_ai.models.waves`)
- **Model Type**: Combinatorial Order Batching Heuristics (FCFS, Seed+Savings, Aisle-Clustering) + LPT Operator Assignment
- **Purpose**: Group open customer orders into pick waves respecting trolley physical capacity ($c = 27$ pairs) and balance picking duration across active operators.
- **Version**: 1.0.0

## 2. Batching Algorithms
1. **First-Come, First-Served (FCFS)**: Sequential grouping of orders until the 27-pair cart capacity or order ceiling is reached. Serves as commercial WMS baseline.
2. **Seed + Savings Heuristic (`seed_savings`)**:
   - Selects a "seed" order with pick locations in the farthest aisle from depot `CC-08`.
   - Iteratively adds candidate unassigned orders that maximize travel distance savings:
     $$S(o_1, o_2) = D(o_1) + D(o_2) - D(o_1 \cup o_2)$$
   - Stops when capacity constraint is reached.
3. **Aisle-Clustering Heuristic (`aisle_cluster`)**: Encodes each order as a 17-dimensional aisle visit vector and groups orders with highest cosine similarity.

## 3. Operator Workload Balancing
Uses the Longest Processing Time (LPT) greedy multiprocessor scheduling rule:
- Computes calibrated labor duration for every formed wave using `LaborModel.wave_time`.
- Sorts waves in descending order of estimated duration.
- Greedily assigns each wave to the operator with the minimum cumulative scheduled labor time.

## 4. Benchmark Performance (5 Busiest Historical Operating Days)
| Metric | Historical Baseline | Seed + Savings | Delta (%) |
|---|---|---|---|
| **Total Walking Distance** | 32,440 m | 22,870 m | **−29.5% walking** |
| **Total Picking Labor** | 34.8 hours | 27.2 hours | **−21.8% labor** |
| **Total Waves Dispatched** | 193 waves | 132 waves | **−31.6% wave trips** |
| **Max/Min Operator Load Ratio**| 1.48 (unbalanced) | 1.02 (near-perfect) | **Balanced workload** |

