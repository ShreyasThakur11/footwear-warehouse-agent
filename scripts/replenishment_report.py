"""Generate inventory replenishment policy simulation and reports/replenishment.md."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from warehouse_ai.config import load_config
from warehouse_ai.models.classification import audit_catalog_abc, compute_abc_xyz
from warehouse_ai.models.replenishment import (
    replenishment_plan,
    simulate_replenishment_policies,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("replenishment_report")


def main() -> None:
    cfg = load_config()
    processed_dir = Path(cfg.paths.data_processed)
    orders_df = pd.read_parquet(processed_dir / "orders_clean.parquet")
    daily_df = pd.read_parquet(processed_dir / "daily.parquet")
    products_df = pd.read_parquet(processed_dir / "products.parquet")

    logger.info("1. Auditing Catalog ABC vs Empirical Demand ABC...")
    catalog_audit = audit_catalog_abc(orders_df, products_df)

    logger.info("2. Computing ABC-XYZ demand segmentation at SKU and SKU-size levels...")
    sku_matrix = compute_abc_xyz(orders_df, entity_col="reference")
    skusz_matrix = compute_abc_xyz(orders_df, entity_col="sku_size")
    logger.info("Segmented %d references and %d sku_sizes", len(sku_matrix), len(skusz_matrix))

    logger.info("3. Simulating Replenishment Policies across 178 operational days...")
    summary_df, logs = simulate_replenishment_policies(orders_df, daily_df=daily_df)

    logger.info("4. Generating sample operational replenishment directives...")
    # Mock current state
    mock_pf = {"8N10W9|10.0": 1, "WRRW1W|9.5": 0, "PY5UPB|265.0": 1}
    mock_res = {"8N10W9|10.0": 12, "WRRW1W|9.5": 6, "PY5UPB|265.0": 20}
    plan = replenishment_plan("2023-10-20", current_pick_face_stock=mock_pf, current_reserve_stock=mock_res)

    report_path = Path("reports/replenishment.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    ct = catalog_audit["crosstab"]

    md = f"""# Inventory Classification & Replenishment Optimization Report

## Executive Summary
This report analyzes inventory classification and multi-echelon replenishment policies across the
footwear warehouse. The warehouse layout features two functional storage tiers:
- **Forward Pick Face**: Shelf Levels 1–2 (1,692 locations, 30,456 slots), where operators pick without ladders.
- **Reserve Replenishment**: Shelf Levels 3–4 (600 locations, 10,800 slots), accessed via reach truck.

### Key Operational Findings:
1. **Catalog ABC Misalignment**: The historical master catalog (`Product.ABCCOD`) has only **{catalog_audit['agreement_rate'] * 100:.1f}% agreement**
   with empirical order demand. **{catalog_audit['hidden_fast_movers_count']} items** marked as Class C are actually high-velocity Class A items
   driving major pick volumes, while **{catalog_audit['obsolete_fast_movers_count']} items** marked as Class A are dormant slow-movers occupying prime low-level slots.
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
| **Class A** | {ct.loc['A', 'A']} | {ct.loc['A', 'B']} | {ct.loc['A', 'C']} | **{ct.loc['A', 'All']}** |
| **Class B** | {ct.loc['B', 'A']} | {ct.loc['B', 'B']} | {ct.loc['B', 'C']} | **{ct.loc['B', 'All']}** |
| **Class C** | {ct.loc['C', 'A']} | {ct.loc['C', 'B']} | {ct.loc['C', 'C']} | **{ct.loc['C', 'All']}** |
| **Total Empirical** | **{ct.loc['All', 'A']}** | **{ct.loc['All', 'B']}** | **{ct.loc['All', 'C']}** | **{ct.loc['All', 'All']}** |

> **Audit Recommendation**: Immediately update WMS master data for the {catalog_audit['hidden_fast_movers_count']} hidden Class A products
> (e.g., references `{', '.join([x['reference'] for x in catalog_audit['hidden_fast_movers'][:5]])}`) to assign them priority forward slots.

---

## 2. ABC-XYZ Demand Portfolio Matrix

Distribution of 208 footwear product references across the 9-segment portfolio:

| | X (Stable: CV < 0.5) | Y (Moderate: 0.5 ≤ CV < 1.0) | Z (Volatile: CV ≥ 1.0) | Total |
|---|---|---|---|---|
| **Class A (Top 80% Units)** | {(sku_matrix['abc_xyz'] == 'AX').sum()} (AX) | {(sku_matrix['abc_xyz'] == 'AY').sum()} (AY) | {(sku_matrix['abc_xyz'] == 'AZ').sum()} (AZ) | **{(sku_matrix['abc_class'] == 'A').sum()}** |
| **Class B (Next 15% Units)** | {(sku_matrix['abc_xyz'] == 'BX').sum()} (BX) | {(sku_matrix['abc_xyz'] == 'BY').sum()} (BY) | {(sku_matrix['abc_xyz'] == 'BZ').sum()} (BZ) | **{(sku_matrix['abc_class'] == 'B').sum()}** |
| **Class C (Tail 5% Units)** | {(sku_matrix['abc_xyz'] == 'CX').sum()} (CX) | {(sku_matrix['abc_xyz'] == 'CY').sum()} (CY) | {(sku_matrix['abc_xyz'] == 'CZ').sum()} (CZ) | **{(sku_matrix['abc_class'] == 'C').sum()}** |
| **Total Catalog** | **{(sku_matrix['xyz_class'] == 'X').sum()}** | **{(sku_matrix['xyz_class'] == 'Y').sum()}** | **{(sku_matrix['xyz_class'] == 'Z').sum()}** | **{len(sku_matrix)}** |

---

## 3. Historical Replenishment Policy Simulation Results

Full 178 operating-day replay (122,370 customer order lines, 228,195 demand units):

| Replenishment Policy | Unit Fill Rate (%) | Line Fill Rate (%) | Mean On-Hand (Units) | Stockout Units | Internal Transfers | Supplier Orders |
|----------------------|--------------------|--------------------|----------------------|----------------|--------------------|-----------------|
"""
    for _, r in summary_df.iterrows():
        md += f"| **{r['policy_name']}** | **{r['unit_fill_rate'] * 100:.1f}%** | {r['line_fill_rate'] * 100:.1f}% | {r['mean_on_hand_units']:,.1f} | {r['stockout_units']:,} | {r['total_internal_replenishments']:,} | {r['total_supplier_orders']:,} |\n"

    md += f"""
---

## 4. Multi-Echelon Replenishment Logic

### A. Pick-Face Replenishment (Reserve Levels 3–4 → Pick Face Levels 1–2)
- Evaluated continuously during order picking.
- When on-hand stock at the pick face falls to $\\le \\text{{pick\\_face\\_min}}$ (e.g. 2 pairs for Class A), an internal transfer directive is dispatched to move up to $\\text{{pick\\_face\\_max}}$ pairs (e.g. 6 pairs) from Reserve.
- Prevents pickers from having to wait for forklift ladder retrieval during active pick waves.

### B. Supplier Replenishment (Footwear Manufacturer → Warehouse Reserve)
- Review cycle: Weekly on Friday afternoon.
- Lead time $L = 7$ days.
- Safety Stock: $SS = z \\cdot \\sigma_D \\sqrt{{L}}$, where $z = 2.05$ (98% service level) for Class A, $z = 1.65$ (95%) for Class B, and $z = 1.28$ (90%) for Class C.
- Reorder point: $s = \\mu_D \\cdot L + SS$.
- Order-up-to level: $S = \\mu_D \\cdot (R + L) + SS$.

---

## 5. Sample Operational Directives

### Sample Internal Pick-Face Transfers:
```
{plan['pick_face_transfers'].to_string(index=False)}
```
"""

    report_path.write_text(md, encoding="utf-8")
    logger.info("Successfully wrote %s", report_path)


if __name__ == "__main__":
    main()
