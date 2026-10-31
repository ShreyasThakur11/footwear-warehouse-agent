# Engineering & Domain Assumptions

## 1. Shoe Size Encoding & Normalization

### Context
In the raw WMS dataset, shoe size entries across tables exhibit three distinct representation formats:
1. **US Standard Whole Sizes**: Represented directly as integers or floats `1.0` through `16.0` (e.g. `9.0`, `10.0`).
2. **US Standard Half Sizes (Integer-Encoded)**: Represented without decimal points as 2- or 3-digit integers `35` through `125` (e.g., `85` = US 8.5, `105` = US 10.5, `115` = US 11.5).
3. **Mondopoint / Millimeter Sizes**: Footwear length in millimeters `215.0` through `305.0` (e.g., `260.0` mm ≈ US 8 / EU 41).
4. **Decimals**: In `Picking_Wave.csv` and storage files, half sizes are explicitly recorded with decimals (e.g., `8.5`, `10.5`).

### Empirical Verification
- We evaluated 59,007 common `(wave_number, reference)` groups between `Customer_Order.csv` and `Picking_Wave.csv`.
- Comparing the multiset of order sizes against pick sizes confirmed an exact multiset match rate of **99.28%** (58,581 out of 59,007 groups).
- Discrepancies (<0.8%) represent recorded warehouse stock shortages or operator substitutions.

### Normalization Logic (`decode_size`)
- Values in `{35, 45, 55, 65, 75, 85, 95, 105, 115, 125}` are divided by `10.0` to yield `{3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5}`.
- Values in `1.0..16.0` and `>= 200.0` are preserved.
- Missing values (`NaN` or empty strings) are mapped to `NaN`.

---

## 2. Warehouse Physical Layout & Coordinates

### Coordinate System & Corridors
- The warehouse coordinate system is expressed in decimeters / grid units.
- Three primary longitudinal cross-aisle corridors facilitate travel between racks:
  - **Left Corridor (LC)**: Located at $x \approx 66.0$. 17 support points (`LC-01` through `LC-17`).
  - **Center Corridor (CC)**: Located at $x \approx 403.0$. 17 support points (`CC-01` through `CC-17`). Contains the I/O dispatch depot at `CC-08` $(403.0, 631.0, 1.0)$.
  - **Right Corridor (RC)**: Located at $x \approx 686.0$. 10 support points (`RC-08` through `RC-17`).
- The right wing of the warehouse begins at bay line 8, explaining why `RC-01` through `RC-07` are absent.

### Location Code Syntax
Location codes follow the schema `AISLE-BAY-LEVEL_SLOT`:
- `Aisle`: Letter `A` through `R` (17 aisles).
- `Bay`: Rack bay number `01` through `26`.
- `Level`: Vertical tier `1` through `4` (levels 1–2 represent manual picking; levels 3–4 represent reserve replenishment).
- `Slot`: Position within the bay shelf (`1`, `2`, `3` for lower levels; `0` for reserve tiers).

---

## 3. Workload Dynamics & Productivity Proxies

### Lack of Pick Timestamps
- Individual pick actions in `Picking_Wave.csv` do not record per-item timestamps.
- Total daily units picked divided by the number of active operators serving on that day serves as our empirical proxy for workforce productivity.
- Order arrival timestamps in `Customer_Order.csv` provide temporal distribution of demand.
