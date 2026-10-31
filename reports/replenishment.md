# Inventory Classification & Replenishment Optimization Report

## Executive Summary
This report analyzes inventory classification and multi-echelon replenishment policies across the
footwear warehouse. The warehouse layout features two functional storage tiers:
- **Forward Pick Face**: Shelf Levels 1–2 (1,692 locations, 30,456 slots), where operators pick without ladders.
- **Reserve Replenishment**: Shelf Levels 3–4 (600 locations, 10,800 slots), accessed via reach truck.

### Key Operational Findings:
1. **Catalog ABC Misalignment**: The historical master catalog (`Product.ABCCOD`) has only **53.8% agreement**
   with empirical order demand. **19 items** marked as Class C are actually high-velocity Class A items
   driving major pick volumes, while **8 items** marked as Class A are dormant slow-movers occupying prime low-level slots.
2. **Fashion Demand Volatility (XYZ)**:
   - At the SKU level: **10 X (stable), 40 Y (moderate), 158 Z (intermittent/volatile)** items.
   - At the SKU-size level: **89.5% (2,253 / 2,517) of SKU-sizes are Class Z**, reflecting the extreme intermittency of individual shoe sizes.
3. **Replenishment Policy Trade-Offs**:
   - **Lean JIT**: Lowest working capital (**26,156 units on-hand**), but achieves only **87.1% unit fill rate** and triggers **38,866 internal replenishment tasks**.
   - **High Service**: High service level (**93.6% unit fill rate**, 95.4% line fill), but ties up **40,122 units of inventory**.
   - **ABC-XYZ Optimized**: Balances service and capital (**92.0% unit fill rate**, 94.1% line fill) with **35,181 units on-hand**, freeing up **~5,000 units of working capital** vs High Service while cutting internal transfers by **26.8% vs Lean JIT**.

---

## 1. Catalog vs Empirical ABC Reconciliation Audit

| Catalog ABC | Empirical A | Empirical B | Empirical C | Total Catalog |
|-------------|-------------|-------------|-------------|---------------|
| **Class A** | 22 | 14 | 8 | **44** |
| **Class B** | 9 | 25 | 36 | **70** |
| **Class C** | 19 | 10 | 65 | **94** |
| **Total Empirical** | **50** | **49** | **109** | **208** |

> **Audit Recommendation**: Immediately update WMS master data for the 19 hidden Class A products
> (e.g., references `6M2FJM, V7JUQL, Q50W5L, B24J86, 0LNUOV`) to assign them priority forward slots.

---

## 2. ABC-XYZ Demand Portfolio Matrix

Distribution of 208 footwear product references across the 9-segment portfolio:

| | X (Stable: CV < 0.5) | Y (Moderate: 0.5 ≤ CV < 1.0) | Z (Volatile: CV ≥ 1.0) | Total |
|---|---|---|---|---|
| **Class A (Top 80% Units)** | 9 (AX) | 17 (AY) | 24 (AZ) | **50** |
| **Class B (Next 15% Units)** | 1 (BX) | 14 (BY) | 34 (BZ) | **49** |
| **Class C (Tail 5% Units)** | 0 (CX) | 9 (CY) | 100 (CZ) | **109** |
| **Total Catalog** | **10** | **40** | **158** | **208** |

---

## 3. Historical Replenishment Policy Simulation Results

Full 178 operating-day replay (122,370 customer order lines, 228,195 demand units):

| Replenishment Policy | Unit Fill Rate (%) | Line Fill Rate (%) | Mean On-Hand (Units) | Stockout Units | Internal Transfers | Supplier Orders |
|----------------------|--------------------|--------------------|----------------------|----------------|--------------------|-----------------|
| **Lean_JIT** | **87.1%** | 90.8% | 26,155.5 | 29,542 | 38,866 | 20,169 |
| **High_Service** | **93.6%** | 95.3% | 40,122.0 | 14,544 | 25,310 | 17,641 |
| **ABC_XYZ_Optimized** | **92.0%** | 94.1% | 35,181.1 | 18,276 | 28,443 | 18,501 |

---

## 4. Multi-Echelon Replenishment Logic

### A. Pick-Face Replenishment (Reserve Levels 3–4 → Pick Face Levels 1–2)
- Evaluated continuously during order picking.
- When on-hand stock at the pick face falls to $\le \text{pick\_face\_min}$ (e.g. 2 pairs for Class A), an internal transfer directive is dispatched to move up to $\text{pick\_face\_max}$ pairs (e.g. 6 pairs) from Reserve.
- Prevents pickers from having to wait for forklift ladder retrieval during active pick waves.

### B. Supplier Replenishment (Footwear Manufacturer → Warehouse Reserve)
- Review cycle: Weekly on Friday afternoon.
- Lead time $L = 7$ days.
- Safety Stock: $SS = z \cdot \sigma_D \sqrt{L}$, where $z = 2.05$ (98% service level) for Class A, $z = 1.65$ (95%) for Class B, and $z = 1.28$ (90%) for Class C.
- Reorder point: $s = \mu_D \cdot L + SS$.
- Order-up-to level: $S = \mu_D \cdot (R + L) + SS$.

---

## 5. Sample Operational Directives

### Sample Internal Pick-Face Transfers:
```
      date     sku_size          source_tier       destination_tier  current_pick_face_units  reserve_available  transfer_units urgency
2023-10-20  8N10W9|10.0 Reserve (Levels 3-4) Pick Face (Levels 1-2)                        1                 12               5  NORMAL
2023-10-20 PY5UPB|265.0 Reserve (Levels 3-4) Pick Face (Levels 1-2)                        1                 20               5  NORMAL
2023-10-20   WRRW1W|9.5 Reserve (Levels 3-4) Pick Face (Levels 1-2)                        0                  6               6  URGENT
```
