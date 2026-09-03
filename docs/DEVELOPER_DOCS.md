# PRC SCAL AI Pipeline — Developer Reference
**Version:** PRC-HUB-VER-14-PROD-READY  
**Stack:** FastAPI · Gemini 2.5-flash (google-genai ≥ 1.16.0) · SQLite/PostgreSQL · React/Vite · Tailwind v4

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Environment Variables](#2-environment-variables)
3. [Database Schema](#3-database-schema)
4. [API Endpoints](#4-api-endpoints)
5. [Security Implementation](#5-security-implementation)
6. [PhysicsGuard — Validation Engine](#6-physicsguard--validation-engine)
7. [PRCChatAssistant — AI Layer](#7-prcchatassistant--ai-layer)
8. [KnowledgeBase — RAG System](#8-knowledgebase--rag-system)
9. [SkillsEngine — Tool Execution](#9-skillsengine--tool-execution)
10. [SSE Protocol](#10-sse-protocol)
11. [Document Generation Pipeline](#11-document-generation-pipeline)
12. [Key Rotation & HA](#12-key-rotation--ha)

---

## 1. Architecture Overview

```
Browser (React/Vite)
    │
    ├─ GET  /api/chat/stream   → SSE (plain text queries, no files)
    └─ POST /api/chat          → JSON (file uploads, doc generation, retries)
              │
         FastAPI (app.py)
              │
    ┌─────────┴──────────┐
    │                    │
  db()              PRCChatAssistant
  SQLite/PG         │
                    ├─ KnowledgeBase.search_async()  [RAG]
                    ├─ gemini-2.5-flash              [LLM]
                    │    └─ Tool calls → _execute_tool()
                    │         ├─ SkillsEngine.run_skill()
                    │         │    ├─ simulation_core.py
                    │         │    ├─ curve_fitting_skill.py
                    │         │    └─ history_matching_skill.py
                    │         ├─ PhysicsGuard         [validation]
                    │         ├─ PRCReportEngine       [docx reports]
                    │         └─ HvielDocEngine        [xlsx/pptx/pdf]
                    └─ physics_audits table          [immutable ledger]
```

**Request routing** (frontend `isDocumentRequest` regex):
- SSE path: plain text, no files, no doc-generation keyword
- POST path: file attachments, retries, and `/\b(generate|create|export)\b.{0,50}\b(report|document|...)\b/i`

---

## 2. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Primary Gemini key. Comma-separated for pool. |
| `GEMINI_API_KEY_2`, `_3`, … | No | — | Additional pool keys (any `GEMINI_API_KEY*` prefix). |
| `DATABASE_URL` | No | SQLite | Full PostgreSQL DSN (psycopg2). Falls back to `chat_history.db`. |
| `ADMIN_PIN` | No | `1509` | 4-digit PIN for admin vault access. |
| `KB_INGEST_SECRET` | No | `""` | Password guard on `POST /api/kb/ingest`. |
| `VITE_API_URL` | No | `""` | Frontend: overrides API base URL. |

**Key pool behavior:** All env vars matching `GEMINI_API_KEY*` are collected, deduplicated, and round-robined. Quota errors trigger automatic rotation with a 60-second cooldown; auth errors trigger a 1-hour hard ban on that key.

---

## 3. Database Schema

### `m` — Message Log
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `sid` | TEXT | Session UUID |
| `role` | TEXT | `user` or `model` |
| `text` | TEXT | Message content |
| `url` | TEXT | Download URL for reports |
| `ts` | REAL | Unix epoch |
| `user_email` | TEXT | Lowercase email |
| `fname` | TEXT | Original filename (file uploads) |

### `sessions` — Session Registry
| Column | Type | Notes |
|---|---|---|
| `sid` | TEXT PK | Session UUID |
| `title` | TEXT | Editable study title (default: `New Study`) |
| `user_email` | TEXT | Owner email |
| `created_at` | REAL | Unix epoch |
| `updated_at` | REAL | Unix epoch, updated on every message |

### `kb` — Knowledge Base Chunks
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `source` | TEXT | Document filename |
| `chunk` | TEXT | 600-word text chunk |

### `kb_vectors` — Embedding Index
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `chunk_id` | INTEGER UNIQUE | FK → `kb.id` |
| `embedding` | BLOB/BYTEA | float32 array, `text-embedding-004` |

### `users` — Registered Engineers
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `email` | TEXT UNIQUE | Lowercase |
| `name` | TEXT | Full name |
| `created_at` | REAL | First login epoch |

### `feedback` — Bug Reports
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `user_email` | TEXT | Reporter |
| `bug_report` | TEXT | Free-text report |
| `ts` | REAL | Unix epoch |

### `analytics_events` — Event Log
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `user_email` | TEXT | Actor |
| `event_type` | TEXT | `login`, `chat`, `feedback`, `register`, `page_view` |
| `event_data` | TEXT | JSON payload |
| `ts` | REAL | Unix epoch |

### `physics_audits` — The Auditor's Ledger (append-only)
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `session_id` | TEXT | FK → sessions.sid |
| `user_email` | TEXT | Engineer email |
| `timestamp` | REAL | Unix epoch |
| `data_type` | TEXT | `micp`, `kr`, `ri`, `ff`, `overburden`, etc. |
| `health_score` | INTEGER | 0–100 |
| `violations` | TEXT | JSON array of `{rule, severity, detail}` |
| `file_name` | TEXT | Source lab file |

**This table is append-only. There are no `UPDATE` or `DELETE` paths for audit records.**

### `response_cache` — Semantic Cache
| Column | Type | Notes |
|---|---|---|
| `id` | PK | Auto-increment |
| `query_hash` | TEXT UNIQUE | MD5 of `(message + kb_context + history_text)` |
| `response` | TEXT | Cached Gemini reply |
| `created_at` | REAL | Unix epoch |

**Cache hit condition:** identical query hash. Cache is populated only on non-tool-call responses (pure text). TTL is not enforced server-side; add a cron job if stale cache is a concern.

---

## 4. API Endpoints

### Public

#### `GET /health`
Liveness probe.  
**Response:** `{"status": "ok", "db": "postgres" | "sqlite"}`

#### `GET /api/diag`
Diagnostic snapshot for deployments.  
**Response:** `{"version", "node_pool_size", "active_node_idx", "nodes_in_cooldown"}`

#### `POST /api/auth`
User login — validates PIN against `ADMIN_PIN`.  
**Body:** `pin=<string>` (form)  
**Response:** `{"status": "success"}` or 401  
**Rate-limited** if `slowapi` installed.

#### `POST /api/register`
Upsert user record (fire-and-forget from frontend after successful auth).  
**Body:** `email=<string>`, `name=<string>` (form)  
**Response:** `{"status": "ok"}`

### Sessions (require `email` param for ownership verification)

#### `GET /api/sessions?email=<email>`
Returns sessions owned by the given email, ordered newest-first.  
**Response:** `[{"id", "title", "ts"}, ...]`

#### `GET /api/session/{sid}?email=<email>`
Returns full message history for a session. Enforces row-level ownership.  
**Response:** `{"status": "ok", "title", "messages": [{"role", "text", "download_url", "ts", "fileName"}, ...]}`

#### `POST /api/session/{sid}/title`
Renames a session title. Enforces row-level ownership.  
**Body:** `email=<string>`, `title=<string>` (form)  
**Response:** `{"status": "ok"}`

#### `DELETE /api/session/{sid}?email=<email>`
Deletes session, all messages, and associated physics audits for that session. Enforces ownership.  
**Response:** `{"status": "ok"}`

### Chat

#### `GET /api/chat/stream`
**Server-Sent Events** stream for text-only messages.  
**Query params:** `message`, `session_id`, `user_email`, `engineer_name`  
**Event types:**

| `type` | Fields | Notes |
|---|---|---|
| `session` | `session_id` | Sent first; client must store the session ID |
| `token` | `text` | Partial response chunk |
| `done` | — | Stream complete |
| `error` | `msg` | Error occurred; stream will close |

**Flow:** RAG search → persist user message → upsert session → fetch history → Gemini stream → persist model reply → fire background KB ingest tasks.

#### `POST /api/chat`
Handles file uploads, document generation requests, and retries.  
**Body:** `message`, `session_id`, `user_email`, `engineer_name`, `files[]` (multipart)  
**Response (success):** `{"status": "success", "session_id", "reply", "is_report_ready": bool, "download_url": str|null, "doc_type": str}`  
**Response (error):** `{"status": "error", "session_id", "reply"}`  

**Document generation path:** triggered when `HvielDocEngine._detect_type(message)` returns a non-null file type. Bypasses Gemini tools; calls `generate_document_json()` directly, then `HvielDocEngine.build_from_json()`.

### Downloads

#### `GET /api/download/{filename}`
Serves generated documents (docx/xlsx/pptx/pdf) from CWD.  
**Security:** `_pathlib.Path(filename).name` strips directory components; `startswith(_DOWNLOAD_ROOT)` enforces containment (CWE-22 guard).

#### `POST /api/report/generate`
Triggers on-demand executive SCAL report generation.  
**Body:** `session_id`, `well_name` (form)  
**Response:** `{"status": "success", "download_url": "/api/report/download/<filename>"}`

#### `GET /api/report/download/{filename}`
Serves reports from the `reports/` subdirectory with its own containment guard.

### Knowledge Base

#### `POST /api/kb/ingest`
Ingest a document into the RAG knowledge base.  
**Body:** `file=<pdf|txt|docx|html>`, `password=<KB_INGEST_SECRET>` (multipart)  
**Response:** `{"status": "success", "book", "chunks_stored", "words"}` or error  
**Authorization:** `password` field must match `KB_INGEST_SECRET` env var.

#### `GET /api/kb/status`
Returns list of ingested knowledge base documents and chunk counts.  
**Response:** `{"books": [{"name", "chunks"}, ...], "total_chunks"}`

### Admin (require `Authorization: Bearer <token>`)

Admin tokens are obtained via `POST /api/admin/auth`. TTL is 15 minutes.

#### `POST /api/admin/auth`
**Body:** `pin=<ADMIN_PIN>` (form)  
**Response:** `{"token": "<hex32>"}` or 401  
Brute-force throttle: 1-second sleep on failure.

#### `GET /api/admin/summary`
Platform statistics: user count, session count, message count, KB chunks, feedback count, storage type.

#### `GET /api/admin/analytics`
Last 200 analytics events with email, type, data, timestamp.

#### `GET /api/admin/feedback`
Last 100 bug reports.

#### `GET /api/admin/users`
All registered engineers ordered by registration date.

### Analytics / Feedback (public write-only)

#### `POST /api/feedback`
**Body:** `user_email`, `bug_report` (form)

#### `POST /api/analytics/event`
**Body:** `user_email`, `event_type`, `event_data` (form)

### Skills

#### `GET /api/skills/list`
Returns available Hermes skill categories and names from `hermes_skills_library/`.  
**Response:** `{"skills": [{"category", "name", "desc"}, ...]}`

---

## 5. Security Implementation

### Row-Level Security — `_verify_session_owner(sid, email)`
Called on every session read/write/delete. Compares the `sessions.user_email` field against the requesting `email` parameter. Unauthenticated requests (no email) raise HTTP 401. Cross-user access attempts raise HTTP 403 and emit a `[SECURITY]` warning log.

### Admin Token Management
```python
_ADMIN_TOKENS: dict[str, float]  # token → expiry_epoch
_ADMIN_TOKEN_TTL = 900           # 15 minutes
```
Tokens are 128-bit hex strings (`secrets.token_hex(16)`). `verify_admin()` is a FastAPI `Depends` guard; it purges expired tokens on each check.

### Path Traversal Guards (CWE-22)
Two independent guards, both resolved at startup:

```python
# /api/download/{filename} — strips directory, then containment check
target = (_DOWNLOAD_ROOT / _pathlib.Path(filename).name).resolve()
if not str(target).startswith(str(_DOWNLOAD_ROOT)):
    raise HTTPException(403)

# /api/report/download/{filename} — reports/ subdirectory guard
target = (reports_root / _pathlib.Path(filename).name).resolve()
if not str(target).startswith(str(reports_root.resolve())):
    raise HTTPException(403)

# SPA catch-all /{full_path:path} — allows nested sub-paths
candidate = (_DIST_DIR_PATH / full_path).resolve()
if not str(candidate).startswith(str(_DIST_DIR_PATH)):
    raise HTTPException(403)
```

### SQL Injection Prevention
All `db()` call sites use parameterized queries with `?` placeholders. `_translate_placeholders()` converts `?` → `%s` for psycopg2 at query-time, never at interpolation time. User data never touches the SQL skeleton string.

### Rate Limiting
If `slowapi` is installed, the `Limiter` is wired to `get_remote_address`. Endpoint decorators apply `@_limiter.limit(...)`. Without the dependency, the app runs without limiting (useful in dev).

### Secrets
- No API keys in source. All keys read from environment.
- `.env` is `.gitignore`-d. See `CLAUDE.md §4` for key rotation instructions.
- `ADMIN_PIN` defaults to `1509` if not set — **always override in production**.

---

## 6. PhysicsGuard — Validation Engine

`PhysicsGuard` is a stateful, chainable validator. One instance per dataset. Call one or more `validate_*` methods, then call `generate_health_score()`.

### Scoring
```
HIGH violation   → −15 pts
MEDIUM violation → −5 pts
Score = max(0, 100 − total_deduction)

Grade A: score ≥ 95
Grade B: score ≥ 80
Grade C: score ≥ 60
Grade F: score < 60
```

### `validate_kr(sw, krw, kro)` — 7 rules
| Rule ID | Severity | Condition |
|---|---|---|
| `KRW_MONOTONICITY` | HIGH | Krw must be non-decreasing in Sw |
| `KRO_MONOTONICITY` | HIGH | Kro must be non-increasing in Sw |
| `KRW_RANGE` | HIGH | All Krw values ∈ [0, 1] |
| `KRO_RANGE` | HIGH | All Kro values ∈ [0, 1] |
| `KRW_ENDPOINT` | HIGH | Krw at max Sw ≤ 1.0 |
| `KRW_ZERO_AT_SWI` | MEDIUM | Krw(Swi) ≤ 0.01 |
| `KRO_ZERO_AT_SOR` | MEDIUM | Kro(1−Sor) ≤ 0.01 |

### `validate_micp(pc, hg_sat)` — 4 rules
| Rule ID | Severity | Condition |
|---|---|---|
| `MICP_NEGATIVE_PC` | HIGH | All Pc > 0 |
| `MICP_ENTRY_PRESSURE` | HIGH | Entry Pc (at Hg_sat > 1%) > 0 |
| `MICP_SATURATION_MONOTONICITY` | HIGH | Hg_sat non-decreasing with Pc |
| `MICP_SAT_RANGE` | MEDIUM | All Hg_sat ∈ [0, 1] |

### `validate_archie(x, y, model_type)` — 2–3 rules
- `model_type="RI"`: `RI_MONOTONICITY`, `RI_RANGE` (RI ≥ 1), `RI_ENDPOINT` (MEDIUM)
- `model_type="FF"`: `FF_MONOTONICITY`, `FF_RANGE` (FF ≥ 1)

### `validate_pc(sw, pc)` — 2 rules
| Rule ID | Condition |
|---|---|
| `PC_MONOTONICITY` | Pc non-increasing as Sw increases |
| `PC_RANGE` | All Pc ≥ −0.1 |

### Audit Logging
Every tool path that invokes `PhysicsGuard` **must** call `_log_physics_audit()` before returning. Failure to log is a critical safety violation. The ledger is append-only; there is no delete path.

### `PhysicsValidator` (legacy)
`validate_core_physics(data)` enforces:
- `Swi + Sor ≤ 1.0` — raises `PhysicsEngineError` if violated
- `0 < Porosity < 1` — raises `PhysicsEngineError` if violated
- Rounds all floats to 4 decimal places via `format_precision()`

---

## 7. PRCChatAssistant — AI Layer

### Model
```python
model_name = "gemini-2.5-flash"   # see CLAUDE.md §5 for upgrade notes
api_version = "v1beta"            # function calling requires v1beta
```

### Tool Loop (non-streaming path)
```
while True:
    resp = model.generate(contents, config=cfg_with_tools)
    for part in resp.parts:
        if part.function_call:
            raw = _execute_tool(part.function_call)
            fmt = _format_tool_response(name, args, raw)
            final += fmt
            append FunctionResponse to contents
        elif part.text:
            final += part.text
    if no tool calls this turn:
        cache result; break
```

**Max iterations:** 5 (hard cap on tool-call loop to prevent runaway billing).

### `_execute_tool(call)` — Tool Dispatch
| Tool | Handler |
|---|---|
| `execute_python_simulation` | `SkillsEngine.run_skill("petroleum", "simulator", "simulation_core.py", [json])` |
| `generate_mermaid_diagram` | Wraps content in `__MERMAID_START__` / `__MERMAID_END__` |
| `fit_petrophysical_curve` | For `micp/ri/ff/jfunction/pc_centrifuge/overburden`: returns `{"status":"ready"}` (computation in `_format_tool_response`). For `brooks_corey/let`: delegates to `curve_fitting_skill.py`. |
| `agentic_history_matching` | `SkillsEngine.run_skill("petroleum", "simulator", "history_matching_skill.py", [json])` |
| `generate_executive_report` | `PRCReportEngine().generate(session_id, well_name)` → `REPORT_READY:<filename>` |
| `get_audit_history` | Reads from `physics_audits` table for current session |

### Semantic Cache
Hash: `MD5(message_lower[:2000] + kb_context[:500] + history_last3_text)`  
Cache miss → full Gemini call → insert to `response_cache`.  
Cache hit → return immediately, skip Gemini entirely.

---

## 8. KnowledgeBase — RAG System

### Embedding
Model: `models/text-embedding-004` (768-dimensional float32)  
Chunk size: 600 words  
Similarity threshold: 0.35 cosine score

### Search Strategy
1. **Vector search** (if `kb_vectors` has < 2000 rows): cosine similarity over all embeddings, top-k=15, filtered at 0.35 threshold.
2. **Keyword fallback** (always runs if vector search returns nothing): tokenizes query into 3+ character words, LIKE queries against `kb.chunk`.

### `ingest_transactional(name, chunks)`
Pre-computes all embeddings **before** acquiring the DB lock. This prevents timeout under concurrent load on long documents. Uses a transactional upsert: deletes existing chunks for the same source, then inserts all new chunks + vectors atomically.

### Async Wrapper
`search_async()` delegates to `run_in_executor` so the FastAPI event loop is never blocked by CPU-bound cosine operations.

---

## 9. SkillsEngine — Tool Execution

```python
SkillsEngine.run_skill(category, skill_name, script_name, args=[])
```

**Resolution order:**
1. `hermes_skills_library/<category>/<skill_name>/scripts/<script_name>`
2. `hermes_skills_library/<category>/<skill_name>/<script_name>`
3. Returns `{"error": "Skill script not found: <path>"}` if neither exists.

**Safety timeout:** 30 seconds. Returns `{"error": "Skill execution timed out"}` on expiry.

**Output:** `{"stdout", "stderr", "exit_code"}` — callers read `stdout` for result JSON.

---

## 10. SSE Protocol

The frontend SSE consumer in `App.jsx` parses **all** SSE data frames as JSON. Raw text frames are silently discarded. Every frame must conform to:

```json
{"type": "<event_type>", ...payload}
```

| `type` | Payload keys | Frontend action |
|---|---|---|
| `session` | `session_id` | Store in state and localStorage |
| `token` | `text` | Append to streaming message bubble |
| `done` | — | Close EventSource, stop loading |
| `error` | `msg` | Show error bubble, set server offline |

**[DONE] sentinel** (legacy): The frontend also handles the plain string `[DONE]` for backward compatibility with the previous server version.

---

## 11. Document Generation Pipeline

```
POST /api/chat  (message matches _detect_type regex)
      │
HvielDocEngine._detect_type(message)
      │  Returns: "docx" | "xlsx" | "pptx" | "pdf" | None
      │
PRCChatAssistant.generate_document_json(file_type, message, history, kb_ctx, engineer)
      │  System prompt: enforce JSON-only output with strict schema
      │  Returns: raw JSON string (may have ```json fences, stripped by build_from_json)
      │
HvielDocEngine.build_from_json(raw_json, file_type, engineer=engineer)
      │  Returns: absolute filepath to generated file
      │
FileResponse via GET /api/download/{filename}
```

**Document types and their JSON schemas:**
- `docx`: `{title, subtitle, author, date, sections[{heading, level, paragraphs, bullets}], tables}`
- `xlsx`: `{title, sheets[{name, headers, rows, column_widths}]}`
- `pptx`: `{title, subtitle, slides[{title, content, bullets}]}`
- `pdf`: `{title, author, sections, tables}`

---

## 12. Key Rotation & HA

```python
GEMINI_KEY_POOL = [key1, key2, ...]   # Deduplicated list from env

# On quota/auth error:
assistant.rotate_key(is_hard_fail=False)  # 60-second cooldown
assistant.rotate_key(is_hard_fail=True)   # 3600-second cooldown (auth error)

# Key health check before use:
_key_healthy(key)  # returns True if cooldown has expired
```

On every `rotate_key()` call, `_init_client()` selects the next healthy key and re-initializes the Gemini client. Thread safety is enforced via `_idx_lock` (key selection) and `_client_lock` (client swap).

---

## Appendix: Frontend Plot Protocol

The AI model communicates chart data to the React frontend via inline `__PRC_PLOT__` blocks in the response text. `MessageRenderer.jsx` parses these blocks and renders them via `KrCurvePlot.jsx` (Recharts). All charts set `isAnimationActive={false}` — data does not animate. The only animations allowed are `streaming-cursor` and status pulse indicators.

```
__PRC_PLOT__
{"title":"...","xAxis":{"label":"..."},"yAxis":{"label":"..."},"curves":[...]}

__MERMAID_START__
graph TD
    ...
__MERMAID_END__

__PRC_DASHBOARD__
<canvas ...></canvas><script>...</script>
__PRC_DASHBOARD__
```

PRC phase colors: Water = `#38bdf8`, Oil = `#fb923c`, Gas = `#10b981`
