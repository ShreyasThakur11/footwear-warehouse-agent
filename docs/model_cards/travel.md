# Model Card: Warehouse Navigation Graph & Dijkstra Travel Time Model

## 1. Model Overview
- **Model Name**: Warehouse Floor Network Graph & Shortest-Path Tour Heuristics (`warehouse_ai.models.travel`)
- **Model Type**: Graph-theoretic Network Model + Dijkstra All-Pairs Shortest Path + Traveling Salesperson Problem (TSP) Heuristics
- **Purpose**: Compute physical travel distances and walking trajectories for order pickers across the multi-tier footwear layout.
- **Version**: 1.0.0

## 2. Model Architecture & Geometry
The physical facility layout comprises:
- **Corridors**: Left Corridor (`LC`), Center Corridor (`CC`, with depot `CC-08` at $x=403, y=631$), and Right Corridor (`RC`).
- **Aisles**: 17 horizontal aisles (A through Q) spanning 25 vertical rack bays.
- **Waypoints**: 44 corridor navigation waypoints connecting aisle entry and exit nodes.
- **Shelf Locations**: 2,292 projected storage bin locations.

### Coordinate Conversion Standards
- Aisle spacing: 0.0732 m/unit along horizontal axis; 0.03222 m/unit along vertical axis.
- Vertical level reach penalty: +5.0 seconds per level for shelves above tier 1 ($z > 1$).

## 3. Tour Routing Algorithms
1. **S-Shape (Serpentine)**: Traverses entire aisles containing requested picks, alternating entry corridor per aisle.
2. **Nearest Neighbor (NN)**: Greedily moves to the nearest unvisited pick location from the current cart position.
3. **Largest Gap**: Evaluates whether traversing completely or returning via the same corridor minimizes total aisle travel.
4. **2-Opt TSP Local Search (`tour_nn_2opt`)**: Iteratively uncrosses pairwise tour edges until no 2-edge swap improves overall tour distance.

## 4. Key Performance Benchmarks
- **Free Win (No Stock Relocation)**: Applying NN + 2-opt to historical AS-IS pick lists reduces walking distance by **14.6%** (166.2 m down to 142.0 m per wave) across 7,323 historical waves.
- **Optimised-FAMILY Routing**: Walking distance drops by **64.7%** (58.7 m per wave) when coupled with family-based storage slotting.
- **Statistical Significance**: Paired Wilcoxon signed-rank tests confirm $p < 0.001$ across all comparisons.

## 5. Limitations
- Assumes deterministic 1.0 m/s walking velocity with cart.
- Does not model dynamic aisle blocking caused by simultaneous two-way cart traffic.

