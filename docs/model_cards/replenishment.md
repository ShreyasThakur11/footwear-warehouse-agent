# Model Card: Multi-Echelon Forward Pick-Face & Supplier Replenishment Simulator

## 1. Model Overview
- **Model Name**: Two-Tier Inventory Buffer & Periodic Review Replenishment Engine (`warehouse_ai.models.replenishment`)
- **Model Type**: Discrete-Event Inventory Depletion & Replenishment Simulator + Periodic Review $(R, S)$ Policy
- **Purpose**: Balance forward manual picking availability on Levels 1–2 against reserve stock on Levels 3–4 while cutting internal box transfers and working capital.
- **Version**: 1.0.0

## 2. Multi-Echelon Inventory Architecture
1. **Tier 1 (Forward Pick Face)**:
   - Covers shelf Levels 1–2 (30,456 storage slots accessible to manual pickers without ladders).
   - Trigger: When shelf bin quantity drops $\le \text{pick\_face\_min}$, an internal transfer directive is issued to pull from upper Reserve tiers.
   - Target: Tops up bin to $\text{pick\_face\_max}$.
2. **Tier 2 (Reserve Storage)**:
   - Covers upper shelf Levels 3–4 (10,800 storage slots handled via forklift reach trucks).
   - Serves as internal buffer replenishing Tier 1 and receiving inbound supplier purchase orders.
3. **External Supplier Review**:
   - Periodic review every $R = 7$ days with lead time $L = 7$ days.
   - Order-Up-To Level: $S = \mu_D \cdot (R + L) + z \cdot \sigma_D \cdot \sqrt{R + L}$.

## 3. Policy Benchmark Comparison (178 Operating Days)
| Policy | Unit Fill Rate | Line Fill Rate | Avg On-Hand Units | Internal Transfers | Working Capital Posture |
|---|---|---|---|---|---|
| **Lean JIT** | 86.1% | 88.4% | 24,110 | 38,866 | Minimal capital, frequent stockouts |
| **High Service** | 95.2% | 96.5% | 40,250 | 31,200 | Capital intensive, high safety stock |
| **ABC-XYZ Optimized** | **92.0%** | **94.1%** | **35,181** | **28,443 (−26.8%)** | Balanced Pareto service & capital |

## 4. Limitations
- Supplier lead time is treated as deterministic (7 days); stochastic supplier delays are mitigated via safety stock buffers.

