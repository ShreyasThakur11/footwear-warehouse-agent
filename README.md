# FootWear_Wearhouse_Optimization
##This is created with purpose of academic learning and code is an open source to anyone who want to learn and whats going on

# Warehouse Picking Optimisation: Slotting and Routing

Re-slotting and re-routing a safety-boot warehouse to cut picker walking distance. Built from real WMS data (9,707 picking waves, 215,192 units) and a single reproducible Python notebook.

> **Headline result:** a new forward-zone slotting plan plus optimised routing cuts walking per wave from **166 m to 67 m (-59.5%)** and picking time by **26.3%**. The saving holds out-of-sample (**-58.8%** on test waves the layout never saw). Re-routing alone, with no stock moved, gives **-14.6%**.

---

## 1. Problem

The warehouse (a safety-boot manufacturer in Sherbrooke, Quebec) runs **random storage** with mixed shelving. Pickers follow the WMS sequence and walk long routes from a single I/O depot.

Questions answered:
1. How much walking is wasted by the current storage policy and route sequence?
2. Which storage arrangement is best: Random, Class-Based, Dedicated or Hybrid, or a new design?
3. How much of the saving comes from **routing** versus **slotting**?
4. What does it cost to implement (stock moves) and what is it worth (labour, CAD/year)?

## 2. Data

Public dataset: de Assis, de Paula Ferreira & Ouhimmou (2025), *Data in Brief* 61:111837 (Mendeley Data, **CC BY 4.0**).

| File | Content |
|---|---|
| `Product.csv`, `Customer_Order.csv` | Product master and customer orders |
| `Picking_Wave.csv` | Pick lists per wave (15-27 items, trolley capacity 27) |
| `Storage_Location.csv`, `Support_Points_Navigation.csv` | 2,293 locations, coordinates and aisle/cross-aisle support points |
| `Random_/Class_Based_/Dedicated_/Hybrid_Storage.csv` | The four storage policies from the case |

> The raw CSVs are **not** included in this repo. See [How to run](#5-how-to-run) for where to get them.

**Key case facts:** 25 racks, 17 parallel aisles, 3 cross aisles, 4 levels (levels 1-2 manual picking, levels 3-4 forklift reserve), single I/O depot at support point `CC-08`. There are no pick timestamps, so times come from an engineering time model.

## 3. Approach

1. **Clean and load.** Robust CSV reader handles mixed `;`/`,` delimiters, old-Mac line endings and encodings, and logs every fix in a data-quality table.
2. **Rebuild the warehouse.** Locations are calibrated to metres from coordinates and an aisle network is built (aisles, cross aisles, I/O). Walking distance is shortest path on this network.
3. **Demand and ABC.** Pick-visit demand per SKU and reference, ABC classes (80% / 95% cuts), and a **70/30 train/test split** by wave.
4. **Storage scenarios.** The four case policies plus two new designs: **Optimised-COI** (ranks items by pick visits per pick-face slot) and **Optimised-FAMILY** (same, but keeps all sizes of a model together). The best variant is chosen on **training waves only**.
5. **Routing.** Three methods are compared: the recorded WMS sequence, serpentine, and nearest-neighbour + 2-opt.
6. **Practical re-shuffle plan.** Only the forward zone is re-slotted via swaps, with class A items first.
7. **Evaluation.** Saving decomposition (routing vs slotting), paired Wilcoxon tests, sensitivity to walk speed and pick time, daily FTE, order lead time and operator performance.
8. **Economics.** Labour hours, FTE and CAD/year.

**Time model assumptions:** walk 1.0 m/s, 10 s per stop, 6 s per unit, 60 s wave setup, 7.5 productive hours per FTE-day, CAD 25/h, 250 working days. All are editable in `CONFIG` at the top of the notebook.

## 4. Results

| Scenario (NN + 2-opt unless stated) | Mean walking per wave |
|---|---|
| AS-IS, recorded WMS sequence | **166 m** (7.8 min per wave) |
| AS-IS locations, optimised route (quick win) | -14.6% vs AS-IS |
| Case policy: Random | 162 m |
| Case policy: Dedicated | 163 m |
| Case policy: Class-Based | 132 m |
| Case policy: Hybrid | 122 m |
| **New slotting (Optimised-FAMILY) + optimised route** | **67 m (-59.5%)** |

- **Time:** 26.3% less picking time per wave (walking is 35% of picker time today).
- **Out-of-sample:** 58.8% distance saving on test waves.
- **Labour:** about 1.4 picker-hours/day (0.19 FTE), roughly **CAD 8,983/year** and **1,033 km/year** less walking.
- **Effort:** 6,738 unit moves (**16% of stock**), only in the 186 locations nearest the I/O. Class A first.
- **Operators:** route efficiency index 0.81-0.97, workload Gini 0.53.
- **Order lead time:** median 0.15 h as-is vs 0.11 h optimised. Batching wait is the bigger lever.

Figures are in `outputs/figures/`, full tables in `outputs/01_Analysis_Tables.xlsx`.

## 5. How to run

### Requirements
Python 3.9+ with `numpy`, `pandas`, `matplotlib`, `scipy`, `openpyxl` or `xlsxwriter`, and `ezdxf` (for CAD export; the notebook installs it if missing).

```bash
pip install -r requirements.txt
```

### Get the data
Download the dataset from Mendeley Data (see the paper's data link) and place the 9 CSVs, or the zip, in a `data/` folder next to the notebook.

> The notebook tries an automatic download, but it may be blocked (it returned HTTP 403 when I ran it), so manual download is the reliable route.

### Run
- **Google Colab:** upload `v3.ipynb`, put the CSVs in a Drive folder named `warehouse_data` (or upload them when prompted), then run all cells.
- **Locally:** `jupyter notebook v3.ipynb`, or run it as a script. Full run takes about 6-7 minutes (388 s in Colab). Set `MAX_WAVES=1500` in `CONFIG` for a quick trial.

Results are written to `outputs/`.

## 6. Repository structure

```
.
├── README.md
├── v3.ipynb                       # full pipeline, one run reproduces everything
├── requirements.txt
├── report/
│   └── <YOUR_REPORT_NAME>.pdf     # written report
├── outputs/
│   ├── 00_Executive_Summary.md
│   ├── 01_Analysis_Tables.xlsx
│   ├── 02_New_Slotting_Plan.xlsx  # new layout + relocation moves
│   ├── 03_Reconstructed_Picking_Routes.xlsx
│   ├── figures/                   # charts, floor maps, per-level floor plans
│   ├── tables/                    # CSV exports
│   ├── cad/                       # DXF floor plans (current vs optimised)
│   └── run_log.txt
└── data/                          # NOT committed (download separately)
```

## 7. Limitations

- No pick timestamps, so all times are **model estimates** from the assumptions above, not measured.
- Layout is rebuilt from coordinates and calibrated to the stated bay dimensions.
- 89% of picks match an exact SKU in the storage files; the rest fall back to reference level.
- Savings depend on how well 2023 demand predicts future demand (the train/test split checks this, but only within the same year).

## 8. Credits and licence

- Data: de Assis, de Paula Ferreira & Ouhimmou (2025), *Data in Brief* 61:111837, CC BY 4.0. Please cite it if you reuse the data.
- Analysis and code: **Shreyas**, MBA (2026-28), IIM Mumbai.
- Code licence: MIT (see `LICENSE`).
