# Written Report & Analytical Figures

This folder contains the official written technical report and publication-grade analytical figures.

## Primary Deliverable

📄 **[Download Official Report PDF (3.9 MB)](Warehouse_Optimisation_Report.pdf)**

The report provides comprehensive mathematical formulations, empirical methodology, sensitivity checks, operator behavioral findings, and warehouse implementation recommendations.

---

## Analytical Figures Catalog (`figures/`)

All 26 figures are generated programmatically via [`v3.ipynb`](../v3.ipynb) with reproducible seeds.

### 1. Demand Profiling & Exploratory Data Analysis (EDA)
- [`01_eda_orders_per_day.png`](figures/01_eda_orders_per_day.png) — Daily order volume distribution and historical fluctuations
- [`02_eda_order_arrival_heatmap.png`](figures/02_eda_order_arrival_heatmap.png) — Order arrival intensity by hour of day and day of week
- [`03_eda_order_profile.png`](figures/03_eda_order_profile.png) — Distribution of line items and total quantity per customer order
- [`04_eda_wave_profile.png`](figures/04_eda_wave_profile.png) — Distribution of units per picking wave against trolley limit (27 units)
- [`05_eda_pareto_abc.png`](figures/05_eda_pareto_abc.png) — Pareto 80/20 ABC demand curve (Class A = 80% volume in 16.5% of SKUs)
- [`06_eda_abc_master_vs_demand.png`](figures/06_eda_abc_master_vs_demand.png) — Catalog velocity classification vs true empirical pick activity
- [`07_eda_size_aisle_operator.png`](figures/07_eda_size_aisle_operator.png) — Multi-dimensional activity across shoe sizes, aisles, and operators

### 2. Spatial Network Topology & Heatmaps
- [`10_map_layout_network.png`](figures/10_map_layout_network.png) — Warehouse graph model with pick aisles, cross-aisles, and I/O depot
- [`11_map_distance_from_io.png`](figures/11_map_distance_from_io.png) — Isochrone distance contour heatmap from Input/Output (I/O) depot
- [`12_map_demand_asis.png`](figures/12_map_demand_asis.png) — Spatial heatmap of historical picking under AS-IS random slotting
- [`13_map_demand_by_policy.png`](figures/13_map_demand_by_policy.png) — Comparative demand density maps across 6 storage policies
- [`14_map_abc_before_after.png`](figures/14_map_abc_before_after.png) — Spatial allocation before vs after shifting Class A items to I/O
- [`15_map_example_route.png`](figures/15_map_example_route.png) — Sample picker tour comparing AS-IS recorded path vs NN 2-opt route

### 3. Simulation Benchmarks & Economic Impact
- [`20_result_distance_by_scenario.png`](figures/20_result_distance_by_scenario.png) — Total and average walking distance across 15 scenarios
- [`21_result_distance_boxplot.png`](figures/21_result_distance_boxplot.png) — Statistical spread and variance of travel distances per wave
- [`22_result_time_breakdown.png`](figures/22_result_time_breakdown.png) — Walk time vs stop time vs pick time vs wave setup time
- [`23_result_saving_waterfall.png`](figures/23_result_saving_waterfall.png) — Waterfall decomposition: routing (-14.6%) vs slotting (-44.9%)
- [`24_result_operator_performance.png`](figures/24_result_operator_performance.png) — Operator productivity gains and route efficiency indices
- [`25_result_daily_FTE.png`](figures/25_result_daily_FTE.png) — Shift labor capacity and daily FTE requirements
- [`26_result_order_lead_time.png`](figures/26_result_order_lead_time.png) — Impact of pick cycle acceleration on order fulfillment speed

### 4. Operational Dynamics & Labor Temporal Trends
- [`30_time_distribution_per_wave.png`](figures/30_time_distribution_per_wave.png) — Probability density shift from 7.85 min down to 5.78 min
- [`31_time_components_by_arrangement.png`](figures/31_time_components_by_arrangement.png) — Time components split across storage policies
- [`32_time_daily_hours.png`](figures/32_time_daily_hours.png) — Longitudinal daily tracking of total picker hours
- [`33_time_by_hour_and_weekday.png`](figures/33_time_by_hour_and_weekday.png) — Heatmap tracking hourly workforce utilization
- [`34_time_cdf.png`](figures/34_time_cdf.png) — Cumulative distribution function (CDF) of wave completion times
- [`35_time_vs_wave_size.png`](figures/35_time_vs_wave_size.png) — Correlation between units per wave and wave cycle duration
- [`36_time_monthly.png`](figures/36_time_monthly.png) — Monthly throughput trends confirming long-term stability
