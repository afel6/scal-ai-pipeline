# Phase 3 Advanced Petrophysical & UI Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automated units normalization, dynamic SQLite basin rule engine, and interactive point drag-and-drop curve calibration in the SCAL and PVT pipelines.

**Architecture:** A lightweight conversion engine normalizes units on ingestion and computation. A SQLite-backed dynamic rules table allows custom rule configurations per basin. The UI plot captures drag events and sends updated coordinates to backend calibration endpoints to re-fit and validate curves.

**Tech Stack:** FastAPI, Python stdlib (sqlite3, urllib, re), React.js, SVG.

---

## Global Constraints
* SCAL backend on port 8000.
* PVT backend on port 8001.
* React frontend on port 5174.
* Physical invariants must be preserved: $B_o \ge 1.0$, $P_b > 0$, viscosity decreases with temperature.

---

## Proposed Changes

### Task 1: Automated Units Normalization Layer

**Files:**
* Create: `scal-ai-pipeline/src/utils/units.py`
* Create: `pvt-ai-pipeline/src/utils/units.py`
* Modify: `pvt-ai-pipeline/src/api/app.py`
* Modify: `scal-ai-pipeline/app.py`
* Test: `scal-ai-pipeline/tests/test_units.py`

- [ ] **Step 1: Write units test suite**
  Write a test file `scal-ai-pipeline/tests/test_units.py`:
  ```python
  import pytest
  from src.utils.units import convert_pressure, convert_temperature, detect_unit

  def test_unit_conversions():
      assert abs(convert_pressure(1.0, "bar") - 14.50377) < 1e-3
      assert abs(convert_temperature(0.0, "C") - 32.0) < 1e-3
      assert detect_unit("Pressure (bar)") == ("pressure", "bar")
  ```

- [ ] **Step 2: Implement units conversion in both pipelines**
  Ensure both `scal-ai-pipeline/src/utils/units.py` and `pvt-ai-pipeline/src/utils/units.py` contain the complete conversion logic.

- [ ] **Step 3: Update PVT endpoints in pvt-ai-pipeline/src/api/app.py**
  Add unit detection and normalization in `pvt_evaluate`, `pvt_curve`, and `pvt_export_eclipse`. Return both the original raw inputs and standardized values.

- [ ] **Step 4: Update SCAL ingestion in scal-ai-pipeline/app.py**
  Scan uploaded Excel column headers for unit tags like `(bar)` or `(D)` and normalize them to target units (`psi`, `mD`) before caching and processing.

- [ ] **Step 5: Run unit tests**
  Run: `$env:PYTHONPATH="."; C:\Users\Asus\Downloads\.venv\Scripts\pytest.exe tests/test_units.py`
  Expected: PASS

---

### Task 2: Dynamic Basin-Specific Rule Engine

**Files:**
* Modify: `scal-ai-pipeline/app.py`
* Modify: `pvt-ai-pipeline/src/api/app.py`
* Modify: `scal-ai-pipeline/physics_validator.py`
* Modify: `pvt-ai-pipeline/src/data/pvt_validator.py`
* Test: `scal-ai-pipeline/tests/test_basin_rules.py`

- [ ] **Step 1: Create rule database table and seed defaults**
  In the database connection/startup manager of both `scal-ai-pipeline/app.py` and `pvt-ai-pipeline/src/api/app.py`, run SQL schema DDL:
  ```sql
  CREATE TABLE IF NOT EXISTS basin_physics_rules (
      basin_name TEXT NOT NULL,
      rule_key   TEXT NOT NULL,
      min_limit  REAL NOT NULL,
      max_limit  REAL NOT NULL,
      PRIMARY KEY (basin_name, rule_key)
  );
  ```
  Seed default rules:
  ```sql
  INSERT OR IGNORE INTO basin_physics_rules (basin_name, rule_key, min_limit, max_limit) VALUES
  ('Default', 'm', 1.3, 2.5),
  ('Default', 'a', 0.5, 1.5);
  ```

- [ ] **Step 2: Refactor PhysicsGuard**
  Update `PhysicsGuard` to fetch parameters matching the active session's `basin_name` from `basin_physics_rules`, falling back to `"Default"`.

- [ ] **Step 3: Expose Admin Rule Endpoints**
  Add `GET /api/admin/rules` and `POST /api/admin/rules` endpoints to both backends.

- [ ] **Step 4: Run rule engine tests**
  Run: `$env:PYTHONPATH="."; C:\Users\Asus\Downloads\.venv\Scripts\pytest.exe tests/test_basin_rules.py`
  Expected: PASS

---

### Task 3: Interactive Curve Calibration UI

**Files:**
* Modify: `frontend/src/components/RelativePermeabilityPlot.jsx`
* Modify: `frontend/src/components/ArchiePlot.jsx`
* Modify: `scal-ai-pipeline/app.py`
* Modify: `pvt-ai-pipeline/src/api/app.py`
* Test: `scal-ai-pipeline/tests/test_calibration.py`

- [ ] **Step 1: Add drag interaction on SVG plots**
  Implement mouse event listeners (`onMouseDown`, `onMouseMove`, `onMouseUp`) on SVG scatter plot circles to update the coordinates state.

- [ ] **Step 2: Create backend calibration endpoints**
  * In `scal-ai-pipeline/app.py`, expose `POST /api/scal/calibrate` to re-fit Brooks-Corey curves.
  * In `pvt-ai-pipeline/src/api/app.py`, expose `POST /api/pvt/calibrate` to re-fit Archie parameters.
  
- [ ] **Step 3: Run calibration integration tests**
  Verify the calibration endpoint re-fits the curves and returns the updated plot line coordinate payload.
  Run: `$env:PYTHONPATH="."; C:\Users\Asus\Downloads\.venv\Scripts\pytest.exe tests/test_calibration.py`
  Expected: PASS
