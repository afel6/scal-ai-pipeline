# Design Specification: Phase 3 Advanced Petrophysical & UI Upgrades

This document specifies the design for the automated units normalization layer, dynamic basin-specific rule engine, and interactive curve calibration UI.

---

## 1. Automated Units Normalization Layer

### 1.1 Architecture & Components
* A lightweight units converter `units.py` under `src/utils/` in both codebases.
* Unit conversion tables for Pressure (`psi`), Temperature (`°F`), Permeability (`mD`), and Viscosity (`cp`).
* A regex-based unit detector `detect_unit` that extracts unit strings from column headers and text payloads. E.g., `Pressure (bar)` -> `bar`.

### 1.2 Data Flow
1. **Input Interception:**
   * In `pvt-ai-pipeline/src/api/app.py`, endpoints `POST /api/pvt/evaluate`, `POST /api/pvt/curve`, and `POST /api/pvt/export/eclipse` are updated to accept optional unit parameters (`pressure_unit`, `temp_unit`).
   * In `scal-ai-pipeline/app.py`, during Excel data parse / ingestion (`extract_absolute_file_truth` or tool execution), column headers are scanned. If a unit is detected (e.g. `bar`), values in that column are converted to standard units (`psi`) before passing to the curve fitters.
2. **Normalization:**
   * Conversion is executed using conversion factors.
3. **Response:**
   * Standardized outputs are returned to the user alongside the raw inputs.

---

## 2. Dynamic Basin-Specific Rule Engine

### 2.1 SQLite Rule Registry
* A new table `basin_physics_rules` is created in both databases:
  ```sql
  CREATE TABLE IF NOT EXISTS basin_physics_rules (
      basin_name TEXT NOT NULL,
      rule_key   TEXT NOT NULL,
      min_limit  REAL NOT NULL,
      max_limit  REAL NOT NULL,
      PRIMARY KEY (basin_name, rule_key)
  );
  ```
* Seeding: Default limits (e.g. `m` $\in [1.3, 2.5]$, `a` $\in [0.5, 1.5]$) are inserted under `basin_name = "Default"`.

### 2.2 Refactoring PhysicsGuard
* `PhysicsGuard.validate_kr()` and `validate_pvt()` are updated to read from `basin_physics_rules`.
* It queries rules for the active basin name, falling back to the `Default` limits.

### 2.3 Admin API
* `GET /api/admin/rules`: List all configured rules.
* `POST /api/admin/rules`: Upsert a rule configuration.

---

## 3. Interactive Curve Calibration UI

### 3.1 Frontend SVG Drag-and-Drop
* React SVG plot components are updated to make data points draggable.
* Mouse move/drag events track positions, map screen coordinates to petrophysical units, and trigger callback updates on drag-end.

### 3.2 Backend Calibration Endpoints
* `POST /api/pvt/calibrate` & `POST /api/scal/calibrate`:
  * Backend receives updated point sets.
  * Re-runs the Brooks-Corey relative permeability or Archie fitting functions.
  * Validates results against the dynamic `PhysicsGuard` constraints.
  * Returns updated fitted curve line coordinates and validation status.
