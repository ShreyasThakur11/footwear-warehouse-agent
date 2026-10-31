# Model Card: Cube-per-Order Index (COI) & Family-Based Storage Re-Slotting Model

## 1. Model Overview
- **Model Name**: Cube-per-Order Index (COI) & Footwear Family Co-location Slotting Engine (`warehouse_ai.models.slotting`)
- **Model Type**: Combinatorial Storage Assignment Heuristic + Linear Sum Assignment + Multi-Policy Wave Replay Simulator
- **Purpose**: Optimize the physical assignment of 208 footwear product references and their respective shoe size runs across 2,293 warehouse shelf locations.
- **Version**: 1.0.0

## 2. Slotting Principles & Formulation
### Cube-per-Order Index (COI)
For each SKU-size variant $i$, the allocation priority is ranked via:
$$\text{COI}_i = \frac{V_i}{f_i}$$
where $V_i$ represents required storage volume (slots) and $f_i$ represents empirical picking frequency. Variants with the lowest COI (high frequency per unit space) are assigned to shelf locations with minimum Dijkstra travel distance from depot `CC-08` on ergonomic picking Levels 1–2 ($z=1$).

### Optimised-FAMILY Architecture
In footwear logistics, customer orders frequently contain adjacent sizes of the same model or co-purchased accessories. Optimised-FAMILY co-locates complete shoe families (e.g. all size runs 8.0 through 12.0 of reference `8N10W9`) in contiguous bays in Aisles A–D closest to the dispatch staging line.

## 3. Storage Policy Benchmarks (300 Wave Simulation)
| Storage Policy | Mean Wave Walking (m) | Total Labor Hours | Distance Saving vs Random | Labor Saving vs Random |
|---|---|---|---|---|
| `random` (Baseline) | 3,811.3 m | 39.0 h | — | — |
| `dedicated` | 3,902.6 m | 39.4 h | −2.4% | −1.0% |
| `hybrid` | 3,190.5 m | 36.8 h | +16.3% | +5.7% |
| `class_based` (ABC) | 2,750.7 m | 35.2 h | +27.8% | +9.9% |
| `optimised_coi` | **1,108.6 m** | **26.4 h** | **+70.9%** | **+32.3%** |
| `optimised_family` | **998.4 m** | **24.8 h** | **+73.8%** | **+36.4%** |

## 4. Practical Implementation & Relocation Matrix
Relocating only **6,736 total units (16.3% of stock)** into 186 golden forward locations unlocks **80% of travel gains**. A two-phase relocation plan minimizes floor disruption:
- **Phase 1**: Relocate top 20 Class A footwear references (3,818 unit moves = 1,909 swaps). Payback in 80 working days.
- **Phase 2**: Reorganize secondary Class B family clusters during low-volume seasonal windows.

