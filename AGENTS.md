# AGENTS.md

This file provides system instructions, setup commands, and architectural context for autonomous AI agents (such as Google Labs Jules) working on the PRC SCAL AI Pipeline.

> [!IMPORTANT]
> **Multi-agent teamwork:** This repo is built by more than one AI agent (Antigravity/Gemini and Claude Code). **Before you start, read [`TEAM.md`](TEAM.md)** — it holds the collaboration protocol, the "Do Not Break" invariants (e.g. the pinned `genkit==0.4.0`), and the async Handoff Log. **When you finish, append a Handoff Log entry in TEAM.md and commit before handing off.**

## 🛠 Project Context
- **Name**: PRC SCAL AI Pipeline (Hviel)
- **Purpose**: A mixture-of-experts petrophysical analysis agent that ingests core sample data (Excel/CSV) and generates reports/charts adhering to strict physical boundaries and an Industrial Brutalist design theme.
- **Tech Stack**: FastAPI backend, React (Vite) frontend, PostgreSQL/SQLite vector store.

## 🚀 Setup & Execution
- **Dependency Installation**:
  ```bash
  pip install -r requirements.txt
  ```
- **Run Development Server**:
  ```bash
  python app.py
  ```

## 🧪 Testing Instructions
- **Physics Integrity & Integration Gate**:
  ```bash
  python -m pytest tests/
  ```
- *Agent Rule*: All simulation, parameter extraction, or math changes **MUST** pass the pytest suite before proposing a PR.

## 📐 Non-Negotiable Coding Standards

### 1. Physics Constraints (PhysicsGuard)
- Exponents: Brooks-Corey ($n_w, n_o > 0$), LET parameters ($L, E, T > 0$), Archie exponents ($m \in [1.3, 3.5]$, $n \in [1.5, 3.0]$).
- Irreducible saturations: $S_{wr} + S_{nr} < 1$.
- Displacement Efficiency Standard: $E_d = (1 - S_{wi} - S_{or}) / (1 - S_{wi})$ (strictly $62.1\%$ for benchmarks, never average values).
- Normalization: Resistivity Index ($RI = 1.0$ at $S_w = 1.0$).

### 2. File Handling Namespace Isolation
- **No `os` module imports or usage for file-system operations** (e.g., path joining, unlinking, exist checks) in `app.py`, `scal_file_handler.py`, and `file_reader.py`.
- **Always use `pathlib.Path` objects** (e.g., `Path(x).exists()`, `Path(x).unlink(missing_ok=True)`).

### 3. Industrial Brutalist UI Aesthetic
- **Visuals**: Dark background (`#030303`/`#07070d`), Amber/Gold accents (`#FFD700`/`#D97706`), Sky Blue data points (`#38bdf8`), High Contrast. No pastels or gradients.
- **Data Denseness**: Grid systems, monospace typography for parameters/numbers, custom subtle borders.
- **No Animations on Data**: Keep charts static (no data bounce). Scrollbar custom styling.

## 🔒 Security & Data Hygiene
- **Memory Footprint**: Ensure data arrays and cache states are cleared cleanly (e.g., `SESSION_DATA_CACHE[session_id].clear()`, `gc.collect()`).
- **File Validation**: Validate `session_id` parameters using regex `r"^(report-)?[a-zA-Z0-9\-]+$"` and files using `Path(filename).name` to block path traversal. Limit payloads to `20MB`.
