# Warehouse Layouts & CAD Blueprints

This directory contains 2D vector blueprints, AutoCAD drawings, and high-resolution floor plans of the safety-boot distribution warehouse in Sherbrooke, Quebec.

## Structure

```
layouts/
├── cad/                    # Vector engineering drawings (DWG & DXF)
│   ├── Full layout.dwg     # Complete 3D/2D AutoCAD warehouse layout
│   ├── Current_Random_*.dxf # Historical layout DXF files (Levels 0–4 & All)
│   └── Optimised_*.dxf     # Proposed slotting DXF files (Levels 0–4 & All)
└── floors/                 # High-resolution raster (PNG) & print-ready (PDF) layouts
    ├── Current_Random_*.png / .pdf
    └── Optimised_*.png / .pdf
```

## Warehouse Specifications

- **Racks:** 25 storage racks
- **Pick Aisles:** 17 parallel pick aisles
- **Cross Aisles:** 3 traversal cross-aisles
- **Locations:** 2,293 addressable slot locations
- **Operating Levels:**
  - **Level 0 (Ground):** Active manual picking zone nearest the I/O depot
  - **Level 1 & 2:** Upper manual picking faces accessible by trolley pickers
  - **Level 3 & 4:** Overhead high-bay reserve buffer serviced by forklifts
- **Input / Output Depot:** Located at coordinate node `CC-08`

## CAD Files

- [`Full layout.dwg`](cad/Full%20layout.dwg) (7.9 MB): Master drawing for Autodesk AutoCAD / DWG TrueView.
- DXF Vector Files: Standard ASCII 2D exchange format compatible with FreeCAD, QCAD, and LibreCAD.
