# SCAL AI Pipeline — Hviel

FastAPI backend + React frontend for Special Core Analysis (SCAL) data:
upload lab spreadsheets (MICP, KR, PC, FRF/RI, NMR, RCAL, wettability,
formation damage), extract them deterministically, validate the physics, chat
over the results, and generate reports. The AI agent persona is **Hviel**.
PVT fluid reports are out of scope — they are rejected with a pointer to the
PVT pipeline (Aviel, port 8001).

## Quickstart

```
run_local.cmd          # backend on http://127.0.0.1:8000 (login PIN 1509)
kill_8000.cmd          # free the port if a previous run is stuck
```

Backend by hand: `.venv_win\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000`

Frontend dev server (proxies /api to :8000):

```
cd frontend
npm install
npm run dev
```

`frontend/dist/` is committed on purpose — `app.py` serves it directly and the
Render deploy uses the pre-built assets.

## Layout

| Path | What |
|------|------|
| `app.py` | The whole backend: routes, auth, sessions, LLM chat, report generation |
| `scal_file_handler.py` | Deterministic spreadsheet read → identify → extract pipeline |
| `extractors/` | Per-data-type parsers (MICP, KR, PC, RCAL, ...) |
| `petrophysical_curves.py`, `prc_physics.py` | Curve fitting + physics validation |
| `hermes_skills_library/petroleum/` | Runtime analysis skills executed by `skills_engine.py` |
| `frontend/` | React + Vite UI |
| `tests/` | pytest suite (`.venv_win\Scripts\python -m pytest tests/ -q`) |

## More

- [HANDOVER.md](HANDOVER.md) — full onboarding: environment, credentials, deploys
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CODEBASE_ORGANIZATION.md](docs/CODEBASE_ORGANIZATION.md)
- [docs/PRC_MAINTENANCE_GUIDE.md](docs/PRC_MAINTENANCE_GUIDE.md) — ops runbook
