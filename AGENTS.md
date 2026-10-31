# Footwear Warehouse Optimisation — Agent Architecture & Operating Manual

## 1. Project Vision
An industrial-grade, agentic AI platform for footwear warehouse storage optimisation — tackling SKU re-slotting, pick wave routing, and simulation.
The goal is cutting picker walking distance by ~60% and pick cycle time by ~26% using real warehouse management system (WMS) data:
- 122,370 customer order lines
- 215,192 picking wave actions across 7,341 picking waves
- 2,293 shelf locations across 25 racks and 17 aisles
- 208 footwear product references and 22 operators

## 2. System Architecture

```
Footwear_Wearhouse-Optimization/
├── AGENTS.md                    # Agent instructions, architecture, operational standards
├── PROGRESS.md                  # Milestone checklists, assumptions, session logs, next steps
├── pyproject.toml               # Package specifications (warehouse_ai) & dependencies
├── README.md                    # Main user documentation & quickstart
├── .gitignore                   # Version control exclusions
├── .env.example                 # Environment variables template
├── configs/
│   └── default.yaml             # Core configurations (paths, seed, warehouse geometry, LLM)
├── data/
│   ├── raw/                     # 9 raw CSV files (git-ignored, see README.md)
│   └── processed/               # Cleaned, validated Parquet tables
├── docs/
│   └── assumptions.md           # Engineering & domain assumptions log
├── reports/
│   ├── figures/                 # EDA and scenario visualization charts (.png)
│   ├── size_mapping.md          # Shoe size normalization & decoding audit
│   ├── data_quality.md          # Industrial data validation report
│   └── eda.md                   # Workload driver & exploratory analysis report
├── scripts/
│   ├── inspect_data.py          # Quick raw data inspector
│   ├── build_processed.py       # End-to-end data processing pipeline
│   └── eda_report.py            # Generates eda.md and analytical figures
├── src/
│   └── warehouse_ai/
│       ├── __init__.py
│       ├── config.py            # Pydantic & YAML config loader
│       ├── data/
│       │   ├── __init__.py
│       │   ├── loaders.py       # Raw file ingestion & format parsing
│       │   ├── cleaning.py      # Size decoding, location parsing, table builders
│       │   └── validate.py      # Data hygiene, reconciliation & sanity checks
│       ├── analysis/
│       │   ├── __init__.py
│       │   └── eda.py           # Reusable EDA metric generators
│       ├── features/            # Feature engineering for demand & slotting
│       ├── optimization/        # Slotting algorithms (ABC, COI, Family) & TSP routing
│       ├── simulation/          # Route simulation & pick duration digital twin
│       ├── agents/              # LangGraph orchestration & LLM reasoning agents
│       ├── dashboard/           # Streamlit app & interactive components
│       └── utils/               # Geometry, graph calculations, math utilities
└── tests/
    ├── __init__.py
    ├── fixtures/                # Sample CSV slices for fast, reproducible tests
    ├── test_loaders.py          # Loader unit tests
    └── test_cleaning.py         # Size decoding and table generation tests
```

## 3. Data Dictionary & Storage Policies
The facility features:
- **I/O Depot**: Node `CC-08` at coordinate `(403.0, 631.0, 1.0)`.
- **Vertical Tiers**: Levels 0–2 for active ground/mezzanine manual picking; Levels 3–4 for reserve forklift replenishment.
- **Storage Policies Tested**:
  1. `Random`: Empirical baseline slotting.
  2. `Class_Based`: ABC velocity classification based on overall SKU volume.
  3. `Dedicated`: Single-SKU allocation per location.
  4. `Hybrid`: Combined dedicated fast-movers with flexible general storage.
  5. `Optimised-FAMILY`: Co-locates footwear product families and size runs near the dispatch corridor.

## 4. Agent Guidelines & Protocols
1. **Never guess data silently**: All domain assumptions, size decodings, or coordinate interpretations must be validated empirically and documented in `docs/assumptions.md` and relevant reports.
2. **Reconciliation First**: Pick counts and order counts must be compared at the wave level. Discrepancies (missing picks, cancelled orders) must be flagged in `reports/data_quality.md`.
3. **Reproducibility**: Use seed `42` where stochastic methods exist. All tests must pass with `pytest`.
4. **Git Hygiene**: Pull origin before beginning, maintain clean commits, and log actions in `PROGRESS.md`.

