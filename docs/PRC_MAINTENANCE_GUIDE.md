# PRC SCAL AI Pipeline — Sovereign Maintenance Guide
**Classification:** Internal Technical Reference  
**Audience:** PRC Laboratory Engineers & System Administrators  
**Pipeline Version:** HUB-VER-14-PROD-READY

---

## 1. SYSTEM RESET PROCEDURES

### 1.1 Full System Reset (Clean Slate)

This clears all chat history, resets the knowledge base, and restarts the pipeline.

```powershell
# Step 1 — Stop the running server (Windows)
.\kill_8000.cmd

# Step 2 — Delete the SQLite session database
Remove-Item -Force chat_history.db -ErrorAction SilentlyContinue

# Step 3 — Clear the vector store (forces re-ingestion on next startup)
Remove-Item -Recurse -Force chroma_db\ -ErrorAction SilentlyContinue

# Step 4 — Restart the backend
python app.py
```

After restart, the system will re-initialize the database schema and re-embed any
documents found in `/books` automatically.

### 1.2 Session Database Reset Only

If you only want to clear conversation history without wiping the knowledge base:

```powershell
Remove-Item -Force chat_history.db
python app.py
```

### 1.3 Knowledge Base Reset

To wipe and rebuild the RAG vector store from scratch:

```powershell
# Delete the vector store
Remove-Item -Recurse -Force chroma_db\

# Re-ingest all books/ documents via the API (requires the server to be running)
# Replace KB_INGEST_PASSWORD with the value from your .env file
curl -X POST http://localhost:8000/api/kb/ingest `
     -F "file=@books/API-RP 40-Core-Analysis.pdf" `
     -F "password=YOUR_PASSWORD_HERE"
```

To check knowledge base status:
```
GET http://localhost:8000/api/kb/status
```
The `chunk_count` field must be > 100. If it is below 100, the knowledge base is
degraded and must be re-ingested before any engineering session.

---

## 2. API KEY ROTATION

### 2.1 Google Gemini API Key

1. Go to: https://aistudio.google.com/app/apikey
2. Create a new key and copy it.
3. Open `.env` in the project root with a text editor.
4. Replace the value of `GEMINI_API_KEY`:

```
GEMINI_API_KEY=AIzaSy_YOUR_NEW_KEY_HERE
```

5. If you have backup keys (`GEMINI_API_KEY1`, `GEMINI_API_KEY2`, etc.), update those too.
6. Restart the server: `python app.py`

**Verification:**
```
POST http://localhost:8000/api/chat
Body: {"message": "ping", "session_id": "test"}
```
The response should stream a reply within 3 seconds.

### 2.2 Neon PostgreSQL Password

1. Log into https://console.neon.tech
2. Navigate to your project → Settings → Reset Password.
3. Copy the new connection string.
4. Open `.env` and replace `DATABASE_URL`:

```
DATABASE_URL=postgresql://neondb_owner:NEW_PASSWORD@your-host.neon.tech/neondb?sslmode=require
```

5. Restart: `python app.py`

### 2.3 KB Ingest Password

This password protects the `/api/kb/ingest` endpoint from unauthorized document uploads.

1. Choose a new strong password.
2. Open `.env` and update:

```
KB_INGEST_PASSWORD=your_new_strong_password
```

3. If deployed on Render, update the environment variable in the Render dashboard:
   Dashboard → Your Service → Environment → `KB_INGEST_PASSWORD` → Edit.
4. Restart the service.

### 2.4 Security Rule: Never Commit `.env`

Before every git push, verify:

```powershell
git status
```

The `.env` file must **never** appear in staged changes. If it does:

```powershell
git rm --cached .env
git commit -m "chore: remove accidental .env staging"
```

---

## 3. UPDATING PHYSICS RULES WITHOUT AN AI ASSISTANT

All physics validation logic lives in a single file: `physics_validator.py`.
The `PhysicsGuard` class contains all rules. Each rule follows the exact same pattern —
you can add, remove, or modify rules without touching any other file.

### 3.1 Understanding the Rule Pattern

Every rule in `validate_kr()` or `validate_micp()` uses the `_check()` helper:

```python
self._check(
    <boolean condition that is True when data is VALID>,
    "RULE_NAME",
    "Human-readable explanation of what is wrong when this fires.",
    severity="HIGH",   # or "MEDIUM"
)
```

- `severity="HIGH"` deducts **15 points** from the Physics Health Score.
- `severity="MEDIUM"` deducts **5 points**.
- If the score drops below 90%, the AI issues a HOLD warning.
- If the score drops below 60%, the data is blocked from the simulator.

### 3.2 Adding a New Kr Rule

**Example:** Add a rule that flags any Sw value outside [0, 1].

Open `physics_validator.py` and add inside `validate_kr()`, after the existing range checks:

```python
# NEW RULE: Sw must be in [0, 1]
self._check(
    bool(np.all(sw_s >= 0.0) and np.all(sw_s <= 1.0)),
    "SW_RANGE",
    f"Water saturation outside [0, 1]: min={sw_s.min():.4f}  max={sw_s.max():.4f}",
    severity="HIGH",
)
```

No restart required for batch processing. For the live API, restart `python app.py`.

### 3.3 Adding a New MICP Rule

**Example:** Flag cases where maximum Hg saturation is below 50% (incomplete test).

Add inside `validate_micp()`:

```python
# NEW RULE: Incomplete MICP — max Hg sat below 50%
self._check(
    float(shg_s[-1]) >= 0.50,
    "MICP_INCOMPLETE_INTRUSION",
    f"Maximum Hg saturation = {shg_s[-1]*100:.1f}% — test appears incomplete "
    "(< 50% pore volume invaded). Extend pressure range before reporting.",
    severity="MEDIUM",
)
```

### 3.4 Changing Scoring Thresholds

In `PhysicsGuard`:

```python
_HIGH_DEDUCTION   = 15   # points deducted per HIGH violation
_MEDIUM_DEDUCTION = 5    # points deducted per MEDIUM violation
```

And in `generate_health_score()`:

```python
if score >= 95:  grade, icon = "A", "..."   # Change 95 to adjust the A threshold
elif score >= 80: grade = "B"
elif score >= 60: grade = "C"
else:             grade = "F"
```

The 90% HOLD threshold is enforced in the SYSTEM_PROMPT (Rule 0-D), not in Python.
To change it, search for `score < 90%` in the system prompt section of `app.py`.

### 3.5 Running the Physics Validator Standalone

```powershell
# Test with your own data
python -c "
import numpy as np
from physics_validator import PhysicsGuard

sw  = [0.20, 0.35, 0.50, 0.65, 0.80]
krw = [0.00, 0.04, 0.15, 0.31, 0.54]
kro = [0.90, 0.62, 0.34, 0.11, 0.00]

result = PhysicsGuard().validate_kr(sw, krw, kro).generate_health_score()
print('Score:', result['score'])
print('Grade:', result['grade'])
for v in result['violations']:
    print(' -', v['rule'], ':', v['detail'])
"
```

---

## 4. RUNNING THE BATCH ANALYTICS ENGINE

The batch processor at `batch_process.py` is a standalone CLI tool. It does not
require the web server to be running.

```powershell
# Create the uploads folder and drop your Excel/CSV files there
mkdir uploads

# Run the batch processor
python batch_process.py --input ./uploads --output PRC_BATCH_REPORT.xlsx

# With verbose column detection logging
python batch_process.py --input ./uploads --verbose
```

**Output:** `PRC_BATCH_REPORT.xlsx` with two sheets:
- **PRC Batch Summary** — one row per file with fitted parameters and physics score
- **Physics Violations** — detail on any file that failed the physics audit

**Supported file types:** `.xlsx`, `.xls`, `.csv`

**Auto-detected data types:** Kr (relative permeability), MICP, RI (resistivity
index), FF (formation factor). Files that cannot be identified are flagged as
`UNKNOWN` in the report.

---

## 5. PRODUCTION DEPLOYMENT (RENDER)

### 5.1 Environment Variables Required in Render Dashboard

Navigate to: Render Dashboard → scal-ai → Environment

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `GEMINI_API_KEY` | Google AI Studio key |
| `CLAUDE_API_KEY` | Anthropic key (if used) |
| `KB_INGEST_PASSWORD` | Knowledge base upload password |

All are set with `sync: false` — their values are never stored in `render.yaml`.

### 5.2 Persistent Disk

The Render service has a 1 GB persistent disk mounted at `/opt/render/project/src`.
This ensures `chat_history.db` survives every redeploy.

To verify the disk is active: Render Dashboard → scal-ai → Disks → `chat-db` (1 GB).

### 5.3 Deploy Checklist

Before pushing to `master`:

- [ ] `python physics_validator.py` passes (or `python -m pytest tests/` if tests added)
- [ ] `git status` — no `.env`, `*.db`, or `__pycache__` files staged
- [ ] `cd frontend && npm run build` — dist/ is current
- [ ] `/api/diag` returns correct version string after deploy
- [ ] Chat smoke test: send "Run a Brooks-Corey simulation swr=0.2 snr=0.15"
      → response must contain `__PRC_PLOT__` and a Physics Health Score footer

### 5.4 Triggering a Deploy

```powershell
git add .
git commit -m "chore: production update"
git push origin master   # triggers auto-deploy on Render
```

Monitor the deploy at: Render Dashboard → scal-ai → Logs

---

## 6. COMMON TROUBLESHOOTING

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Chat returns no response | `GEMINI_API_KEY` expired or rate-limited | Rotate key per §2.1 |
| KB chunk count < 100 | Vector store corrupted or deleted | Re-ingest per §1.3 |
| `chat_history.db` not persisting on Render | Disk not mounted | Verify disk in Render dashboard §5.2 |
| Physics score always 100 on bad data | `PhysicsGuard` not called | Check `_format_tool_response` in `app.py` |
| MICP routed to Kr tools | Wrong model keyword in tool call | Check Section 6 routing rules in `app.py` SYSTEM_PROMPT |
| Port 8000 already in use | Previous server instance running | Run `kill_8000.cmd` then restart |
| `chromadb` import error | Package not installed | `pip install chromadb>=0.4.0` |
| `psycopg2` connection refused | Neon DB unreachable or wrong URL | Verify `DATABASE_URL` in `.env` |

---

## 7. ARCHITECTURE QUICK REFERENCE

```
Request → FastAPI (app.py)
            ├── RAG lookup      (rag_database.py / ChromaDB)
            ├── Gemini LLM      (google-genai SDK, v1beta)
            │     └── Tool calls → _execute_tool()
            │                         ├── execute_python_simulation → simulation_core.py
            │                         └── fit_petrophysical_curve  → petrophysical_curves.py
            └── _format_tool_response()
                  ├── PhysicsGuard.validate_*()   (physics_validator.py)
                  ├── Plot JSON  →  __PRC_PLOT__ blocks
                  └── Physics footer  →  appended to every chart response

Frontend → React + Vite + TailwindCSS
  App.jsx → MessageRenderer.jsx → KrPlot.jsx / Mermaid.jsx / SimulationHeatmap.jsx
  SidebarTabs.jsx → KB status + Skills list
  AdminDashboard.jsx → Admin-only controls
```

---

*This document is maintained by the PRC AI Engineering Team.  
For issues, contact the system administrator or open a ticket.*
