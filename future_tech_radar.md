# PRC Technology Radar — Next-Horizon Architecture
**Status:** Internal Architecture Review  
**Date:** May 2026  
**Scope:** Technologies under active evaluation for the PRC SCAL AI Pipeline v2 roadmap

---

## Tier 1 — Adopt (Production-Ready, High Confidence)

### Rust (Systems Layer)
- **Why:** Zero-cost abstractions, memory safety without GC, sub-millisecond latency for numerical kernels. Ideal for the physics simulation core currently running as Python subprocesses via `SkillsEngine`.
- **Target module:** `simulation_core`, `curve_fitting_skill`, `history_matching_skill` — rewrite as a compiled Rust library exposed via PyO3 FFI or as a native WebSocket server.
- **Benchmark rationale:** Brooks-Corey Simulated Annealing (currently ~2–4s in Python) → projected <50ms in Rust.

### WebSockets (Real-Time Data Layer)
- **Why:** Current SSE is unidirectional — client cannot push mid-stream corrections or abort requests. WebSockets enable full-duplex lab-data ingestion streams.
- **Target module:** Replace `GET /api/chat/stream` SSE with `ws://` for interactive sessions. Retain SSE for passive consumers (dashboard monitoring).
- **Protocol:** JSON-framed messages, typed events (`{type, payload}`), binary frames for raw lab sensor data.

### PostgreSQL (Primary DB at Scale)
- **Why:** Already supported in `app.py` via connection pool. SQLite WAL is hitting limits at >50 concurrent users. PG's `RETURNING id`, advisory locks, and `pg_notify` are needed for the audit ledger's real-time push.
- **Migration:** The `_translate_placeholders()` function in `app.py` already handles `?` → `%s`. Schema migration scripts are the only outstanding item.

---

## Tier 2 — Trial (Promising, Needs Validation)

### Tokio + Axum (Rust Async Web Framework)
- **Why:** If the physics simulation layer moves to Rust, co-locating the WebSocket ingestion server in the same process eliminates IPC overhead. Axum's extractors are ergonomically similar to FastAPI.
- **Risk:** Team Rust proficiency. Recommend a 4-week spike with a single endpoint before broader adoption.

### Apache Arrow + Polars (In-Memory Analytics)
- **Why:** Lab data files (Excel, CSV) are currently parsed row-by-row in Python. Arrow columnar format enables zero-copy SIMD operations. Polars is 10–50× faster than pandas for the typical SCAL dataset sizes (500–50,000 rows).
- **Target module:** `SCALFileHandler` ingestion path.

### ClickHouse (Analytics OLAP)
- **Why:** `analytics_events` and `physics_audits` tables are append-only, write-heavy, and read in bulk for admin dashboards. ClickHouse's columnar OLAP storage is optimal for time-series event aggregation.
- **Risk:** Operational overhead of a second database. Only justified when `analytics_events` exceeds 10M rows.

### wasm-bindgen (Frontend Physics Preview)
- **Why:** Compile the Rust physics core to WebAssembly for instant client-side curve preview before server round-trip. Engineer sees tentative Brooks-Corey curve update on every slider change.
- **Risk:** WASM bundle size, browser memory limits for large datasets.

---

## Tier 3 — Assess (Watch, Not Yet Actionable)

### Qdrant (Dedicated Vector DB)
- **Why:** The current RAG system stores embeddings as raw BLOB in SQLite/PG and does linear cosine scan. At >10,000 chunks, this becomes the bottleneck. Qdrant provides HNSW approximate nearest-neighbor search with sub-millisecond query at 1M+ vectors.
- **Threshold for adoption:** When `kb_vectors` exceeds 5,000 rows.

### gRPC (Service Mesh)
- **Why:** If `SkillsEngine` skills are extracted into microservices (separate deployment units per skill category), gRPC with protobuf provides strongly-typed, high-throughput inter-service communication.
- **Current state:** Premature. All skills run in-process or as subprocesses on the same machine.

### Temporal.io (Workflow Orchestration)
- **Why:** Long-running SCAL workflows (ingest → validate → fit → report) are currently handled by a single HTTP request with a 280-second timeout. Temporal enables durable, retryable, observable workflows that survive server restarts.
- **Threshold:** Required when workflows exceed 5 minutes or span multiple services.

---

## Key Architectural Constraints (Non-Negotiable)

1. **Physics Integrity Gate must survive any re-architecture.** `PhysicsGuard` validation runs on every data path. No bypass, regardless of transport layer.
2. **The Audit Ledger is append-only.** Any new transport (WebSocket, gRPC) must still write to `physics_audits` before returning results.
3. **All SSE events remain typed JSON.** The frontend SSE consumer discards raw text frames. This protocol constraint applies to WebSocket frames as well.
4. **PRC phase color scheme is fixed.** `#38bdf8` (water), `#fb923c` (oil), `#10b981` (gas). No UI framework migration changes these.
