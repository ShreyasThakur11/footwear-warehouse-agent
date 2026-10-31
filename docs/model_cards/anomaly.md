# Model Card: Operational Anomaly Detection & Exception Triage Engine

## 1. Model Overview
- **Model Name**: Dual Rule-Based Integrity Scanner & Statistical Wave Outlier Detector (`warehouse_ai.models.anomaly`)
- **Model Type**: Configurable Deterministic Rule Engine + Unsupervised Multivariate Isolation Forest (`sklearn.ensemble.IsolationForest`)
- **Purpose**: Detect inventory discrepancies, physical policy breaches, labor productivity deviations, and unusual wave geometries across commercial WMS transaction logs.
- **Version**: 1.0.0

## 2. Detection Architecture

### 1. Deterministic Rule-Based Scanners
Evaluates transactional logs against 5 core operating rules:
1. `SHORT_PICK` / `OVER_PICK`: Picked quantity deviates from customer order requirement for a given wave and SKU.
2. `LOCATION_POLICY_MISMATCH`: Items retrieved from a location not designated for that reference under active storage policies.
3. `UNKNOWN_LOCATION`: Pick recorded at non-standard staging areas (`ZN-COR`, `EX-01`, etc.).
4. `DEMAND_SURGE_BREACH`: Daily order volume falls outside P10–P90 calibrated forecast bounds.
5. `OPERATOR_PRODUCTIVITY_DEV`: Operator daily units-per-hour deviates >2.0 standard deviations from peer cohort mean.

### 2. Statistical Multivariate Anomaly Detection
Fits an `IsolationForest` (contamination = 1.0%, estimators = 100) on 4 wave geometry features:
- `total_units`: Units retrieved per wave.
- `n_locations`: Distinct bin stops.
- `n_aisles`: Number of horizontal aisles crossed.
- `travel_dist`: Total Dijkstra walking distance.

Identifies waves with abnormal travel-to-unit ratios (e.g. crossing 15 aisles for only 3 units) indicative of poor batching or split replenishment.

## 3. Industrial Exception Triage Audit (Full Historical Dataset)
- **Total Exceptions Scanned**: **21,582 records** across 122,370 order lines and 215,192 picks.
- **High Severity (Action Required)**: 494 records (unreconciled customer fulfillment shortfalls and 22 staging bays).
- **Medium Severity**: 21,088 records (16,132 policy location mismatches, 5,242 line quantity variances).
- **Statistical Wave Outliers**: 98 anomalous waves flagged for routing and batch re-examination.
- **Productivity Deviations**: 42 low-velocity operator shifts and 38 high-velocity surge shifts flagged for ergonomic and fatigue auditing.

## 4. Prescriptive Action Mapping
Every generated exception is paired with an actionable remediation directive:
- `SHORT_PICK` ➔ "Initiate immediate forward pick-face cycle count."
- `LOCATION_POLICY_MISMATCH` ➔ "Audit slotting master data and schedule box relocation."
- `OPERATOR_PRODUCTIVITY_LOW` ➔ "Review picking cart ergonomics and check for aisle congestion."

