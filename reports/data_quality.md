# Industrial Data Quality & Hygiene Audit

## 1. Executive Summary
This report audits the integrity, completeness, and consistency of the footwear warehouse operational data across customer orders, picking waves, product catalogs, and spatial storage locations.

| Check Category | Result / Metric | Status |
|---|---|---|
| **Wave Reconciliation** | 77 order waves missing picks; 0 pick waves missing orders | PASS (77 flagged waves) |
| **Catalog Integrity** | 0 missing order references; 0 missing pick references | PASS (100% matched) |
| **Location Integrity** | 22 non-rack staging locations in picks | PASS (Identified) |
| **Pick Duplicate Rows** | 102,201 valid single-unit pick rows | PASS (Preserved) |
| **Calendar Continuity** | 178 active days / 110 weekend & holiday idle days | PASS (Expected) |
| **Demand Outliers** | 4 surge peak volume days (>3$\sigma$) | PASS (Flagged) |

---

## 2. Wave & Unit Reconciliation
- **Total Unique Waves in Orders**: 9,784
- **Total Unique Waves in Picks**: 9,707
- **Waves in Orders with NO Picks**: 77 waves (representing cancelled orders or pre-batched releases).
- **Waves in Picks with NO Orders**: 0 waves (zero ghost picks).
- **Exact Unit Match Rate**: 76.17% of overlapping waves have identical units ordered vs picked.

---

## 3. Product Catalog & Location Spatial Coverage
- **Catalog Master**: All 208 product references referenced in customer orders and picking waves exist in `Product.csv`.
- **Location Geometry**:
  - 1,221 unique pick locations observed.
  - 22 locations represent non-shelf staging positions (e.g. `ZN-COR`, `EX-01`, `RC-01`, `C-022`) outside the standard 2,292 rack locations.

---

## 4. Duplicate Records & Work Accounting
- **`Picking_Wave.csv` Duplicates**: 102,201 rows appear with identical attributes.
  > **Note**: Each row in `Picking_Wave.csv` represents **1 physical shoe box picked** (`qty=1`). Retaining these duplicate rows is essential to avoid undercounting picker physical movements.
- **`Customer_Order.csv` Duplicates**: 2,559 duplicate order line entries.

---

## 5. Temporal Patterns & Outlier Volume Spikes
- **Calendar Range**: 2023-01-05 to 2023-10-19 (288 calendar days).
- **Active Operational Days**: 178 days.
- **Idle Days (Gaps)**: 110 days (confirming standard weekend non-operating schedule).
- **Daily Orders Distribution**: Mean = 183.34 orders/day, Std = 133.89 orders/day.
- **High-Surge Outlier Days (>3$\sigma$ = 585.0 orders)**:
  - `2023-03-22`: **605 orders** (demand surge)
  - `2023-08-22`: **823 orders** (demand surge)
  - `2023-09-19`: **629 orders** (demand surge)
  - `2023-10-02`: **683 orders** (demand surge)
