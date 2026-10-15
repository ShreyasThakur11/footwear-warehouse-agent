<div align="center">

# 👟 Footwear Warehouse Optimisation

Re-slotting and re-routing a safety-boot warehouse to **cut picker walking distance by 59.5%**. Built from real WMS data (9,707 picking waves, 215,192 units) and a single reproducible Python notebook.

Everything is reproducible from one notebook. No proprietary tools, no black-box solvers.

**[Open the Dashboard](https://shreyasthakur11.github.io/Footwear_Wearhouse-Optimization/)** · [Report](report/) · [Notebook](v3.ipynb)

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://python.org)
[![Data: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

</div>

---

## Headline Result

> A new forward-zone slotting plan plus optimised routing cuts walking per wave from **166 m → 67 m (−59.5%)** and picking time by **26.3%**.
>
> The saving holds out-of-sample (**−58.8%** on test waves the layout never saw). Re-routing alone, with no stock moved, gives **−14.6%**.

## What it Does

| Step | Detail |
| --- | --- |
| **Clean & Load** | Robust CSV reader handles mixed `;`/`,` delimiters, old-Mac line endings, encodings — logs every fix |
| **Rebuild Layout** | Calibrates 2,293 locations to metres; builds an aisle network; shortest-path walking distance |
| **Demand & ABC** | Pick-visit demand per SKU, ABC classes (80/95% cuts), 70/30 train/test split by wave |
| **Storage Scenarios** | 6 policies compared: Random, Class-Based, Dedicated, Hybrid, **Optimised-COI**, **Optimised-FAMILY** |
| **Routing** | WMS sequence vs serpentine vs nearest-neighbour + 2-opt |
| **Re-shuffle Plan** | Only the forward zone is re-slotted via swaps, class A items first |
| **Evaluation** | Paired Wilcoxon tests, sensitivity analysis, FTE impact, order lead-time decomposition |
| **Economics** | Labour hours, FTE and CAD/year savings quantified |

## Problem

The warehouse (a safety-boot manufacturer in Sherbrooke, Quebec) runs **random storage** with mixed shelving. Pickers follow the WMS sequence and walk long routes from a single I/O depot.

**Questions answered:**
1. How much walking is wasted by the current storage policy and route sequence?
2. Which storage arrangement is best: Random, Class-Based, Dedicated, Hybrid, or a new design?
3. How much of the saving comes from **routing** versus **slotting**?
4. What does it cost to implement (stock moves) and what is it worth (labour, CAD/year)?

## Data

Public dataset: de Assis, de Paula Ferreira & Ouhimmou (2025), *Data in Brief* 61:111837 (Mendeley Data, **CC BY 4.0**).

| File | Content |
|---|---|
| `Product.csv`, `Customer_Order.csv` | Product master and customer orders |
| `Picking_Wave.csv` | Pick lists per wave (15–27 items, trolley capacity 27) |
| `Storage_Location.csv`, `Support_Points_Navigation.csv` | 2,293 locations, coordinates and aisle/cross-aisle support points |
| `Random_/Class_Based_/Dedicated_/Hybrid_Storage.csv` | The four storage policies from the case |

> The raw CSVs are **not** included in this repo. See [How to Run](#how-to-run) for where to get them.

**Key case facts:** 25 racks · 17 parallel aisles · 3 cross aisles · 4 levels (1–2 manual picking, 3–4 forklift reserve) · single I/O depot at `CC-08`.

## Results

| Scenario (NN + 2-opt unless stated) | Mean walk / wave |
|---|---|
| AS-IS, recorded WMS sequence | **166 m** (7.8 min / wave) |
| AS-IS locations, optimised route (quick win) | −14.6% vs AS-IS |
| Case policy: Random | 162 m |
| Case policy: Dedicated | 163 m |
| Case policy: Class-Based | 132 m |
| Case policy: Hybrid | 122 m |
| **New slotting (Optimised-FAMILY) + optimised route** | **67 m (−59.5%)** |

**Highlights:**
- ⏱️ **Time:** 26.3% less picking time per wave (walking is 35% of picker time today)
- 📊 **Out-of-sample:** 58.8% distance saving on test waves
- 💰 **Labour:** ~1.4 picker-hours/day (0.19 FTE), roughly **CAD 8,983/year** and **1,033 km/year** less walking
- 🏗️ **Effort:** 6,738 unit moves (**16% of stock**), only in the 186 locations nearest the I/O
- 👷 **Operators:** route efficiency index 0.81–0.97, workload Gini 0.53
- 📦 **Lead time:** median 0.15 h as-is → 0.11 h optimised

## How to Run

### Requirements
Python 3.9+ with `numpy`, `pandas`, `matplotlib`, `scipy`, `openpyxl` or `xlsxwriter`, and `ezdxf`.

```bash
pip install -r requirements.txt
```

### Get the Data
Download the dataset from [Mendeley Data](https://data.mendeley.com/) (see the paper's data link) and place the 9 CSVs, or the zip, in a `data/` folder next to the notebook.

> The notebook tries an automatic download, but it may be blocked (HTTP 403), so manual download is the reliable route.

### Run
- **Google Colab:** Upload `v3.ipynb`, put the CSVs in a Drive folder named `warehouse_data` (or upload them when prompted), then run all cells.
- **Locally:** `jupyter notebook v3.ipynb`, or run it as a script. Full run takes about 6–7 minutes. Set `MAX_WAVES=1500` in `CONFIG` for a quick trial.

Results are written to `outputs/`.

## Time Model Assumptions

| Parameter | Value |
|---|---|
| Walk speed | 1.0 m/s |
| Stop time | 10 s/stop |
| Pick time | 6 s/unit |
| Wave setup | 60 s |
| Productive hours/FTE-day | 7.5 h |
| Labour cost | CAD 25/h |
| Working days/year | 250 |

All are editable in `CONFIG` at the top of the notebook.

## Repository Structure

```
.
├── README.md
├── LICENSE
├── requirements.txt
├── v3.ipynb                            # full pipeline, one run reproduces everything
├── report/
│   └── FootWear_Wearhouse_Optimization.pdf   # written report
├── docs/
│   └── README.md                       # documentation index
├── index.html                          # GitHub Pages dashboard
├── assets/
│   └── css/
│       └── style.css                   # dashboard styles
├── outputs/                            # NOT committed (generated by notebook)
│   ├── 00_Executive_Summary.md
│   ├── 01_Analysis_Tables.xlsx
│   ├── 02_New_Slotting_Plan.xlsx
│   ├── 03_Reconstructed_Picking_Routes.xlsx
│   ├── figures/
│   ├── tables/
│   ├── cad/
│   └── run_log.txt
└── data/                               # NOT committed (download separately)
```

## Limitations

- No pick timestamps — all times are **model estimates** from the assumptions above, not measured.
- Layout is rebuilt from coordinates and calibrated to the stated bay dimensions.
- 89% of picks match an exact SKU in the storage files; the rest fall back to reference level.
- Savings depend on how well 2023 demand predicts future demand (the train/test split checks this, but only within the same year).

## Credits & Licence

- **Data:** de Assis, de Paula Ferreira & Ouhimmou (2025), *Data in Brief* 61:111837, CC BY 4.0. Please cite it if you reuse the data.
- **Analysis and code:** **Shreyas**, MBA (2026–28), IIM Mumbai.
- **Code licence:** MIT (see [`LICENSE`](LICENSE)).
