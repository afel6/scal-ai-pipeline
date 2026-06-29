# HANDOVER.md — PRC SCAL AI Pipeline · Data-Science Onboarding

**Read this first.** It is the single front door to the repository: how to run it,
how the code is laid out, where to make changes safely, and what technical debt to
be aware of. The other Markdown files are deeper references — this one indexes them.

> Audience: the Data Science team taking ownership of the pipeline. You do **not**
> need to read 9,000 lines of `app.py` to be productive — read this, run the gate,
> then dive into the specific layer you're changing using the module map below.

---

## 1. What this system is

A sovereign, on-prem petrophysical AI agent ("Hviel") for the Petroleum Research
Center (Libya). It ingests Special Core Analysis (SCAL / RCAL) lab files
(Excel / CSV / PDF / DOCX / XML), extracts and validates the petrophysics against
hard physical laws, fits reservoir-engineering models, and produces cited chat
answers and branded Word/PowerPoint reports.

The defining design principle: **deterministic Python is the source of truth; the
LLM never invents numbers.** Every physical interpretation passes a validation gate
(`PhysicsGuard`) before it can reach a report.

- **Backend:** FastAPI (Python 3.11; 3.13 also used locally).
- **Frontend:** Vite + React + Tailwind (`frontend/`).
- **LLM:** Google Gemini via **genkit, pinned `0.4.0`** (do not bump — see §6).
- **Stores:** SQLite (local) / Postgres (prod) for chat+audit; ChromaDB for vector
  RAG; SQLite for the new geological knowledge graph.

---

## 2. Run it locally (5 minutes)

```bash
# 1. Python deps (3.11 recommended; 3.13 works locally)
pip install -r requirements.txt

# 2. Secrets — copy and fill in a Gemini key
#    (.env is git-ignored and never deployed)
#    GEMINI_API_KEY=...   (comma-separated keys supported)

# 3. Run the gate FIRST — proves the install is sane
py -3.13 -m pytest tests/        # must be green before you touch anything

# 4. Launch (Windows)
run_local.cmd                    # FastAPI on http://127.0.0.1:8000  · login PIN 1509
```

Frontend changes require a rebuild — Render serves the committed `frontend/dist`,
there is no build step on deploy:

```bash
cd frontend && npm install && npm run build
```

Liveness check is **`/health`** (public). Never use `/api/diag` for liveness — it is
auth-gated and returns 401 before login.

> **Local interpreter note:** the bundled `.venv` is a MinGW Python without wheels —
> `python -m pytest` fails there. Use the system launcher `py -3.13` (documented in
> CLAUDE.md §1).

---

## 3. The one rule that matters: the Physics Gate

```bash
py -3.13 -m pytest tests/
```

Any change touching simulation, curve fitting, parameter extraction, or numerical
output **must** keep this green. `PhysicsGuard` (in `physics_validator.py`) enforces
monotonic Kr curves, endpoint constraints, Archie exponent ranges, mass
conservation, and more. A change that passes its own unit test but fails the gate is
a broken change. Full rationale: **CLAUDE.md §1**.

---

## 4. Module map (the repo is flat — navigate by role, not by folder)

All Python modules currently live in the repo root. Group them mentally by layer:

### Entry / API core
| File | Role |
|---|---|
| `app.py` | **The monolith.** FastAPI app: chat (SSE), tool execution, file upload, report endpoints, session cache, auth, audit ledger. ~9k lines. *See debt §5.* |
| `config.py` | Pydantic `Settings` — all env-driven config (keys, DB paths, thresholds). **Add new config here, never hardcode.** |
| `logger_setup.py` | JSON structured logging. **Use the project logger, never `print()`.** |
| `extra_routes.py` | Feedback / analytics / registration routes, admin-gated. |

### Physics & math engines (the trustworthy core)
| File | Role |
|---|---|
| `physics_validator.py` | **`PhysicsGuard`** — the validation gate. Health-score + violations for Kr, MICP, Archie, J-function, compressibility, saturation endpoints. |
| `petrophysical_curves.py` | Brooks-Corey / LET relative-perm fitter, Pc model, endpoint normalization. |
| `prc_simulated_annealing.py` | Global Brooks-Corey curve match via simulated annealing (escapes local minima). |
| `prc_physics.py` | Deterministic, unit-safe SCAL calculations (anti-hallucination). |
| `prc_thermodynamics.py` | `PRCThermodynamics` — fluid/thermo properties. |
| **`physics_sandbox.py`** | **NEW.** Fit→validate→auto-correct engine (Brooks-Corey, Archie FF/RI, Archie-Waxman-Smits) + restricted `run_sandboxed()`. *See §7.* |

### Knowledge / retrieval
| File | Role |
|---|---|
| `rag_database.py` | ChromaDB vector store of analog wells + the `books/` library. |
| **`geological_graph.py`** | **NEW.** SQLite knowledge graph (Basin/Formation/Lithology/Well/Fluid) + `hybrid_search` fusing graph + vectors. *See §7.* |
| `skills_engine.py` | Dispatch layer for the Hermes agentic skills. |
| `hermes_skills_library/` | The skill implementations (Archie, RQI/FZI, Klinkenberg, centrifuge, …). |
| `ingest_legacy.py` | One-off KB ingestion script. |

### File ingestion & parsing
| File | Role |
|---|---|
| `file_reader.py` | Multi-format reader (xlsx/xls/csv/pdf/docx/xml) → typed tables. |
| `scal_file_handler.py` | SCAL-aware extraction, ground-truth inventory, structural validation. |
| `data_validator.py` | `validate_scal_data()` — schema/range checks on extracted JSON. |

### Output / reporting / visuals
| File | Role |
|---|---|
| **`visualizer.py`** | **REFACTORED.** Pure `extract_curve_coordinates()` (matplotlib-free JSON) + thin PNG renderer. *See §7.* |
| `document_engines.py` | DOCX/PPTX/PDF builders; chart image generation for documents. |
| `report_generator.py` / `report_builder.py` | Branded Word report assembly. |
| `hviel_doc_engine.py` | Structured document-generation engine for the agent. |
| `prc_word_exporter.py` / `claude_doc_template.py` | Word export helpers / templates. |
| `dashboard_architect.py` | Universal SCAL/RCA dashboard JSON architect. |
| `llm_insight_generator.py` | Narrative interpretation text from fitted params. |

### Ops / CLI utilities
| File | Role |
|---|---|
| `batch_process.py` | Batch analytics CLI over a folder of lab files. |
| `database_migration.py` / `db_purge.py` / `cleanup_assets.py` | DB + asset lifecycle scripts. |
| `grader.py` | Auto-grades AI responses against ground truth (eval harness). |
| `e2e_test.py` | End-to-end smoke driver. |

### Tests
`tests/` — pytest suite (the physics gate lives here). `conftest.py` carries CI-safety
shims (offline embedder, genkit stub) so the suite runs without a live Gemini key.

---

## 5. Data flow (upload → answer)

```
Upload (xlsx/csv/pdf/docx/xml)
   └─ file_reader / scal_file_handler  → extract typed tables + ground-truth inventory
        └─ data_validator              → schema/range gate
             └─ physics engines        → fit curves / compute params
                  └─ PhysicsGuard       → validate (health score + violations)  ◀── the gate
                       ├─ report path:  document_engines / report_generator / visualizer → .docx / .png
                       └─ chat path:    app.py injects validated ground truth into the Gemini prompt (SSE)
                                         └─ audit ledger logs every physical interpretation
```

The new modules slot in as: `physics_sandbox` alongside the physics engines (richer
fit + auto-correction), and `geological_graph` alongside `rag_database` (relational
queries the vector store can't answer).

---

## 6. Do-Not-Break invariants (these crash CI or the deploy)

This is the authoritative list for the DS team. (`TEAM.md` at the repo root is the
*internal AI-agent build log* from development — background only, not your reference.)

- **`genkit==0.4.0`** + `genkit-plugin-google-genai==0.4.0`. genkit ≥ 0.5 removed the
  `genkit.ai` module → `ModuleNotFoundError` on any clean install. Do not unpin.
- **File ops use `pathlib.Path`**, never the `os` module, in `app.py`,
  `scal_file_handler.py`, `file_reader.py` (historical `UnboundLocalError` on Render).
- **Liveness = `/health`**, not `/api/diag`.
- **Rebuild `frontend/dist`** after any JSX/CSS change.
- **Never commit `.env`, `*.db`, `__pycache__/`** (secrets / user data).
- **Physics gate green** before any push.

---

## 7. The three modules added for this handover

Standalone, strictly-typed, fully tested. **Not yet wired into `app.py`** — they are
libraries ready for you to integrate (register sandbox fits as tools; seed the graph
from `books/`).

- **`geological_graph.py`** — `GeologicalGraph(db_path)`. `add_relation()`,
  `query_connections(node, depth_limit)` (bounded BFS), `hybrid_search(query,
  porous_range, perm_range, retriever)`. Pass a live `RAGDatabase` as `retriever` to
  bridge graph + vectors. Tests: `tests/test_geological_graph.py`.
- **`physics_sandbox.py`** — `PhysicsSandbox.fit_brooks_corey / fit_archie /
  fit_waxman_smits`, each running fit → validate → auto-correct. `run_sandboxed()`
  executes restricted snippets (AST audit blocks imports/dunder/`open`/`eval`;
  whitelisted `math`/`numpy`/`scipy` only — best-effort, **not** a hardened jail).
  Tests: `tests/test_physics_sandbox.py`.
- **`visualizer.py`** — coordinate generation is now decoupled from rendering:
  `extract_curve_coordinates()` returns pure `{x, y, labels}` JSON (let the frontend
  or `document_engines` render); `generate_plots()` is kept for `app.py` compat.
  Tests: `tests/test_visualizer_coordinates.py`.

> ⚠️ **Gotcha — health grade ≠ fit quality.** `PhysicsGuard` scores *parameter
> legality*, not goodness-of-fit. The sandbox can clamp physically-impossible input
> into a legal-but-poor fit that still grades "A" while `r²` is low. **Always read
> `parameters.r2` alongside `health.grade`** before trusting a result.

---

## 8. Known technical debt (ranked — your refactor backlog)

1. **`app.py` is a ~9k-line monolith.** Chat, tools, upload, reports, auth, cache,
   and audit all in one file. **Highest-value refactor**, but do it *after* you
   understand the session-cache and provenance invariants (CLAUDE.md §4 ledger) —
   they are subtle and load-bearing. Split by concern (routes / chat / tools /
   reports) incrementally, keeping the gate green at each step.
2. **Anti-hallucination is band-aids, not architecture.** Many regex post-processors
   patch LLM output (citation forging, truncation, provenance). The structural fix is
   deterministic grounding — the new `geological_graph` + `physics_sandbox` point the
   right way. Prefer extending those over adding more output filters.
3. **genkit frozen at 0.4.0.** A migration is owed eventually; plan it deliberately.
4. **Two test-type classifiers can disagree** (`SCALFileHandler.identify()` vs
   `file_reader._detect_test_type`) — some files mislabel. Unify to one scorer.
5. **Doc sprawl.** 11 Markdown files. This HANDOVER indexes them; consider moving the
   deep ones into a `docs/` folder later (cosmetic, low priority).
6. **New modules unwired.** Integrate `physics_sandbox` / `geological_graph` into the
   tool path to realize their value.

---

## 9. Where to start (first day)

1. `pip install -r requirements.txt` → `py -3.13 -m pytest tests/` (green?).
2. `run_local.cmd` → log in (PIN 1509) → upload a sample SCAL file → watch a report
   generate. That single flow exercises ingestion → physics → validation → output.
3. Read **CLAUDE.md** (engineering rules + physics gate). Skim `physics_validator.py`
   — it is the heart of the system.
4. Pick a debt item from §8. Keep the gate green. Record what you changed in your own
   PR / changelog.

Welcome aboard.
