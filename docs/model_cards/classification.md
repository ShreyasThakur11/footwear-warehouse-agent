# Model Card: Multi-Criteria Inventory Classification (Pareto ABC & XYZ Variability)

## 1. Model Overview
- **Model Name**: Dual-Axis Inventory Demand Profiler & Master Data Auditor (`warehouse_ai.models.classification`)
- **Model Type**: Empirical Cumulative Volume Pareto Profiler (ABC) + Coefficient of Variation Demand Dispersal (XYZ)
- **Purpose**: Stratify SKU catalog into operational velocity tiers and audit inconsistencies in legacy WMS master data.
- **Version**: 1.0.0

## 2. Classification Methodology
### ABC Velocity Classification
- **Class A**: Top cumulative **80.0%** of total pick unit volume (accounts for 16.5% of SKU variants).
- **Class B**: Next cumulative **15.0%** of total pick unit volume (accounts for 23.5% of SKU variants).
- **Class C**: Remaining **5.0%** of total pick unit volume (accounts for 60.0% of long-tail variants).

### XYZ Demand Variability Classification
Classified via the coefficient of variation of weekly demand: $CV = \sigma_D / \mu_D$:
- **Class X (Stable Demand)**: $CV \le 0.50$ (smooth cadence, predictable safety buffers).
- **Class Y (Moderate Volatility)**: $0.50 < CV \le 1.00$ (seasonal or intermittent runs).
- **Class Z (Extreme Lumpiness)**: $CV > 1.00$ (highly erratic, make-to-order characteristics).

## 3. Catalog Audit & Master Data Discrepancy
Comparing empirical demand classifications against `Product.ABCCOD` in legacy WMS master data reveals:
- **Master Data Agreement**: Only **53.8% concordance** between recorded code and empirical velocity.
- **Hidden Fast Movers**: 19 high-velocity footwear references driving top picking traffic are misclassified as Class C in master data, resulting in remote upper-rack placement.

## 4. Operational Role in Digital Twin
- Dictates safety stock coverage factors in `replenishment.py` ($z_A = 2.05$, $z_B = 1.65$, $z_C = 1.28$).
- Directs golden-zone shelf allocation in `slotting.py`.

