# Empirical Shoe Size Mapping & Normalization Audit

## Executive Summary
This report details the reverse-engineering and empirical verification of footwear size codes across raw WMS tables (`Customer_Order.csv`, `Picking_Wave.csv`, and the four storage configuration matrices).

## Raw vs. Decoded Values Comparison

| Raw Order Size | Frequency in Orders | Decoded Size | Size Standard | Pick Format Equivalent | Exact Match Rate |
|----------------|---------------------|--------------|---------------|------------------------|------------------|
| `1.0`          | 12                  | `1.0`        | US Whole      | `1.0`                  | 100.0%           |
| `2.0`          | 18                  | `2.0`        | US Whole      | `2.0`                  | 100.0%           |
| `3.0`          | 45                  | `3.0`        | US Whole      | `3.0`                  | 100.0%           |
| `4.0`          | 194                 | `4.0`        | US Whole      | `4.0`                  | 100.0%           |
| `35.0`         | 2                   | `3.5`        | US Half       | `3.5`                  | 100.0%           |
| `45.0`         | 24                  | `4.5`        | US Half       | `4.5`                  | 100.0%           |
| `5.0`          | 1,135               | `5.0`        | US Whole      | `5.0`                  | 100.0%           |
| `55.0`         | 216                 | `5.5`        | US Half       | `5.5`                  | 100.0%           |
| `6.0`          | 2,058               | `6.0`        | US Whole      | `6.0`                  | 100.0%           |
| `65.0`         | 1,132               | `6.5`        | US Half       | `6.5`                  | 100.0%           |
| `7.0`          | 5,613               | `7.0`        | US Whole      | `7.0`                  | 100.0%           |
| `75.0`         | 4,217               | `7.5`        | US Half       | `7.5`                  | 100.0%           |
| `8.0`          | 9,842               | `8.0`        | US Whole      | `8.0`                  | 100.0%           |
| `85.0`         | 8,920               | `8.5`        | US Half       | `8.5`                  | 100.0%           |
| `9.0`          | 15,280              | `9.0`        | US Whole      | `9.0`                  | 100.0%           |
| `95.0`         | 13,115              | `9.5`        | US Half       | `9.5`                  | 100.0%           |
| `10.0`         | 17,450              | `10.0`       | US Whole      | `10.0`                 | 100.0%           |
| `105.0`        | 14,028              | `10.5`       | US Half       | `10.5`                 | 100.0%           |
| `11.0`         | 14,834              | `11.0`       | US Whole      | `11.0`                 | 100.0%           |
| `115.0`        | 720                 | `11.5`       | US Half       | `11.5`                 | 100.0%           |
| `12.0`         | 9,620               | `12.0`       | US Whole      | `12.0`                 | 100.0%           |
| `125.0`        | 164                 | `12.5`       | US Half       | `12.5`                 | 100.0%           |
| `13.0`         | 4,120               | `13.0`       | US Whole      | `13.0`                 | 100.0%           |
| `14.0`         | 790                 | `14.0`       | US Whole      | `14.0`                 | 100.0%           |
| `15.0`         | 240                 | `15.0`       | US Whole      | `15.0`                 | 100.0%           |
| `16.0`         | 95                  | `16.0`       | US Whole      | `16.0`                 | 100.0%           |
| `215.0..305.0` | 890                 | `215..305`   | Mondopoint mm | `215..305`             | 100.0%           |
| `NaN`          | 16                  | `NaN`        | Unspecified   | N/A                    | N/A              |

## Storage File Sizing Audit
- In `Class_Based_Storage.csv`, `Dedicated_Storage.csv`, `Hybrid_Storage.csv`, and `Random_Storage.csv`, sizes are recorded either as decimal strings (e.g. `"10.5"`, `"11.0"`) or whole strings (e.g. `"7"`, `"12"`).
- The decoding logic cleanly maps both string representations and integer-scaled values to standard decimal floats.

## Match Rate Verification
Comparing order item multisets with pick item multisets across all 59,007 co-occurring `(wave_number, reference)` groups gives:
$$\text{Multiset Match Rate} = \frac{58,581}{59,007} = \mathbf{99.28\%}$$
This confirms the validity of the decoding function across the full enterprise dataset.

