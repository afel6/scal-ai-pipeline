# SCAL AI Pipeline — Hviel

FastAPI backend + React frontend for Special Core Analysis (SCAL) data:
upload lab spreadsheets (MICP, KR, PC, FRF/RI, NMR, RCAL, wettability,
formation damage), extract them deterministically, validate the physics, chat
over the results, and generate reports. The AI agent persona is **Hviel**.
PVT fluid reports are out of scope — they are rejected with a pointer to the
PVT pipeline (Aviel, port 8001).

The defining design principle: **deterministic Python is the source of truth;
the LLM never invents numbers.** Every physical interpretation passes a
validation gate (`PhysicsGuard`) before it can reach a report.

- **Backend:** FastAPI (Python 3.11; 3.13 also works locally)
- **Frontend:** Vite + React + Tailwind (`frontend/`)
- **LLM:** Google Gemini via `google-genai` (see CLAUDE.md §5 for pinned model/SDK)
- **Stores:** SQLite (local) / Postgres (prod) for chat + audit; ChromaDB for
  the analog-wells module; SQLite for the geological knowledge graph

## Quickstart

```
pip install -r requirements.txt
py -3.13 -m pytest tests/    # the physics gate — must be green before you touch anything
run_local.cmd                # backend on http://127.0.0.1:8000 (login PIN 1509)
```

Backend by hand: `python -m uvicorn app:app --host 127.0.0.1 --port 8000`

Secrets go in `.env` (git-ignored, never deployed): `GEMINI_API_KEY=...`
(comma-separated keys supported), `DATABASE_URL`, `KB_INGEST_PASSWORD`.

Frontend dev server (proxies /api to :8000):

```
cd frontend
npm install
npm run dev
```

`frontend/dist/` is committed on purpose — `app.py` serves it directly and the
Render deploy uses the pre-built assets. Rebuild after any JSX/CSS change
(`npm run build` in `frontend/`, or run `setup_prod.ps1`).

## The one rule that matters: the Physics Gate

```
py -3.13 -m pytest tests/
```

Any change touching simulation, curve fitting, parameter extraction, or
numerical output must keep this green. `PhysicsGuard` (`physics_validator.py`)
enforces monotonic Kr curves, endpoint constraints, Archie exponent ranges,
and more. A change that passes its own unit test but fails the gate is a
broken change. Full rationale: CLAUDE.md §1.

## Layout

The repo is flat — navigate by role, not by folder.

| Path | What |
|------|------|
| `app.py` | The monolith: routes, auth, sessions, SSE chat, tool execution, report endpoints, audit ledger (~9k lines) |
| `config.py` | Pydantic `Settings` — all env-driven config. Add new config here, never hardcode |
| `logger_setup.py` | JSON structured logging. Use the project logger, never `print()` |
| `physics_validator.py` | `PhysicsGuard` — the validation gate |
| `petrophysical_curves.py` | Brooks-Corey / LET relative-perm fitter, Pc model, endpoint normalization |
| `prc_physics.py` | Deterministic, unit-safe SCAL calculations |
| `prc_simulated_annealing.py` | Global Brooks-Corey curve match via simulated annealing |
| `physics_sandbox.py` | Fit→validate→auto-correct engine + restricted `run_sandboxed()` |
| `file_reader.py` | Multi-format reader (xlsx/xls/csv/pdf/docx/xml) → typed tables |
| `scal_file_handler.py` | SCAL-aware extraction, ground-truth inventory, structural validation |
| `extractors/` | Per-data-type parsers (MICP, KR, PC, RCAL, ...) |
| `data_validator.py` | Schema/range checks on extracted JSON |
| `rag_database.py` | ChromaDB vector store of analog wells (not wired into live chat) |
| `geological_graph.py` | SQLite knowledge graph (basins/formations/wells/samples) + `hybrid_search` fusing graph + vectors; uploads auto-link Well -[HAS_SAMPLE]-> Sample |
| `skills_engine.py` | Dispatch layer for the Hermes agentic skills |
| `hermes_skills_library/petroleum/` | The skill implementations, run in a child process |
| `report_generator.py`, `hviel_doc_engine.py` | Branded Word/PPTX/PDF report assembly |
| `dashboard_architect.py` | Universal SCAL/RCA dashboard JSON architect |
| `llm_insight_generator.py` | Narrative interpretation text from fitted params |
| `visualizer.py` | `extract_curve_coordinates()` (pure JSON) + thin PNG renderer |
| `grader.py` | Auto-grades AI responses against ground truth |
| `frontend/` | React + Vite UI |
| `tests/` | pytest suite — the physics gate lives here |

## Do-Not-Break invariants

- **`genkit==0.4.0`** + `genkit-plugin-google-genai==0.4.0` — genkit ≥ 0.5
  removed the `genkit.ai` module. Do not unpin.
- File ops use `pathlib.Path`, never the `os` module, in `app.py`,
  `scal_file_handler.py`, `file_reader.py` (historical `UnboundLocalError` on Render).
- Liveness is **`/health`** (public), not `/api/diag` (auth-gated, 401 before login).
- Rebuild `frontend/dist` after any JSX/CSS change.
- Never commit `.env`, `*.db`, `__pycache__/`.
- Physics gate green before any push.

> ⚠️ **Health grade ≠ fit quality.** `PhysicsGuard` scores *parameter
> legality*, not goodness-of-fit. Always read `parameters.r2` alongside
> `health.grade` before trusting a result.

## Operations

**Full reset (clears chat history + vector store):** stop the server, delete
`chat_history.db` and `chroma_db/`, restart. Schema re-initializes and `books/`
re-embeds automatically. KB health: `GET /api/kb/status` — `chunk_count` must
stay above 100.

**Key rotation:** update `GEMINI_API_KEY` / `DATABASE_URL` /
`KB_INGEST_PASSWORD` in `.env` locally and in the Render dashboard
(Environment tab) for prod, then restart.

**Deploy (Render):** push to `master` — auto-deploys via `render.yaml`.
Persistent disk at `/data` keeps `chat_history.db` across deploys. Checklist
before pushing: gate green, `frontend/dist` current, no `.env`/`*.db` staged.

**Backup:** `backup_vault.ps1` bundles git history + DB dump + env snapshot
into `vault_backups/`.

| Symptom | Fix |
|---------|-----|
| Chat returns no response | `GEMINI_API_KEY` expired or rate-limited — rotate |
| KB chunk count < 100 | Re-ingest via `POST /api/kb/ingest` |
| Physics score always 100 on bad data | `PhysicsGuard` not called — check `_format_tool_response` in `app.py` |
| Port 8000 already in use | Kill the previous server instance |
| `psycopg2` connection refused | Verify `DATABASE_URL` in `.env` |

## Known technical debt

1. `app.py` is a ~9k-line monolith — split by concern incrementally, keeping
   the gate green at each step. Understand the session-cache and provenance
   invariants (CLAUDE.md §4) first; they are subtle and load-bearing.
2. Anti-hallucination is regex band-aids, not architecture — prefer extending
   `geological_graph` / `physics_sandbox` over adding more output filters.
3. Two test-type classifiers can disagree (`SCALFileHandler.identify()` vs
   `file_reader._detect_test_type`) — unify to one scorer.

## More

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — LLM, RAG, skills, and security architecture
- [docs/DEVELOPER_DOCS.md](docs/DEVELOPER_DOCS.md) — API endpoints, DB schema, SSE protocol
- [CLAUDE.md](CLAUDE.md) — engineering rules, physics gate, security audit log
