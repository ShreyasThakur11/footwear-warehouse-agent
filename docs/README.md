# Documentation

## Contents

| Document | Description |
|---|---|
| [Report](../report/) | Full written report (PDF) with methodology, findings, and recommendations |
| [Notebook](../v3.ipynb) | Complete analysis pipeline — one run reproduces all results, figures, and exports |
| [Dashboard](https://shreyasthakur11.github.io/Footwear_Wearhouse-Optimization/) | Interactive KPI dashboard with key findings and visual summaries |

## Methodology Overview

This analysis applies warehouse operations research techniques to a real-world safety-boot distribution centre:

1. **Data ingestion** — Robust parser for mixed-delimiter CSVs with automatic encoding detection
2. **Warehouse reconstruction** — Physical layout modelled from coordinate data; aisle network with shortest-path routing
3. **Demand analysis** — ABC classification (80/95% Pareto cuts) with train/test temporal split
4. **Storage optimisation** — Six storage policies benchmarked (Random, Class-Based, Dedicated, Hybrid, Optimised-COI, Optimised-FAMILY)
5. **Route optimisation** — Nearest-neighbour + 2-opt heuristic vs serpentine vs recorded WMS sequence
6. **Economic quantification** — FTE reduction, CAD/year savings, implementation cost (stock moves)

## Data Source

Public dataset from Mendeley Data:
> de Assis, de Paula Ferreira & Ouhimmou (2025), *Data in Brief* 61:111837, **CC BY 4.0**

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Download data from Mendeley, place CSVs in data/ folder
# Then run the notebook
jupyter notebook v3.ipynb
```

Full run: ~6–7 minutes. Quick trial: set `MAX_WAVES=1500` in `CONFIG`.
