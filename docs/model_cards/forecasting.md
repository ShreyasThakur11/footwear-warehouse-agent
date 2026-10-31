# Model Card: Multi-Horizon Demand Forecaster & Prediction Interval Engine

## 1. Model Overview
- **Model Name**: Quantile Gradient Boosting & Intermittent SKU-Size Forecaster (`warehouse_ai.models.forecasting`)
- **Model Type**: Supervised Quantile Regression (`HistGradientBoostingRegressor`) + Holt-Winters ETS + Croston's Method with Syntetos-Boylan Approximation (SBA)
- **Purpose**: Project aggregate daily workload (Units, Lines, Orders) across a 1–14 day horizon and weekly SKU-size requirements to drive workforce and replenishment sizing.
- **Version**: 1.0.0

## 2. Model Architecture & Feature Engineering
- **Temporal Cadence**: Day-of-week one-hot indicators, day-of-month, week-of-year, month.
- **Autoregressive Lags**: Lags 1, 7, and 14 days capturing weekly seasonality.
- **Rolling Windows**: 7-day and 14-day rolling means and standard deviations.
- **Calendar Knowledge**: Canadian and Quebec statutory holiday calendar integration (Good Friday, Easter Monday, Patriots' Day, Saint-Jean-Baptiste, Labour Day, Thanksgiving) preventing artificial post-holiday forecasting overhangs.
- **Prediction Intervals**: Calibrated pinball loss quantile objectives at $\alpha = 0.10$ (P10 lower bound) and $\alpha = 0.90$ (P90 safety buffer), alongside median loss at $\alpha = 0.50$ (P50 expected volume).

## 3. SKU-Size Intermittency Modeling
- **Intermittency Skew**: **69.8%** of weekly SKU-size time series are zero-demand intervals.
- **Croston-SBA**: Separates non-zero demand size from inter-arrival intervals and applies the Syntetos-Boylan correction factor $(1 - \alpha/2)$ to eliminate standard exponential smoothing positive bias on sporadic slow-movers.

## 4. Backtest Performance (Rolling 8-Week Evaluation)
| Target | Champion Model | MAE | WAPE (%) | Bias (%) | 80% Coverage (%) |
|---|---|---|---|---|---|
| **Units Demand** | Quantile Gradient Boosting | 724.7 | 93.2% | -19.7% | 73.5% |
| **Pick Lines** | Quantile Gradient Boosting | 391.4 | 91.9% | -21.9% | 73.5% |
| **EDI Orders** | Holt-Winters ETS | 93.8 | 93.0% | -11.1% | 64.3% |

## 5. Limitations
- Does not incorporate external promotional calendars or wholesale bulk markdown events unless reflected in historical EDI lag signals.

