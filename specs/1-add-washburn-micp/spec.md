# Specification - Washburn Equation Integration (MICP)

## Goal Description
Mercury Injection Capillary Pressure (MICP) is a primary laboratory method used to evaluate reservoir rock pore throat size distribution. The pipeline currently extracts raw capillary pressure data but does not perform the physical calculations to translate this pressure into pore throat sizes.

This feature integrates the **Washburn Equation** into the core physics engine to automatically calculate and validate pore throat radii (in microns) from capillary pressure data (in psia).

---

## User Scenarios

### Scenario 1: Automatic Pore Throat Calculation
* **Given:** A user uploads a SCAL spreadsheet containing capillary pressure data (`pressure_psia`).
* **When:** The pipeline processes the file.
* **Then:** The system automatically calculates the corresponding pore throat radius (in microns) for each pressure point and includes these values in the processed output dataset.

### Scenario 2: Physical Boundary Validation
* **Given:** The user uploads a dataset with physically impossible pressure values (e.g., negative pressures or zero pressure).
* **When:** The pipeline runs validation checks.
* **Then:** The system flags these points as physical violations (error/warning) and explains the violation clearly in the validation report.

---

## Functional Requirements

### 1. Mathematical Calculation (Washburn Equation)
The system must calculate the pore throat radius $r$ (in microns) from capillary pressure $P_c$ (in psia) using:
$$r = \frac{2 \cdot \gamma \cdot |\cos(\theta)|}{P_c \cdot 68947.6} \cdot 10000$$

Where:
* $P_c$ is the capillary pressure in psia.
* $\gamma$ is the interfacial tension of mercury (default: $480 \text{ dynes/cm}$).
* $\theta$ is the mercury contact angle (default: $140^\circ$).
* $68947.6$ is the conversion factor from psi to dynes/cm².
* $10000$ is the conversion factor from centimeters to microns.

### 2. Validation Constraints
* **Positive Pressures:** $P_c > 0$. If $P_c \le 0$, the calculation must yield an error or warning, as dividing by zero or negative pressure is physically impossible.
* **Monotonicity:** As capillary pressure $P_c$ increases, the calculated pore throat radius $r$ must strictly decrease. If it does not, the dataset is physically corrupt.

### 3. Core Engine Integration
* The calculation must be exposed as a utility function in the physics module (`prc_physics.py` or similar).
* The data processing pipeline (`scal_file_handler.py`) must call this function when it encounters capillary pressure columns during file ingestion.

---

## Success Criteria

1. **Precision:** Calculated pore throat radii must be accurate to **4 decimal places**.
2. **Robustness:** The system must gracefully handle division-by-zero errors (e.g., $P_c = 0$) by replacing them with a safe minimum value (like $1 \times 10^{-9}$) and logging a warning.
3. **Verification:** Our unit tests must verify the Washburn calculation using standard reference data (e.g., a pressure of $100 \text{ psia}$ should yield a pore throat radius of approximately $1.0664 \text{ microns}$).
