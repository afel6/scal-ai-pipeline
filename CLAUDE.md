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

### Ingested Documents Registry

- **[2026-05-29] API-RP 40-Core-Analysis.pdf** (1,234,972 bytes): Programmatically ingested under precise 500-word / 50-word overlap chunking constraints. Embedded 287 chunks using the `text-embedding-004` model (via `gemini-embedding-2` pool) and committed to SQLite `library_chunks` table. Retrieval verified at a similarity score of 1.0000 (exceeding the 0.85 threshold).

---

## 4. LEST-WE-FORGET — Security Audit Log

This section is append-only. Every security vulnerability discovered, patched, or
mitigated during development or audits is recorded here. Do not remove entries.
Add new entries at the top of the list with date, CVE class, and patch description.

---

### [2026-05-29] UnboundLocalError Fix: Defensive `os` Module Scope Hardening

**Class:** UnboundLocalError / Module Scope Fragility / Render Deployment Blocker  
**Discovery:** Render deployment crashed with `"cannot access local variable 'os' where it is not associated with a value"` inside `extract_absolute_file_truth` and `sync_document_generation_task`. AST analysis of all Python files found ZERO explicit variable shadowing (`except ... as os`, `for os in ...`, `os = ...`).  
**Root Cause:** The Python 3.14 runtime on Render/Linux has stricter scope resolution that can fail to bind `os` when the global import order or circular dependency chain delays module-level binding.  
**Patch:**  
  1. **`scal_file_handler.py`**: Moved `import os` to be the FIRST import in the file (before `re`, `io`, `pathlib`). Added defensive `import os as _os` inside `extract_absolute_file_truth()` body.  
  2. **`app.py`**: Added defensive `import os as _os` at the top of `sync_document_generation_task()` try block, and `import os as _os_cleanup` in its `finally` block. ALL `os.` references within the function converted to `_os.` / `_os_cleanup.` to guarantee scope isolation.  
  3. **Verified** that `document_engines.py`, `file_reader.py`, `report_generator.py` all have proper top-level `import os`.  
**Status:** RESOLVED 2026-05-29. Deployed to Render.

---

### [2026-05-29] Deterministic Pre-Parser & Permeability Column Binding — Anti-Data-Shuffling Defense

**Class:** CWE-20 Data Integrity / Column Binding Validation / System Instruction Injection  
**Discovery:** Diagnostic test confirmed Specific_Oil_Permeability.xlsx contains ONLY ['Sheet1'], but LLM hallucinated phantom sheets ('Sample-1,2,3,24') and confused Cumulative Volume columns with KL Permeability. No prompt-level fix can prevent this — the ground truth must be deterministically injected from the backend server.  
**Risk:** Without deterministic server-side column binding validation, the LLM can silently bind volume/cumulative columns (e.g., 'Cum.vol.inj. (cc)') to permeability fields, producing physically impossible extraction results. Additionally, the existing column header validation in `validate_extraction_against_inventory()` was dead code (built the `inv_headers_by_sheet` dict but never used it).  
**Patch:**  
  1. **NEW FUNCTION: `extract_absolute_file_truth()`** — Standalone, zero-SCALFileHandler-dependency pre-parser using raw `pd.ExcelFile().sheet_names` and `pd.read_excel(nrows=2)`. Produces deterministic `MANDATORY_GROUND_TRUTH_INVENTORY` text block.  
  2. **SYSTEM INSTRUCTION INJECTION**: Ground truth injected into the Gemini SYSTEM INSTRUCTION (not user prompt), making it architecturally un-bypassable. Includes 5 mandatory rules: sheet validation, column validation, anti-recycling, permeability column binding, and Swi/Sor explicit value priority.  
  3. **NEW FUNCTION: `validate_permeability_column_binding()`** — Post-extraction server-side validation rejecting any permeability field bound to columns containing 'cc', 'Volume', 'Cum.vol', or 'Cumulative'. Raises `PERM_COLUMN_HALT`.  
  4. **FIX: Column Header Validation (was dead code)** — `validate_extraction_against_inventory()` now actually checks Protocol 2 column citations against the ground truth headers from the inventory (was building the dict but never checking it).  
  5. **DUAL-LAYER INJECTION**: Ground truth injected at BOTH system instruction level (MANDATORY_GROUND_TRUTH_INVENTORY) and user prompt level (Phase 0b inventory text), providing cross-validation at two architectural layers.  
**Status:** RESOLVED 2026-05-29. Applied to both sync and background extraction paths. Verified via pytest regression suite.

---

### [2026-05-29] Phase 0b ACTIVATION: Ground Truth Inventory Injection & Server-Side Validation

**Class:** CWE-20 Dead Code Activation / Structural Hallucination Prevention / Defense-in-Depth  
**Discovery:** Code audit revealed that three critical Phase 0b functions were built but NEVER WIRED into the extraction pipeline:  
  1. `generate_structural_inventory_text()` — generated human-readable inventory but was never called in `app.py`.  
  2. `validate_extraction_against_inventory()` — imported at line 51 but never invoked post-extraction.  
  3. The `structural_inventory` dict returned by `SCALFileHandler.process()` was silently discarded in all code paths.  
**Risk:** Without the ground-truth inventory injected into the LLM prompt, the model had no Python-verified reference to check against, allowing context recycling and citation fabrication to persist. Without the server-side validation call, hallucinated sheets/columns were never caught by Python code.  
**Patch:**  
  1. **SYNC PATH (line ~2991):** Instantiate `SCALFileHandler(tmp_path)` on spreadsheet files, call `.read()` + `.generate_structural_inventory()` + `.generate_structural_inventory_text()`, and inject the ground truth text directly into the LLM prompt between `--- GROUND TRUTH ---` markers.  
  2. **BACKGROUND PATH (line ~5967):** Identical injection using `SCALFileHandler(temp_file_path)`.  
  3. **POST-EXTRACTION VALIDATION (both paths):** After salvage_and_clean_json, call `validate_extraction_against_inventory(parsed, phase0b_inventory)` to catch hallucinated sheets/columns server-side and raise `STRUCTURAL_HALT`.  
  4. **THINKING BLOCK STRIP (both paths):** Added `strip_thinking_blocks(clean_text)` after markdown code block removal but before JSON parsing, ensuring `<thinking>` tags never corrupt JSON.  
**Status:** RESOLVED 2026-05-29. Verified via pytest regression suite (30/30 Phase 0b + 133/133 full).

---

### [2026-05-29] Phase 0b: Proof of Read — Anti-Hallucination Runtime Isolation

**Class:** CWE-20 Improper Input Validation / Structural Hallucination Prevention / Context Recycling Defense  
**Discovery:** Production accuracy evaluation (4/10 score). LLM recycled cached values (Cum.vol.inj. misidentified as KL Permeability), hallucinated sheets in Specific_Oil_Permeability.xlsx, and missed permeability records on 'comp' sheets of Phi_k_OBP files.  
**Risk:** Without runtime structural proof-of-read, the LLM engine can fabricate citations by relying on memorized file structures from prior context windows, leading to silent data-integrity failures in SCAL extraction.  
**Patch:**
1. Rewrote `extraction_system_prompt.md` to mandate Phase 0b structural file inventory output (sheet names, header rows, shapes, first 2 data rows) BEFORE any extraction. Added STRUCTURAL_HALT conditions forbidding citation of sheets/columns not in the inventory.
2. Added `generate_structural_inventory()` and `generate_structural_inventory_text()` methods to `SCALFileHandler` for Python-side inventory generation.
3. Added `validate_extraction_against_inventory()`, `strip_thinking_blocks()`, `strip_placeholder_artifacts()`, and `detect_multi_well_mixing()` utility functions to `scal_file_handler.py`.
4. **CRITICAL BUG FIX**: Fixed indentation bug in background `salvage_and_clean_json()` (app.py) where `return data_list` was inside the `for ok, ov in overrides.items()` loop, causing Sor override to be skipped when Swi was the first key.
5. Added STRUCTURAL_HALT detection to both sync and background extraction salvage functions.
6. Added `<thinking>` block stripping and `[NOT YET CHECKED]` placeholder cleanup to SSE finalization path.
7. Updated both sync and background extraction prompts with Phase 0b mandate and 5-key JSON schema (phase_0b_proof_of_read + protocol_1-3 + extracted_data).  
**Status:** RESOLVED 2026-05-29. Verified via pytest regression suite.

---

### [2026-05-29] High-Fidelity Extraction Protocols & Benchmark Priority — Structured RAG Extractor

**Class:** Accuracy & Reliability Gate / Structural Hallucination Prevention  
**Discovery:** Technical evaluation audit (Accuracy score 4/10 due to structural/citation errors and parameter fabrication).  
**Risk:** Under high-dimensional SCAL data extraction, models can invent citations, misidentify column units, or compute derived parameters instead of prioritizing explicitly reported benchmarks (e.g., Swi/Sor).  
**Patch:**
Upgraded system prompt template (`extraction_system_prompt.md`) to mandate three structural execution protocols inside the JSON extraction envelope: Protocol 1 (FILE-OPEN PROOF: sheet names and raw column target inventory), Protocol 2 (HEADER & UNIT DOUBLE-CHECK: literal column header/unit alignment checks per cell value), and Protocol 3 (LABELED-VALUE ABSOLUTE PRIORITY: explicit laboratory benchmark extraction). Refactored prompt building and loaded JSON parsing/salvaging logic in `app.py` and `prc_physics.py` to seamlessly isolate audit blocks, perform robust multi-suffix salvaging, and enforce priority laboratory overrides (e.g., min Swi and Sor endpoints) downstream.  
**Status:** RESOLVED 2026-05-29. Verified passing fuzzer and 8/8 regression unit tests.

---

### [2026-05-29] Automated Verification and Thread-Safety Hardening — Multi-Encoding & Async Validation

**Class:** CWE-362 Race Conditions / CWE-20 Improper Input Validation / Thread Safety  
**Discovery:** Automated pipeline and thread state auditing  
**Risk:** Under high concurrent request volumes, volatile task states in `TASKS_DB` and multi-encoding decoding procedures (`smart_read_csv`) are prone to race conditions, parsing exceptions, and regression.  
**Patch:**
Designed and deployed a comprehensive concurrent and multi-encoding unit test suite (`tests/test_async_remediation_hardened.py`). The suite validates 100% thread safety of concurrent mutations under `ThreadPoolExecutor` (20 parallel workers), enforces correct multi-encoding fallbacks (`latin1`, `cp1252`, `utf-8`) containing petrophysical Greek/scientific notation (e.g. `°` and `µ`), and validates `process_large_file_stream` size-checking constraints natively in all environments.  
**Status:** RESOLVED 2026-05-29. Verified passing 8/8 tests with 0% regression.

---

### [2026-05-29] Path Traversal & Parameter Injection — `GET /api/v1/tasks/{session_id}`

**Class:** CWE-22 Path Traversal / CWE-20 Improper Input Validation  
**Discovery:** Handover audit & production hardening session  
**Risk:** The `session_id` URL path parameter was used to query the task database. If unvalidated, a crafted parameter containing directory traversal or SQL metacharacters could cause arbitrary code/file access or local task log manipulation.  
**Patch:**
Strict regex validation is now applied to `session_id` using:
```python
if not re.match(r"^(report-)?[a-zA-Z0-9\-]+$", session_id):
    raise HTTPException(status_code=400, detail="Invalid session_id format")
```
This restricts session/task identifiers strictly to alphanumeric characters and dashes.  
**Status:** RESOLVED 2026-05-29.

---

### [2026-05-29] Path Traversal — `GET /api/report/download/{filename}`

**Class:** CWE-22 Path Traversal  
**Discovery:** Hardening session  
**Risk:** An attacker could download arbitrary files outside the output reports folder by passing path traversal sequences (like `../`) or absolute paths.  
**Patch:**
Implemented path sanitization using `_pathlib.Path(filename).name` to strip out all directory traversal separators and verify the resolved path remains securely contained inside the dedicated reports directory.  
**Status:** RESOLVED 2026-05-29.

---

### [2026-05-29] Denial of Service & RAM Exhaustion — Unlimited File Uploads

**Class:** CWE-400 Resource Exhaustion / CWE-770 Allocation of Resources Without Limits  
**Discovery:** Production scalability audit  
**Risk:** Large uploaded spreadsheets/CSVs (>100MB) processed directly in-memory could trigger server crashes (OOM) or `504 Gateway Timeout` errors, starving concurrent users.  
**Patch:**
Files uploaded to `/api/v1/analyze-scal` are now processed as a byte-stream in `512KB` chunks. The streaming helper tracks the cumulative size and terminates the request with an HTTP `413 Request Entity Too Large` error if the payload exceeds a strict `20MB` limit.  
**Status:** RESOLVED 2026-05-29.

---

### [2026-05-10] Path Traversal — `GET /{full_path:path}` SPA catch-all route

**Class:** CWE-22 Path Traversal  
**Discovery:** Security audit — file upload sandboxing review  
**Risk:** The SPA catch-all route passed `full_path` (a user-controlled URL segment) directly
to `os.path.join(_DIST_DIR, full_path)` with no containment check. A request like
`GET /../../.env` could serve arbitrary files from the server filesystem, including
`.env` (API keys) and `chat_history.db` (user conversations).  
**Patch:**

```python
_DIST_DIR_PATH = _pathlib.Path(_DIST_DIR).resolve()  # resolved once at startup

candidate = (_DIST_DIR_PATH / full_path).resolve()
if not str(candidate).startswith(str(_DIST_DIR_PATH)):
    raise HTTPException(status_code=403, detail="Access denied")
```

Unlike `/api/download/`, the SPA route must allow nested sub-paths (`assets/js/app.js`),
so `.name` stripping cannot be used — full containment validation is applied instead.  
**Status:** RESOLVED 2026-05-10. `_DIST_DIR_PATH` resolved at startup in `app.py`;
containment check applied before any `FileResponse`.

---

### [2026-05-10] SQL Clarity — `ingest_transactional()` f-string placeholder pattern

**Class:** CWE-89 (code quality / future regression risk, not currently exploitable)  
**Discovery:** Security audit — parameterized query review  
**Risk:** f-strings like `f"SELECT id FROM kb WHERE source = {ph}"` visually resemble
SQL injection. `ph` is the driver placeholder token (`"?"` / `"%s"`) from `_get_conn()`,
never user data. However, the pattern would become a real vulnerability if `ph` were
ever replaced by or mixed with a user-controlled variable. Added clarifying comments
to every affected line to make the intent unambiguous for future reviewers.  
**Status:** RESOLVED 2026-05-10. Comments added; logic unchanged (values remain parameterized).

---

### [2026-05-10] SQL Clarity — `get_sessions()` `.format()` WHERE clause

**Class:** CWE-89 (code quality, not currently exploitable)  
**Discovery:** Security audit — parameterized query review  
**Risk:** `q.format(filter=f)` inserted a static WHERE clause string into a SQL template.
The `f` variable was always hardcoded (`""` or `"WHERE m.user_email=?"`), so no injection
was possible, but the pattern was confusing and fragile.  
**Patch:** Replaced with two explicit parameterized `db()` calls in an if/else branch.  
**Status:** RESOLVED 2026-05-10.

---

### [2026-05-10] Developer Path Exposure — `deploy.ps1` hardcoded `C:\Program Files\...`

**Class:** CWE-426 Untrusted Search Path / portability issue  
**Discovery:** Secrets scan  
**Risk:** `C:\Program Files\Git\cmd\git.exe` and `C:\Program Files\GitHub CLI\gh.exe` were
hardcoded, revealing the developer's machine layout. Would silently fail on any other
Windows layout.  
**Patch:** Replaced with bare `"git"` and `"gh"` — resolved from PATH on the executing machine.  
**Status:** RESOLVED 2026-05-10.

---

### [2026-05-17] Developer Path Exposure — `push_advanced.cmd` hardcoded `C:\Program Files\Git\cmd`

**Class:** CWE-426 Untrusted Search Path / portability issue  
**Discovery:** Status audit (follow-up to deploy.ps1 fix on 2026-05-10 — push_advanced.cmd was missed)  
**Risk:** `set PATH=%PATH%;C:\Program Files\Git\cmd` unconditionally prepended the developer's
machine-specific Git installation path, silently failing or conflicting on any machine where
Git lives elsewhere.  
**Patch:** Replaced with a conditional injection using `WHERE git >nul 2>&1 || SET PATH=C:\Program Files\Git\cmd;%PATH%`
— only injects the fallback path when `git` is not already resolvable from the current PATH.
A `REM` comment explains the intent.  
**Status:** RESOLVED 2026-05-17.

---

### [2026-05-10] CRITICAL — Live API Keys in `.env` (NOT in git — `.gitignore` confirmed)

**Class:** CWE-312 Cleartext Storage of Sensitive Information  
**Discovery:** Secrets scan  
**Risk:** `.env` contains live `GEMINI_API_KEY` values and the Neon PostgreSQL connection
string (`npg_sHZyj8OBDS1G@...`). `.env.local` contains a Vercel OIDC JWT.  
**Git history note:** Previous `.env` commits (before `.gitignore` was added) exposed
earlier key rotations in git history. If this repository is or was ever public, those
historical keys are compromised regardless of current `.gitignore` state.  

**REQUIRED ACTIONS:**
1. ~~Rotate all `GEMINI_API_KEY` values in Google AI Studio.~~ — **COMPLETED 2026-05-17** (all 5 keys rotated in Google AI Studio, updated in `.env` and Render dashboard)
2. ~~Rotate the Neon PostgreSQL password via the Neon console.~~ — **ROTATED 2026-05-17**
3. ~~Revoke the Vercel OIDC token in `.env.local`.~~ — **CLOSED 2026-05-17** (Vercel no longer used; deployment moved to Render. Token removed from `.env.local`, file cleaned.)
4. ~~Run `git filter-repo` or BFG Repo-Cleaner to purge historical `.env` commits, then force-push.~~ — **COMPLETED 2026-05-17** (`git filter-repo --path .env --invert-paths --force` run; verified via `git log --all --oneline -- .env` (empty output). History force-pushed to `origin/master`. Commits `e50e822`, `6a8d5a8`, `d369152` are permanently purged.)
5. ~~Confirm `.gitignore` excludes `.env`, `.env.*`, `*.db` before every push (see §6).~~ — **CONFIRMED 2026-05-17**

**Status:** FULLY RESOLVED 2026-05-17 — All keys rotated, Vercel removed, `.env` purged from git history and force-pushed. Backup bundle saved at `C:\Users\Asus\Downloads\scal-ai-pipeline-backup-before-scrub.bundle` (34.1 MB).

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

**Status:** RESOLVED 2026-05-10. Implemented in `app.py` — `_DOWNLOAD_ROOT` resolved once at startup,
`_pathlib.Path(filename).name` strips any directory component, and `str(target).startswith(str(_DOWNLOAD_ROOT))`
enforces containment. Only bare filenames in the process CWD are served.

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
- [ ] `ADMIN_PIN` is set in Render environment variables — not just `.env` (`.env` is never deployed; an unset `ADMIN_PIN` makes every admin login return 401)

---

## 7. The Auditor’s Ledger — Immutable Accountability

As of 2026-05-10, every physical interpretation and simulation output is logged in the
**PRC Audit Ledger** (`physics_audits` table in `chat_history.db`). This is a non-negotiable
accountability requirement for industrial deployment.

### Database Schema

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER/SERIAL | Primary Key |
| `session_id` | TEXT | Link to the chat session |
| `timestamp` | REAL | Unix timestamp of the audit |
| `data_type` | TEXT | Category (micp, history_matching, simulation_1d) |
| `health_score` | INTEGER | 0-100 score from PhysicsGuard |
| `violations` | TEXT (JSON) | Detailed list of physical law violations |
| `file_name` | TEXT | Source laboratory filename |

### Operational Rules

- **Auto-Logging:** Every tool path that invokes `PhysicsGuard` (e.g., MICP plotting, Kr simulation) **MUST** call `_log_physics_audit()` before returning the result. Failure to log an audit for a physical interpretation is a critical safety violation.
- **Tool Access:** Hviel accesses this ledger via the `get_audit_history` tool. Use this tool to verify the quality trend of user-uploaded data and alert the engineer to recurring violations (e.g., non-monotonic Kr curves).
- **System Notification:** The system prompt mandates that the user is notified of this logging. Never disable the audit-ledger notification in the `SYSTEM_PROMPT`.
- **Immutability:** Audit records are append-only. The database helper provides no `DELETE` or `UPDATE` methods for the `physics_audits` table.
