# Sovereign Engineering Mental Model — PRC SCAL AI Pipeline

This file defines the non-negotiable engineering rules for the PRC SCAL AI Pipeline
(Hviel). Every contributor and AI assistant working on this codebase must internalize
and enforce these rules without exception.

---

## 1. Physics Integrity Gate

**Every code change that touches simulation, curve fitting, parameter extraction, or
any numerical output MUST be validated against `physics_validator.py` before commit.**

```
python physics_validator.py
```

A change that passes unit tests but fails the physics validator is a broken change.
Do not merge it.

### What the validator enforces

- Krw and Kro are monotonic in the correct directions across the saturation range
- Krw(Swi) = 0, Kro(1 − Sor) = 0 (endpoint constraints)
- Brooks-Corey exponents nw, no > 0; LET parameters L, E, T > 0
- Residual saturations: Swr + Snr < 1 (physically meaningful two-phase system)
- Capillary pressure: drainage Pc is strictly positive; imbibition Pc is ≤ 0 at Sor
- Archie exponents: m ∈ [1.3, 3.5], n ∈ [1.5, 3.0] for typical reservoir rock
- Resistivity Index: RI = 1.0 at Sw = 1.0 (fully brine-saturated normalization)
- All output arrays are finite (no NaN, Inf) and within physically plausible bounds

### Change categories that require validation

| Category | Validator required |
|---|---|
| `simulation_core.py` changes | Always |
| `app.py` `_execute_tool()` or `_format_tool_response()` changes | Always |
| New tool function declarations added to `_HVIEL_TOOLS` | Always |
| `hviel_doc_engine.py` data extraction changes | Always |
| Frontend plot rendering (`KrPlot.jsx`, future plot components) | Run visual spot-check against validator output |
| Pure UI / CSS / auth changes | Not required |

---

## 2. Industrial Brutalist UI Aesthetic

The PRC SCAL AI Pipeline UI follows the **Industrial Brutalist** design language.
This is not negotiable for demo, production, or internal builds.

### Core principles

- **High contrast.** Dark backgrounds (`#030303`, `#07070d`). Text is near-white.
  Accent colors are amber/gold (`#FFD700`, `#D97706`) and sky blue (`#38bdf8`).
  No pastels. No gradients that soften the feel.
- **Data-dense.** Every pixel earns its place. No decorative whitespace. Charts
  fill their containers. Tooltips show four decimal places.
- **Monospace for data.** All numerical output, parameter values, tool responses,
  and chart labels use `font-family: monospace`. Prose uses Outfit/Inter.
- **No animations on data.** Charts set `isAnimationActive={false}`. Data does not
  bounce or fade in. The only animations allowed are streaming cursor (`streaming-cursor`)
  and status indicators (pulse on live nodes).
- **Glassmorphism surfaces use CSS tokens.** Never hardcode `rgba()` values inline
  on glass surfaces. Use `var(--prc-glass)`, `var(--prc-border)`, `var(--prc-gold)`.
- **Borders are subtle, not decorative.** `border-yellow-900/40` is the standard
  panel border. Heavier borders (`border-yellow-500`) are reserved for active/focus states.
- **Error states are red, not yellow.** `var(--prc-red)` (#dc2626) for all error UI.
  Streaming state uses `streaming-ring` and `streaming-cursor` classes.

### Component rules

```
KrPlot    — dark bg (#07070d), yellow border, custom footer legend, no Recharts Legend
Chat UI   — msg-bubble with fadeSlideUp, streaming-cursor on live assistant output
Auth      — auth-input / auth-button classes, never raw Tailwind on form elements
Headers   — PRC brand: "PRC Petrophysics Engine" in yellow uppercase tracking-[0.2em]
```

### What to reject in code review

- Rounded corners > `rounded-2xl` on data panels
- White or light backgrounds anywhere except modals
- Default browser scrollbars (always override with custom 3px amber scrollbar)
- Recharts default Legend (use custom footer legend instead)
- `text-blue-*` for primary UI (blue is only for Krw data series)

---

## 3. RAG System — Knowledge Hierarchy

The RAG system (196 chunks from `books/`) represents ground truth for all
petrophysical definitions, standards, and interpretive guidelines. Hviel must
follow this hierarchy strictly:

```
1. books/ embeddings    — Primary source. Always cite. Always prefer.
2. Structured tool output — Simulation results, fitted parameters, calculated values.
3. LLM general knowledge — Last resort only. Must be flagged as "general knowledge,
                            not from PRC technical library."
```

### Enforcement rules

- If a user asks for a definition or equation (Archie, Leverett J, Brooks-Corey,
  Burdine, Mualem), the system prompt instructs Hviel to answer from RAG context first.
  If the RAG context does not contain the answer, state that explicitly before falling
  back to general knowledge.
- Never hallucinate petrophysical parameters. If a specific Libyan field value
  (porosity, Swi, Kro_max) is requested and is not in the RAG context or user-uploaded
  file, say so.
- The `/api/kb/ingest` endpoint is password-protected. Only ingest PRC-approved
  technical documents (API RP 40, SCAL standards, internal field studies).
- RAG chunk count must be monitored via `/api/kb/status`. If chunk count drops below
  100, the knowledge base is degraded — raise an alert before the next session.

### Adding documents to the knowledge base

```
POST /api/kb/ingest
Content-Type: multipart/form-data
password=<KB_INGEST_PASSWORD>
file=<pdf_or_txt>
```

Documents must be in English. Arabic field reports must be translated before ingestion.
Do not ingest vendor marketing materials, datasheets, or content not peer-reviewed
or standards-body approved.

---

## 4. LEST-WE-FORGET — Security Audit Log

This section is append-only. Every security vulnerability discovered, patched, or
mitigated during development or audits is recorded here. Do not remove entries.
Add new entries at the top of the list with date, CVE class, and patch description.

---

### [2026-05-10] Path Traversal — `/api/download/{filename:path}`

**Class:** CWE-22 Path Traversal  
**Discovery:** Code audit during production hardening session  
**Risk:** A crafted `filename` value containing `../` sequences could escape the
intended output directory and serve arbitrary files from the server filesystem,
including `.env`, `chat_history.db`, or Python source files.  
**Patch:** The route handler must validate that the resolved path stays within the
permitted output directory before serving the file. Patch pattern:

```python
import pathlib

ALLOWED_DIR = pathlib.Path(".").resolve()

@app.get("/api/download/{filename:path}")
async def download_file(filename: str):
    target = (ALLOWED_DIR / filename).resolve()
    if not str(target).startswith(str(ALLOWED_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(target))
```

**Status:** Patch pattern documented. Verify implementation in `app.py` at the
`/api/download/` route before next external demo or user-facing deployment.

---

### [2026-05-10] SQL Injection — `db()` helper raw string interpolation

**Class:** CWE-89 SQL Injection  
**Discovery:** Code audit during production hardening session  
**Risk:** Any call site that constructs a SQL string with f-string or `%`
interpolation instead of parameterized queries allows injection via user-controlled
input (session_id, email, message text).  
**Patch:** All `db()` calls must use the parameterized form:

```python
# CORRECT — parameterized
db("INSERT INTO m (sid, role, text) VALUES (?, ?, ?)", (sid, role, text))

# FORBIDDEN — interpolation
db(f"INSERT INTO m (sid, role, text) VALUES ('{sid}', '{role}', '{text}')")
```

The `db()` helper itself is safe (passes args to cursor.execute). Audit all call
sites to confirm no f-string interpolation reaches a SQL string.  
**Status:** All current call sites in `app.py` confirmed parameterized as of
2026-05-10. Re-audit any new `db()` call added in future PRs.

---

### [2026-05-10] Sensitive File Exposure — `chat_history.db` and `.env`

**Class:** CWE-538 File and Directory Information Exposure  
**Discovery:** Static analysis during session  
**Risk:** If `.gitignore` scoping is incorrect, `chat_history.db` (contains full
user conversation history and email addresses) or `.env` (contains API keys) could
be committed to the repository and exposed publicly on GitHub.  
**Patch applied:**
- `.gitignore` confirmed: `*.db`, `.env`, `.env.*` are excluded
- `/dist/` scoped to repo root (not `dist/` which would match any depth)
- `frontend/dist/` intentionally tracked (build artifacts for Render static serving)
- `__pycache__/` and `scratch/` untracked via `git rm --cached`  
**Status:** Resolved. Verify with `git status` before every push.

---

## 5. Model and API Stability

The active Gemini model and API version are documented here to prevent regressions
during SDK upgrades.

| Parameter | Value | Reason |
|---|---|---|
| Model | `gemini-2.5-flash` | gemini-1.5-flash removed from v1beta; 2.0-flash restricted on AI Studio keys |
| API version | v1beta (SDK default) | Function calling (`tools` field) only available in v1beta, not v1 |
| SDK | `google-genai >= 1.16.0` | Legacy `google-generativeai` removed |
| Tools schema type strings | Uppercase (`"OBJECT"`, `"STRING"`, `"ARRAY"`, `"NUMBER"`) | Pydantic `Schema.type` Literal enum requires uppercase; lowercase causes silent null coercion and malformed wire JSON |
| `_generate()` non-streaming | `next(_generate(), fallback)` | `_generate` is a generator function; `return value` inside a generator does not return to the caller |

When upgrading `google-genai`, re-run the chat smoke test before pushing:

```
POST /api/chat  message="Run a Brooks-Corey simulation swr=0.2 snr=0.15 krw_max=0.65 kro_max=0.90"
Expected: STATUS=success, reply contains __PRC_PLOT__ and curves JSON
```

---

## 6. Deployment Checklist

Before every push to `master` (which triggers Render auto-deploy):

- [ ] `python physics_validator.py` passes
- [ ] `git status` shows no `.env`, `*.db`, or `__pycache__` files staged
- [ ] `frontend/dist/` is current (run `npm run build` in `frontend/` if JSX/CSS changed)
- [ ] `/api/diag` returns correct version string after deploy
- [ ] Chat smoke test passes (see §5)
- [ ] No new `db()` call sites use string interpolation
- [ ] New download paths (if any) use the path traversal guard from §4
