# Sovereign SCAL AI — Engineering Operator's Manual

**Document Class:** PRC Internal Technical Reference  
**Version:** 2.0 — Production Architecture  
**System:** PRC Hviel SCAL AI Pipeline  
**Date:** May 2026  
**Classification:** Executive Board Briefing

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [The Physics Watchtower](#3-the-physics-watchtower)
   - 3.1 PhysicsGuard — Design Philosophy
   - 3.2 Relative Permeability (Kr) Compliance Checks
   - 3.3 MICP Compliance Checks
   - 3.4 Archie Resistivity Compliance Checks
   - 3.5 Capillary Pressure (Pc) Compliance Checks
   - 3.6 Health Scoring and Grading
4. [The Audit Ledger — Immutable Accountability](#4-the-audit-ledger--immutable-accountability)
5. [Gemini Multi-Modal Tool-Calling Architecture](#5-gemini-multi-modal-tool-calling-architecture)
6. [Database Schema and Row-Level Security](#6-database-schema-and-row-level-security)
7. [Security Architecture](#7-security-architecture)
8. [Deployment and Operational Checklist](#8-deployment-and-operational-checklist)

---

## 1. Executive Summary

The PRC Hviel SCAL AI Pipeline is a production-grade petrophysical intelligence platform built to ingest, validate, fit, and interpret Special Core Analysis (SCAL) laboratory data at the Petroleum Research Center (PRC) of Libya. The system pairs a **real-time physics compliance engine** with a **multi-modal AI assistant** running on Google Gemini 2.5 Pro, enabling engineers to process MICP, relative permeability, Archie resistivity, and capillary pressure datasets within a conversational interface while guaranteeing that every numerical result is physically lawful before it reaches the reservoir simulator.

Three design principles are non-negotiable:

| Principle | Enforcement Mechanism |
|---|---|
| No synthetic data reaches the reservoir without physics validation | `PhysicsGuard` blocks all violating datasets before tool response is emitted |
| All physical interpretations are permanently traceable | Immutable `physics_audits` Audit Ledger, append-only by design |
| User data is strictly isolated by identity | Row-Level Security (RLS) on every session read/write/delete operation |

The pipeline processes the following SCAL test types natively: Relative Permeability (Brooks-Corey / LET model fitting), Mercury Injection Capillary Pressure (MICP), Formation Factor and Resistivity Index (Archie), Leverett J-Function, Centrifuge / Porous-Plate Capillary Pressure, and Overburden Compaction curves.

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          PRC Hviel — System Architecture                         │
└─────────────────────────────────────────────────────────────────────────────────┘

  Browser (React 19 / Vite / Tailwind v4)
  │
  │  SSE stream  ──  GET /api/chat/stream?message=...&session_id=...&user_email=...
  │  File upload ──  POST /api/upload                                               
  │  Session ops ──  GET/DELETE /api/session/{sid}?email=...                       
  │  Auth        ──  POST /api/auth (PIN verification)                             
  │
  ▼
  FastAPI (app.py) — Python 3.13
  ├── Middleware: CORS, SlowAPI rate limiter (IP-keyed)
  ├── Auth Gate:  _verify_session_owner() — RLS on every session endpoint
  ├── DB Layer:   db() helper — SQLite WAL (dev) / PostgreSQL pool (prod)
  │
  ├── PRCChatAssistant (gemini-2.5-pro, multi-key HA pool)
  │   ├── RAG Retrieval  ─── KnowledgeBase.search_async() — cosine sim, top-k=15
  │   ├── Semantic Cache  ── MD5(message[:2000]+kb_ctx[:500]+history_last3)
  │   ├── Tool Dispatch   ── _execute_tool() → physics-validated JSON response
  │   └── SSE Bridge      ── asyncio.Queue → StreamingResponse (text/event-stream)
  │
  ├── Physics Watchtower  ─────────────────────────────────────────────────────────
  │   ├── PhysicsGuard        — real-time rule engine (Kr, MICP, Archie, Pc)
  │   ├── PhysicsValidator    — hard gate (Swi+Sor≤1, porosity bounds)
  │   └── _log_physics_audit()— append-only write to physics_audits table
  │
  ├── Curve Fitting Engine
  │   ├── KrCurveFitter       — Brooks-Corey / LET via Simulated Annealing
  │   ├── PRCThermodynamics   — J-Leverett Pc, Amott-Harvey wettability index
  │   └── SCALFileHandler     — Excel/CSV/TXT ingestion, column auto-mapping
  │
  ├── Document Engine (HvielDocEngine)
  │   └── .docx / .xlsx / .pptx generation from structured JSON schemas
  │
  ├── Skills Engine (SkillsEngine)
  │   └── Subprocess dispatch to hermes_skills_library/
  │
  └── Knowledge Base (RAG)
      └── SQLite/PG vector store — text-embedding-004 (768-dim), 600-word chunks
```

**Runtime data flow for a chat message:**

```
User message
  → RLS check (session ownership verified)
  → RAG retrieval (top-k=15, cosine threshold 0.35)
  → Semantic cache lookup (MD5 hash)
      ↳ HIT  → emit cached response via SSE
      ↳ MISS → Gemini 2.5 Pro generation with tool access
                  → Tool call? → _execute_tool()
                                   → PhysicsGuard validates output
                                   → _log_physics_audit() (if physics data)
                                   → JSON result injected into tool response
                → Token streaming via asyncio.Queue → SSE frames
  → Session persisted to DB
```

---

## 3. The Physics Watchtower

### 3.1 PhysicsGuard — Design Philosophy

`PhysicsGuard` (`physics_validator.py`) is a **stateful, chainable validator** that accumulates rule violations across one or more `validate_*` calls on a single dataset, then emits a structured health score and audit block. It is the last line of defence before any numerical result leaves the pipeline.

The guard is invoked inside `_execute_tool()` on every tool path that produces physical data. A result that fails the guard is **not suppressed** — it is delivered with a prominently flagged audit block that the system prompt instructs Hviel to report verbatim. An engineer receives the health score whether the data is clean or not.

**Severity model:**

| Severity | Deduction | Meaning |
|---|---|---|
| `HIGH` | −15 points | Hard physical law violation (monotonicity broken, impossible value) |
| `MEDIUM` | −5 points | Soft endpoint warning (data quality concern, not a hard impossibility) |

**Grading scale:**

| Grade | Score Range | Interpretation |
|---|---|---|
| A | ≥ 95 | All curves pass — PRC-Certified for reservoir simulation |
| B | 80–94 | Minor inconsistencies — review before simulator submission |
| C | 60–79 | Marginal quality — re-measurement recommended |
| F | < 60 | Critical violations — MUST NOT enter the simulator |

**Score formula:**

```
deduction = Σ(HIGH violations × 15) + Σ(MEDIUM violations × 5)
score     = max(0, 100 − deduction)
```

---

### 3.2 Relative Permeability (Kr) Compliance Checks

`PhysicsGuard.validate_kr(sw, krw, kro)` applies seven rules. The input arrays are sorted by `Sw` before evaluation to handle unsorted lab data gracefully.

| Rule ID | Severity | Physical Law Enforced |
|---|---|---|
| `KRW_MONOTONICITY` | HIGH | Krw must be non-decreasing with Sw — water phase flows more easily as water saturation rises |
| `KRO_MONOTONICITY` | HIGH | Kro must be non-increasing with Sw — oil phase is displaced as water saturation rises |
| `KRW_RANGE` | HIGH | Krw ∈ [0, 1] — relative permeability is a dimensionless fraction |
| `KRO_RANGE` | HIGH | Kro ∈ [0, 1] — same physical constraint |
| `KRW_ENDPOINT` | HIGH | Krw at maximum Sw ≤ 1.0 — no phase can exceed its own absolute permeability |
| `KRW_ZERO_AT_SWI` | MEDIUM | Krw(Swi) ≈ 0 — water is immobile at irreducible saturation |
| `KRO_ZERO_AT_SOR` | MEDIUM | Kro(1−Sor) ≈ 0 — oil is immobile at residual oil saturation |

**Tolerance:** Violations detected with tolerance `1e-4` to accommodate floating-point precision in lab data digitisation. The MEDIUM endpoint rules use threshold `0.01` (1% relative permeability) as the immobility boundary.

**Physical meaning of each rule in engineering context:**

- **KRW/KRO monotonicity:** A non-monotonic Kr curve implies the flowing phase locally reverses direction as saturation increases — physically impossible in a simple two-phase system. This typically signals measurement noise, data entry error, or mixed-cycle data (drainage points mixed with imbibition points).

- **Endpoint constraints (MEDIUM):** Krw(Swi) > 0 means water flows at irreducible saturation — this contradicts the definition of Swi and indicates either the scan did not start at true Swi or the connate water was mobilised during the measurement. Kro(1−Sor) > 0 means oil flows at residual saturation — this indicates Sor was not reached, resulting in overestimated sweep efficiency.

---

### 3.3 MICP Compliance Checks

`PhysicsGuard.validate_micp(pc, hg_sat)` applies four rules to Mercury Injection Capillary Pressure data. Input arrays are sorted by Pc (ascending) before evaluation.

| Rule ID | Severity | Physical Law Enforced |
|---|---|---|
| `MICP_NEGATIVE_PC` | HIGH | All Pc values must be positive — mercury injection (drainage) requires positive capillary pressure throughout the intrusion cycle |
| `MICP_ENTRY_PRESSURE` | HIGH | Entry pressure Pe > 0 psia — the threshold pressure at which mercury first enters the pore network; Pe ≤ 0 means mercury entered without overcoming capillary resistance (physically impossible) |
| `MICP_SATURATION_MONOTONICITY` | HIGH | Hg saturation must be non-decreasing with increasing Pc — mercury cannot spontaneously leave pores as pressure increases during drainage |
| `MICP_SAT_RANGE` | MEDIUM | Hg saturation ∈ [0, 1] — saturation is a volumetric fraction |

**Entry pressure detection:** The guard identifies Pe as the first Pc value where Hg saturation exceeds 1% (`shg > 0.01`), consistent with the industry convention that captures the true network entry threshold and ignores sub-threshold noise.

**MICP data routing rule (enforced in system prompt):** The system prompt explicitly forbids calling Kr simulation tools for MICP data. Calling `execute_python_simulation` (a Kr tool) on MICP data is flagged as a `CRITICAL FAILURE` in the tool dispatch instructions. The routing table in Section 0-B of the system prompt separates these data types by keyword detection.

---

### 3.4 Archie Resistivity Compliance Checks

`PhysicsGuard.validate_archie(x, y, model_type)` handles two sub-models sharing the same validation interface.

**Resistivity Index (RI) mode — `model_type="RI"`:**

| Rule ID | Severity | Physical Law |
|---|---|---|
| `RI_MONOTONICITY` | HIGH | RI must be non-increasing with Sw — as water saturation rises, the rock becomes more conductive, so RI decreases |
| `RI_RANGE` | HIGH | RI ≥ 1.0 — by definition RI = Rt/Ro ≥ 1 (at Sw < 1, the partially saturated rock is always more resistive than the fully brine-saturated baseline) |
| `RI_ENDPOINT` | MEDIUM | RI(Sw=1) < 1.1 — at full brine saturation, RI must be 1.0 (normalization condition of Archie's second equation) |

**Formation Factor (FF) mode — `model_type="FF"`:**

| Rule ID | Severity | Physical Law |
|---|---|---|
| `FF_MONOTONICITY` | HIGH | FF must be non-increasing with porosity — higher porosity means lower tortuosity and more conductive paths, so F decreases |
| `FF_RANGE` | HIGH | FF ≥ 1.0 — Formation Factor = Ro/Rw ≥ 1 by definition (rock is always less conductive than the pore fluid alone) |

**Archie parameter bounds (enforced by system prompt, not guard):**

Per CLAUDE.md and system prompt rules, Archie exponents are validated against physically representative ranges for reservoir rock:

| Parameter | Valid Range | Physical Basis |
|---|---|---|
| Cementation exponent `m` | [1.3, 3.5] | m < 1.3 implies fracture-dominated; m > 3.5 implies extreme tortuosity beyond known reservoir rocks |
| Saturation exponent `n` | [1.5, 3.0] | n < 1.5 implies non-Archie behaviour; n > 3.0 is rare and flags potential wettability or mixed-wet effects |

---

### 3.5 Capillary Pressure (Pc) Compliance Checks

`PhysicsGuard.validate_pc(sw, pc)` applies two rules to Centrifuge or Porous Plate Pc data.

| Rule ID | Severity | Physical Law |
|---|---|---|
| `PC_MONOTONICITY` | HIGH | Pc must be non-increasing with Sw — as water saturation increases (imbibition direction), capillary pressure decreases |
| `PC_RANGE` | HIGH | Pc ≥ −0.1 psia — drainage Pc is positive; imbibition Pc approaches zero at Sor |

---

### 3.6 Health Scoring and Grading

After all `validate_*` calls complete, `generate_health_score()` returns the following structured audit block:

```json
{
  "score":         85,
  "grade":         "B",
  "icon":          "⚠️",
  "violations": [
    {
      "rule":     "KRW_ZERO_AT_SWI",
      "severity": "MEDIUM",
      "detail":   "Krw(Swi) = 0.0312 ≠ 0 — water should be immobile at irreducible saturation (Swi)."
    }
  ],
  "rules_checked": 7,
  "summary":       "1 minor physical inconsistency detected — review before simulator submission.",
  "footer":        "⚠️ Physics Health Score: 85%  |  Audit Result: 1 minor physical inconsistency..."
}
```

The `footer` field is displayed verbatim in the chat UI. A score below 90% triggers a mandatory `HOLD` condition: Hviel must list every violation with its engineering implication and append "This data MUST NOT enter the reservoir simulator until the above violations are resolved."

**Legacy gate — `PhysicsValidator`:**

In addition to `PhysicsGuard`, a deterministic hard gate `PhysicsValidator.validate_core_physics()` blocks simulation parameter sets where:
- `Swi + Sor > 1.0` (physically impossible two-phase saturation sum)
- `porosity ≥ 1.0` or `porosity ≤ 0.0` (non-physical fractional porosity)

This gate raises `PhysicsEngineError` before the simulation even starts, preventing nonsense parameters from ever reaching the Brooks-Corey model.

---

## 4. The Audit Ledger — Immutable Accountability

### 4.1 Purpose and Design Mandate

The **PRC Audit Ledger** (`physics_audits` table) is an append-only record of every physical interpretation and simulation output produced by the pipeline. It provides a permanent chain of accountability for all numerical results: who submitted the data, when, what health score it received, and exactly which physical laws were violated.

This requirement is non-negotiable for industrial deployment. A drilling or completion decision based on SCAL data that failed physics validation must be traceable back to the specific lab measurement, the specific session, the specific violation, and the timestamp.

### 4.2 Database Schema

```sql
CREATE TABLE IF NOT EXISTS physics_audits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,      -- FK to sessions.sid
    user_email   TEXT,      -- Engineer who submitted the data
    timestamp    REAL,      -- Unix epoch of the audit
    data_type    TEXT,      -- 'micp' | 'simulation_1d' | 'kr_fit' | 'archie_ri' | 'archie_ff'
    health_score INTEGER,   -- 0–100 from PhysicsGuard
    violations   TEXT,      -- JSON array of {rule, severity, detail}
    file_name    TEXT        -- Source laboratory filename (if file upload triggered the audit)
);
```

**Immutability guarantee:** The `db()` helper and all application code provide no `UPDATE` or `DELETE` path for `physics_audits`. Session deletion cleans `physics_audits` by `session_id` only when the session itself is deleted by its verified owner — the audit record for a session is retained for the lifetime of that session.

### 4.3 Audit Logging Function

```python
def _log_physics_audit(sid, data_type, audit_res, file_name=None):
    db(
        "INSERT INTO physics_audits "
        "(session_id, timestamp, data_type, health_score, violations, file_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (sid, time.time(), data_type, audit_res["score"],
         json.dumps(audit_res["violations"]), file_name)
    )
```

`_log_physics_audit()` is called inside `_execute_tool()` on every tool path that invokes `PhysicsGuard`. Failure to log is a critical safety violation — the system prompt mandates that the engineer is informed of this logging on every session.

### 4.4 Hviel's Access to the Audit Ledger

The `get_audit_history` tool exposes the ledger to the LLM:

```python
"name": "get_audit_history",
"description": "Retrieves the historical record of physics audits (the Auditor's Ledger) for the current session."
```

Hviel is instructed to proactively use this tool to detect recurring violations — for example, if three consecutive files from the same well all produce non-monotonic Kr curves, this signals a systematic laboratory or digitisation error that the engineer must address before any results are submitted to the reservoir simulation team.

### 4.5 Audit Ledger in the Session Deletion Flow

```
DELETE /api/session/{sid}?email={email}
  → _verify_session_owner(sid, email)       ← RLS check first
  → DELETE FROM m WHERE sid=? AND user_email=?
  → DELETE FROM sessions WHERE sid=? AND user_email=?
  → DELETE FROM physics_audits WHERE session_id=?   ← no email filter needed:
                                                        ownership verified above
```

The `physics_audits` delete uses only `session_id` because `_verify_session_owner` already confirmed the requesting email owns the session. The `user_email` column in `physics_audits` is populated for administrative queries but is not the access-control key in the deletion path.

---

## 5. Gemini Multi-Modal Tool-Calling Architecture

### 5.1 Model Configuration

| Parameter | Value | Rationale |
|---|---|---|
| Model | `gemini-2.5-pro` | Highest reasoning capability for multi-step SCAL interpretation |
| API SDK | `google-genai ≥ 1.16.0` | Replaces deprecated `google-generativeai` |
| API Version | `v1beta` (SDK default) | Function calling (`tools` field) only available in v1beta |
| Tools schema type strings | Uppercase (`"OBJECT"`, `"STRING"`, `"ARRAY"`, `"NUMBER"`) | Pydantic `Schema.type` Literal enum rejects lowercase; lowercase causes silent null coercion |
| Temperature | Default (system-managed) | Deterministic physics tool dispatch; creative latitude only in prose interpretation |

### 5.2 High-Availability Key Pool

`PRCChatAssistant` maintains a pool of Gemini API keys to survive per-key rate limits and quota exhaustion:

```python
GEMINI_KEY_POOL = [key for env var GEMINI_API_KEY, GEMINI_API_KEY_2, ...]

def rotate_key(self, is_hard_fail: bool = False):
    _mark_key_failed(current_key, is_hard_fail)  # hard: 3600s cooldown; soft: 60s
    self._current_idx = (self._current_idx + 1) % len(self._keys)
    self._init_client()
```

Key failures are tracked in `_FAILED_KEYS` with a thread-safe lock. A 429 rate-limit triggers a 60-second soft cooldown; a 400/403 auth error triggers a 3600-second hard cooldown. The pool cycles through healthy keys on each rotate.

### 5.3 Tool Catalogue

Six tools are registered in `_HVIEL_TOOLS`:

| Tool Name | Trigger Condition | Physics Gate |
|---|---|---|
| `execute_python_simulation` | User requests Kr curves, Brooks-Corey simulation, or 1D displacement | `PhysicsValidator` (parameter gate) + `PhysicsGuard` (output audit) |
| `fit_petrophysical_curve` | User uploads lab data — Kr, MICP, Archie RI/FF, Pc, J-Function, Overburden | `PhysicsGuard` on fitted curve output |
| `agentic_history_matching` | Simulated Annealing optimisation on uploaded Kr lab data | `PhysicsGuard` on optimised parameters |
| `generate_mermaid_diagram` | User requests a workflow, flowchart, or process diagram | None (diagram generation) |
| `generate_executive_report` | User requests a `.docx` report or engineering deliverable | None (document generation) |
| `get_audit_history` | Proactive or on-request review of session physics quality history | None (read-only ledger query) |

### 5.4 Tool Dispatch Internals

```
Gemini returns tool call(s)
  ↓
_execute_tool(call)
  ├── "execute_python_simulation"
  │     PhysicsValidator.validate_core_physics(params)   ← raises if Swi+Sor>1 or bad phi
  │     simulation_core.run(model, params)
  │     PhysicsGuard().validate_kr(sw, krw, kro)
  │     _log_physics_audit(sid, "simulation_1d", audit_result)
  │     return _format_tool_response(name, args, json_result)
  │
  ├── "fit_petrophysical_curve"
  │     route by model: brooks_corey → validate_kr
  │                     micp        → validate_micp
  │                     ri / ff     → validate_archie
  │                     pc_*        → validate_pc
  │     _log_physics_audit(sid, model, audit_result, file_name)
  │     return formatted JSON (plot-ready for React components)
  │
  ├── "agentic_history_matching"
  │     prc_simulated_annealing.fit(sw, krw, kro)
  │     PhysicsGuard().validate_kr(sw_fitted, krw_fitted, kro_fitted)
  │     _log_physics_audit(sid, "history_matching", audit_result)
  │     return optimised Brooks-Corey parameters + convergence metadata
  │
  ├── "generate_executive_report"
  │     HvielDocEngine.generate(session_messages, well_name)
  │     returns {"download_url": "/api/report/download/{filename}"}
  │
  ├── "generate_mermaid_diagram"
  │     returns {"type": "mermaid", "code": "..."}
  │
  └── "get_audit_history"
      db("SELECT ... FROM physics_audits WHERE session_id=?")
      returns structured ledger JSON
```

### 5.5 SSE Streaming Architecture

The chat endpoint uses **Server-Sent Events (SSE)** with typed JSON frames. All frames follow the protocol:

```
data: {"type": "session", "session_id": "abc123"}

data: {"type": "token",   "text": "partial response chunk"}

data: {"type": "done"}

data: {"type": "error",   "msg": "upstream 503 — Gemini unavailable"}
```

Raw text frames are silently discarded by the frontend consumer. Only typed JSON frames are processed. This is an architectural constraint: any transport-layer migration (WebSocket, gRPC) must preserve the `{"type": "..."}` frame envelope.

**Async bridge:** The synchronous Gemini generator is bridged to the async FastAPI `StreamingResponse` via `asyncio.Queue`. A background thread runs `_generate()`, pushing token chunks into the queue. The async producer coroutine `_producer()` drains the queue and yields SSE-formatted strings.

### 5.6 Semantic Cache

Identical queries (same message, same knowledge base context, same recent history) are served from cache without hitting the Gemini API:

```python
cache_key = md5(message[:2000] + kb_context[:500] + history_last3_text)
```

Cache is per-process (in-memory `_CACHE: dict`). Cache miss invokes the full RAG + Gemini pipeline. Cache hit emits the stored response as a single SSE token + done event.

### 5.7 RAG Knowledge Base

| Parameter | Value |
|---|---|
| Embedding model | `text-embedding-004` (768 dimensions) |
| Chunk size | 600 words |
| Similarity metric | Cosine similarity |
| Similarity threshold | 0.35 (below this, chunk is excluded) |
| Top-k results | 15 |
| Source corpus | PRC technical library — API RP 40, SCAL standards, Burdine, Mualem, Brooks-Corey, LET, Amott/USBM, internal PRC field studies |

The knowledge hierarchy is enforced in the system prompt: RAG context (PRC library) takes priority over Gemini general knowledge. If the RAG context does not address the question, Hviel must state this explicitly before falling back to general engineering knowledge.

---

## 6. Database Schema and Row-Level Security

### 6.1 Complete Schema

```sql
-- Chat sessions
CREATE TABLE sessions (
    sid        TEXT PRIMARY KEY,
    title      TEXT    NOT NULL DEFAULT 'New Study',
    user_email TEXT,
    created_at REAL,
    updated_at REAL
);

-- Chat messages
CREATE TABLE m (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sid        TEXT,
    role       TEXT,        -- 'user' | 'model'
    text       TEXT,
    url        TEXT,        -- download URL for document responses
    ts         REAL,
    user_email TEXT,
    fname      TEXT         -- attached filename
);

-- Physics Audit Ledger (append-only)
CREATE TABLE physics_audits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    user_email   TEXT,
    timestamp    REAL,
    data_type    TEXT,
    health_score INTEGER,
    violations   TEXT,      -- JSON array
    file_name    TEXT
);

-- Knowledge Base embeddings
CREATE TABLE kb_vectors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source    TEXT,
    chunk_idx INTEGER,
    text      TEXT,
    embedding BLOB         -- raw float32 array
);

-- Analytics events
CREATE TABLE analytics_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    event_type TEXT,
    user_email TEXT,
    session_id TEXT,
    metadata   TEXT        -- JSON
);

-- Registered users
CREATE TABLE users (
    email      TEXT PRIMARY KEY,
    name       TEXT,
    created_at REAL
);

-- Feedback submissions
CREATE TABLE feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    user_email TEXT,
    message    TEXT,
    rating     INTEGER
);

-- Document generation jobs
CREATE TABLE report_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    user_email  TEXT,
    created_at  REAL,
    file_path   TEXT,
    status      TEXT
);

-- Admin action log
CREATE TABLE admin_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL,
    admin_ip   TEXT,
    action     TEXT,
    details    TEXT
);
```

### 6.2 Row-Level Security (RLS)

`_verify_session_owner(sid, email)` is called on every session read, write, and delete operation:

```python
def _verify_session_owner(sid: str, email: str):
    if not email:
        raise HTTPException(status_code=401, detail="Authentication required")
    row = db("SELECT user_email FROM sessions WHERE sid=?", (sid,))
    if row and row[0][0] and row[0][0].lower().strip() != email.lower().strip():
        raise HTTPException(status_code=403, detail="Unauthorized: You do not own this session.")
```

This enforces:
1. **Authentication gate:** No email → 401. Unauthenticated requests are rejected before touching the database.
2. **Ownership gate:** Email mismatch → 403 with a security warning log. Cross-user session access is blocked regardless of whether the `sid` is guessable.
3. **Null owner pass-through:** Sessions with `user_email = NULL` (e.g., pre-auth sessions) are accessible — this allows the legacy flow where a session exists before the user authenticates.

---

## 7. Security Architecture

### 7.1 SQL Injection Prevention

All `db()` call sites use parameterized queries with `?` placeholders. User data never touches the SQL skeleton string:

```python
# CORRECT — parameterized
db("SELECT * FROM sessions WHERE sid=? AND user_email=?", (sid, email))

# FORBIDDEN — interpolation (no instance of this pattern exists in production code)
db(f"SELECT * FROM sessions WHERE sid='{sid}'")
```

The `_translate_placeholders()` function converts `?` to `%s` for the psycopg2 PostgreSQL driver at execution time. This conversion operates on the static SQL template only — parameter values are passed separately and are never interpolated.

### 7.2 Path Traversal Guards (CWE-22)

Three independent guards protect against path traversal:

**Guard 1 — `/api/download/{filename:path}`**
```python
target = (_DOWNLOAD_ROOT / pathlib.Path(filename).name).resolve()
if not str(target).startswith(str(_DOWNLOAD_ROOT)):
    raise HTTPException(status_code=403)
```
Uses `.name` to strip all directory components — only bare filenames in the CWD are served.

**Guard 2 — `/api/report/download/{filename:path}`**
Same pattern as Guard 1 with a separate root directory for report outputs.

**Guard 3 — `/{full_path:path}` SPA catch-all**
```python
_DIST_DIR_PATH = pathlib.Path(_DIST_DIR).resolve()  # resolved once at startup
candidate = (_DIST_DIR_PATH / full_path).resolve()
if not str(candidate).startswith(str(_DIST_DIR_PATH)):
    raise HTTPException(status_code=403)
```
Uses full containment validation (not `.name` stripping) because the SPA must serve nested asset paths (`assets/js/app.js`). Containment is checked against the resolved `_DIST_DIR_PATH` resolved once at application startup.

### 7.3 Admin Token System

Admin access uses backend-issued 128-bit hex tokens with a 15-minute TTL:

```python
_ADMIN_TOKEN_TTL = 900  # seconds
token = secrets.token_hex(16)  # 128-bit random token
_ADMIN_TOKENS[token] = time.time() + _ADMIN_TOKEN_TTL
```

The admin PIN never leaves the server-side environment variable (`ADMIN_PIN`). The frontend receives only the token, not the PIN. Expired tokens are rejected by `_require_admin_token()` without database lookup.

### 7.4 Rate Limiting

SlowAPI provides IP-keyed rate limiting on sensitive endpoints. If `slowapi` is not installed, the limiter degrades gracefully (no crash — rate limiting is bypassed). Production deployments must have `slowapi` installed.

### 7.5 Secrets Management (OPEN — Action Required)

Per CLAUDE.md §4 (LEST-WE-FORGET security audit log):

- `.env` contains live `GEMINI_API_KEY` values and the Neon PostgreSQL connection string
- `.env.local` contains a Vercel OIDC JWT

**Required actions (pending manual completion by developer):**
1. Rotate all `GEMINI_API_KEY` values in Google AI Studio
2. Rotate the Neon PostgreSQL password via the Neon console
3. Revoke the Vercel OIDC token in `.env.local`
4. If the repository was ever public: run `git filter-repo` or BFG Repo-Cleaner to purge historical `.env` commits, then force-push

---

## 8. Deployment and Operational Checklist

### 8.1 Pre-Deployment Checklist (Run Before Every Push to `master`)

```
[ ] python physics_validator.py                       — physics gate passes
[ ] pytest tests/ -v                                   — 82/82 unit tests green
[ ] cd frontend && npx playwright test                 — 19/19 E2E tests green
[ ] git status                                         — no .env, *.db, __pycache__ staged
[ ] cd frontend && npm run build                       — frontend/dist/ current
[ ] GET /api/diag                                      — correct version string post-deploy
[ ] POST /api/chat?message="Run a Brooks-Corey simulation swr=0.2 snr=0.15"
    Expected: status=success, reply contains __PRC_PLOT__ and curves JSON
[ ] GET /api/kb/status                                 — chunk count ≥ 100
[ ] No new db() call sites use string interpolation
[ ] New download paths (if any) use path traversal guard pattern
```

### 8.2 Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Primary Gemini API key |
| `GEMINI_API_KEY_2`, `_3`, ... | No | Additional pool keys for HA |
| `DATABASE_URL` | No | PostgreSQL connection string (omit for SQLite) |
| `ADMIN_PIN` | No | Admin access PIN (default: `1509`) |
| `KB_INGEST_SECRET` | Yes (for KB ingest) | Password protecting `/api/kb/ingest` |
| `VITE_API_URL` | Frontend | Backend base URL (empty string = same origin) |

### 8.3 Knowledge Base Health Monitor

```bash
GET /api/kb/status
```

If `chunk_count < 100`, the knowledge base is degraded. Hviel's petrophysical definitions, model equations, and laboratory procedure citations will fall back to general LLM knowledge rather than PRC-certified sources. Raise an alert before the next user session.

### 8.4 Gemini Model Upgrade Path

When upgrading `google-genai`, re-run the chat smoke test before pushing:

```
POST /api/chat  message="Run a Brooks-Corey simulation swr=0.2 snr=0.15 krw_max=0.65 kro_max=0.90"
Expected: STATUS=success, reply contains __PRC_PLOT__ and curves JSON
```

Verify that tool schema type strings remain uppercase (`"OBJECT"`, `"STRING"`, `"ARRAY"`, `"NUMBER"`). The Pydantic `Schema.type` Literal enum will silently coerce lowercase values to null, producing malformed wire JSON without a visible error.

### 8.5 Database Migration (SQLite → PostgreSQL)

The `_translate_placeholders()` function handles `?` → `%s` conversion automatically. The only outstanding migration item is the schema DDL — the `CREATE TABLE IF NOT EXISTS` statements in `app.py` must be run against the PostgreSQL instance once. The application then selects the correct driver at startup based on the presence of `DATABASE_URL`.

---

*Sovereign SCAL AI — Engineering Operator's Manual v2.0*  
*PRC Petroleum Research Center — Tripoli, Libya*  
*Document prepared by the PRC AI Systems Engineering Division*
