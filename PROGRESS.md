# Project Progress & Roadmap

## 1. Roadmap & Milestone Checklist

- [x] **Milestone 1: Project Skeleton & Data Ingestion**
  - [x] Repo directory structure with `__init__.py` files
  - [x] `pyproject.toml` and `.gitignore` configuration
  - [x] `.env.example` and `configs/default.yaml`
  - [x] Config loader (`src/warehouse_ai/config.py`)
  - [x] 9 CSV data loaders (`src/warehouse_ai/data/loaders.py`) with BOM, whitespace, snake_case handling
  - [x] Support points navigation coordinate parsing (LC, CC, RC corridors)
  - [x] Data inspection CLI (`scripts/inspect_data.py`)
  - [x] Unit test suite with fixtures (`tests/test_loaders.py`)
  - [x] Raw data guide (`data/raw/README.md`)

- [x] **Milestone 2: Data Cleaning, Size Decoding & Processed Parquet Tables**
  - [x] Empirical shoe size decoding algorithm (`src/warehouse_ai/data/cleaning.py`)
  - [x] Location code parsing into aisle, bay, level, slot + coordinate joins
  - [x] Generate 8 processed Parquet tables in `data/processed/` (`orders_clean`, `picks_clean`, `waves`, `daily`, `hourly`, `products`, `locations`, `storage_long`)
  - [x] Industrial validation suite (`src/warehouse_ai/data/validate.py` -> `reports/data_quality.md`)
  - [x] End-to-end pipeline script (`scripts/build_processed.py`)
  - [x] Unit tests for size decoding and location parsing (`tests/test_cleaning.py`)
  - [x] Size mapping documentation (`docs/assumptions.md` & `reports/size_mapping.md`)

- [x] **Milestone 3: Exploratory Data Analysis & Workload Drivers**
  - [x] Reusable EDA metrics module (`src/warehouse_ai/analysis/eda.py`)
  - [x] Automated report generator (`scripts/eda_report.py`)
  - [x] High-resolution charts in `reports/figures/` (daily trends, arrival heatmap, distributions, operator productivity proxy, Pareto SKU curves, picking heatmaps, storage policy coverage)
  - [x] Comprehensive EDA report with business findings & modeling implications (`reports/eda.md`)
  - [x] Unit tests for EDA metric modules (`tests/test_eda.py`)

- [ ] **Milestone 4: Storage Allocation Optimization (Reslotting)**
  - [ ] Demand profiling, Pareto ABC, and COI (Cube-per-Order Index) calculation
  - [ ] Family-based co-location model (Optimised-FAMILY)
  - [ ] Re-slotting simulation & stock relocation matrix

- [ ] **Milestone 5: Pick Routing & TSP Algorithms**
  - [ ] Graph-based warehouse navigation (LC, CC, RC cross-aisles)
  - [ ] S-Shape (Serpentine) heuristic
  - [ ] Nearest-Neighbour + 2-opt local search solver
  - [ ] Out-of-sample test wave benchmarking

- [ ] **Milestone 6: Digital Twin Simulation & Agentic Orchestration**
  - [ ] Wave cycle time model (travel time + pick setup + handling)
  - [ ] Multi-agent orchestration via LangGraph (Planner, Data Analyst, Slotting Specialist, Routing Optimizer)
  - [ ] Interactive Streamlit visualizer & scenario comparison dashboard

---

## 2. Key Results & Benchmarks
- **Raw Dataset Scope**: 122,370 customer order lines, 215,192 pick actions across 7,341 picking waves, 2,293 shelf locations, 208 products, 22 operators.
- **Empirical Size Match Rate**: 99.28% exact multiset match between orders and picks across 59,007 wave-reference groups.
- **Pareto Demand Skew**: 20% of SKU catalog drives 80.0% of total pick units; sizes 8.5–11.0 account for >65% of volume.
- **Workload Release Shock**: Over 90% of daily orders arrive instantaneously in the 07:00 AM morning wave.
- **Physical Layout Geometry**: 17 aisles (A–Q), 25 racks, 5 vertical levels (Levels 1–2 manual picking zone, Levels 3–4 replenishment reserve).
- **Navigation Network**: 44 corridor waypoints across Left Corridor (x≈66), Center Corridor (x≈403, I/O depot at CC-08), and Right Corridor (x≈686).

---

## 3. Assumptions Log
- **Size Mapping**: Order sizes without decimal points represent either whole sizes (e.g., 9 -> 9.0) or half sizes multiplied by 10 (e.g., 105 -> 10.5, 85 -> 8.5). Verified empirically by matching wave-reference multisets between orders and picks.
- **Trolley Capacity**: Picking cart capacity is strictly bounded at 27 pairs of footwear. Waves exceeding 27 units require multi-trip logistics.
- **Support Points Orientation**: In `Support_Points_Navigation.csv`, coordinates precede their corridor label (e.g. `(66.0, -29.0, 1.0);LC-01`).
- **Productivity Proxy**: Daily units processed divided by active operators on duty serves as empirical proxy for labor productivity in the absence of per-item timestamps.

---

## 4. Open Issues & Notes
- Operator picking speed variance: actual pick duration has no individual per-item timestamps; total daily units vs active operators serves as empirical productivity proxy.
- Unreconciled pick records: 77 waves present in orders lack matching pick logs (cancelled orders or pre-staged batches). Handled gracefully with audit logging.
- 22 pick locations are non-rack staging areas (`ZN-COR`, `EX-01`, etc.) outside the standard 2,292 rack locations.

---

## 5. Session Log

| Date | Task | Changes | Status |
|------|------|---------|--------|
| 2026-10-31 | Skeleton Setup | Initialized folders, pyproject.toml, configs, loaders, tests | Done |
| 2026-10-31 | Data Cleaning & Processed Tables | Size decoding algorithm, location parsing, parquet builds, validation report | Done |
| 2026-10-31 | EDA & Workload Drivers | Reusable EDA modules, visualizer script, 7 charts, eda.md | Done |

---

## 6. Next Steps
1. Implement Milestone 4: Storage Allocation Optimization (Pareto ABC classification, COI, and Optimised-FAMILY slotting algorithm).
2. Implement Milestone 5: Pick Routing & TSP Algorithms (Navigation graph, S-Shape heuristic, and NN 2-opt solver).
3. Implement Milestone 6: Multi-agent LangGraph workflow and interactive Streamlit digital twin.
