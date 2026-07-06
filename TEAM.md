# TEAM.md — Multi-Agent Collaboration Protocol

Two AI agents build this repo together. They **cannot talk in real time**, so they
coordinate through this file, git, and the human.

| Agent | Strengths / role |
|---|---|
| **Antigravity (Gemini)** | Feature building, the AI/chat pipeline, rapid implementation |
| **Claude Code (Claude)** | Review, testing, debugging, security, deploy hygiene, verification |

## How we communicate
1. **Git is the source of truth.** Commit your work before handing off.
2. **The Handoff Log below is our async message board.** Read the latest entry
   before you start; append a new entry when you finish.
3. **The human is the live bridge** — they can copy a message from one agent's
   window into the other's when something needs a real-time relay.

## Rules both agents follow
1. **Commit before handoff.** Never leave large uncommitted changes for the other
   agent to step on. (Lesson learned: 687 uncommitted lines in `app.py` once made
   review slow and risky.)
2. **One agent per file at a time.** Don't both edit `app.py` simultaneously.
3. **Read before you write.** On start, run `git log --oneline -5`, `git status`,
   and read the newest Handoff Log entry.
4. **Run the gate before declaring "done":** `python -m pytest tests/` must pass.
5. **Respect the "Do Not Break" invariants below.**

## Do Not Break (hard invariants — breaking these crashes CI or the deploy)
- **genkit is pinned:** `genkit==0.4.0` + `genkit-plugin-google-genai==0.4.0`.
  genkit ≥ 0.5 removed the `genkit.ai` module → `ModuleNotFoundError` on any clean
  install (CI + Render). Do **not** unpin or bump without re-verifying imports.
- **Frontend liveness check uses `/health`** (public), never `/api/diag` (auth-gated,
  returns 401 before login → false "Offline" badge).
- **File ops use `pathlib.Path`**, never the `os` module, in `app.py`,
  `scal_file_handler.py`, `file_reader.py`.
- **Rebuild `frontend/dist`** after any JSX/CSS change (`cd frontend && npm run build`)
  — Render serves the committed dist; there is no frontend build step on deploy.
- **Physics gate must pass** (PhysicsGuard) — see CLAUDE.md §1 / AGENTS.md.

## Handoff Log (newest first — APPEND, never delete)

### [2026-07-06] Claude Code — Pruned dead _TEST_TYPE_RULES from file_reader.py (commit 177bedb)

**Did:** removed the unused first-match rule list flagged in the entry below;
replaced with a pointer comment to the shared SCALFileHandler.KEYWORDS
classifier. **Verified:** full suite -> 320 passed.

### [2026-07-06] Claude Code — Classifier alignment: file_reader delegates to SCALFileHandler (commit b94af4c)

**Did:**
- `file_reader._detect_test_type` no longer uses its own first-match
  `_TEST_TYPE_RULES` scan; it now scores with `SCALFileHandler.KEYWORDS` using
  the exact `identify()` rules (word-boundary for <=4-char keywords, 10x/5x
  weights, max-score winner) and maps handler keys to file_reader keys
  (MICP/REL_PERM/IMBIBITION/KW_THROUGHPUT/overburden_compaction, else UNKNOWN).
  Import is function-local (circular-import guard).
- `_TEST_TYPE_RULES` in file_reader.py is now unused by the classifier — kept
  in place this round; safe to prune in a later cleanup.
- New `tests/test_classifier_alignment.py`: per-type snippet assertions + both
  UNKNOWN fallbacks (no vocabulary; unmapped handler type NMR).
- Note: pending uncommitted `scal_file_handler.py` changes (NVIDIA session) do
  not touch KEYWORDS/identify, so committed-tree behavior matches the verified
  worktree. NVIDIA migration work remains uncommitted, as found.

**Verified:** `py -3.13 -m pytest tests/test_classifier_alignment.py` -> 1 passed;
full suite -> 320 passed.

### [2026-07-06] Claude Code — Geological graph seeding + hybrid_geological_search tool (commit 96b935b)

**Did:**
- `geological_graph.py`: `GeologicalGraph.__init__` gained `seed: bool = True`;
  new `_seed_default_relations()` populates an empty store with the default Libyan
  slice (Sirte/Murzuq formations, lithologies, fluids, 4 PENETRATES wells with
  porosity/permeability metadata). Idempotent — any existing node skips seeding.
- `app.py`: `hybrid_geological_search` registered end-to-end — `_HVIEL_TOOLS`
  schema, `HybridGeologicalSearchInput` + `@ai.tool` stub, `_execute_tool` branch
  (graph on `settings.graph_db_path` + `RAGDatabase` analog retriever via
  `graph.hybrid_search`), `_format_tool_response` Markdown renderer.
- **Gotcha for future agents:** `RAGDatabase()` against the legacy repo-root
  `./chroma_db` store makes chromadb's Rust bindings raise `pyo3 PanicException`
  (a `BaseException` — `except Exception` does NOT catch it). The tool branch
  catches `BaseException` (re-raising KeyboardInterrupt/SystemExit) and degrades
  to graph-only. Consider migrating/rebuilding that store.
- `tests/test_geological_graph.py` fixture now uses `seed=False`; new
  `tests/test_geological_graph_tool.py` exercises the tool path hermetically
  (tmp `GRAPH_DB_PATH`, tmp `CHROMA_DIR`, offline fake embedder, pre-ingested analog).

**Verified:** graph + tool tests -> 15 passed; full suite -> 319 passed; suite
against exact commit content (pending NVIDIA work stashed) -> 296 passed.
NVIDIA migration work remains uncommitted, as found (see 2026-07-05 entry below).

### [2026-07-06] Claude Code — Sandbox fitting tools wired to PhysicsSandbox (commit 719137e)

**Did:**
- Implemented the two stubbed Genkit sandbox tools in `app.py` (~line 2430):
  `sandbox_fit_brooks_corey_tool` and `sandbox_fit_archie_tool` now instantiate
  `PhysicsSandbox` (imported inside the functions to avoid circular imports), call
  `.fit_brooks_corey(...)` / `.fit_archie(...)`, inject `sample_name` when provided,
  and return the fit dict as a JSON string.
- Committed the full (previously uncommitted) sandbox feature surface in `app.py`:
  `_HVIEL_TOOLS` schemas, `_execute_tool` handlers (run_sandboxed + session cache
  binding), `_format_tool_response` plot formatters, plus `tests/test_sandbox_tools.py`.
- Deliberately did NOT commit the still-pending NVIDIA NIM migration work
  (app.py remainder, `llm_json_utils.py`, `hviel_doc_engine.py`, `llm_insight_generator.py`,
  `scal_file_handler.py`, `physics_validator.py`, `src/`, other new tests, frontend/dist
  rebuild) — that belongs to the 2026-07-05 report-pipeline entry below and awaits its own commit.

**Verified:** `py -3.13 -m pytest tests/test_sandbox_tools.py` -> 2 passed.
Full worktree suite -> 318 passed. Suite re-run against exact commit content
(pending changes stashed) -> 295 passed (the 4 tests for uncommitted features excluded).

### [2026-07-05] Claude Code — Chat ground-truth injection capping (large-Excel context overflow fix)

**Did:**
- **Completed the injection-site fix** for the "large multi-sheet Excel overflows the chat context" bug (e.g. `Mercury Injection Well T1-31.xls`, 10 sheets → ~800K-char un-truncated `MANDATORY_GROUND_TRUTH_INVENTORY` injected into the prompt → negative `max_tokens` HTTP 400 from NVIDIA).
- Rewrote `_truncate_ground_truth()` (app.py ~line 858) with **two lines of defense, both env-configurable**:
  1. Per-sheet row capping — each sheet's `    ROW n: [...]` dump reduced to head/tail preview with an explicit `[TRUNCATED n ROWS ...]` marker. **`SCAL_GT_MAX_ROWS`** (default 6). Sheet names, `COLUMNS (...)` headers, and `FULL SHAPE` dimensions are always preserved so the model knows what exists and can ask for ranges.
  2. Overall char cap — **`SCAL_GT_MAX_CHARS`** (default 120000). If row-capping isn't enough, rows re-cap to a 2-row preview; pathological cases (huge cells) get a head+tail char cut plus an appended structural sheet index so no sheet name is ever lost.
- New helper `_cap_prompt_block()` (app.py ~line 838) — generic head+tail char cap with truncation marker.
- **All chat injection sites hooked** (both were inside `PRCChatAssistant.chat`):
  - app.py ~5158: `[MANDATORY GROUND TRUTH INVENTORY]` block in `extracted_context` → `_truncate_ground_truth(cached_gt)`; `[FULLY-VERIFIED EXTRACTION PARAMETERS]` (labeled_values) capped via `_cap_prompt_block`.
  - app.py ~5383: `MANDATORY_GROUND_TRUTH_INVENTORY (SESSION DATA CACHE)` block prepended to the dynamic system prompt inside `_generate()` → gt row/char-capped; **`CACHED LABELED VALUES` and `CACHED FLAT VECTORS` JSON dumps now capped too** via **`SCAL_GT_JSON_MAX_CHARS`** (default 30000) — flat_vectors holds full numeric column vectors per sheet (stored under two keys each) and was a second, previously-unguarded overflow vector.
  - Other `ground_truth` readers checked and confirmed non-injecting (provenance token lookup ~1670, `get_filenames_from_cache`, cache persistence) — no other chat-prompt injection points exist. The report pipeline (`sync_document_generation_task` system-instruction injection) was deliberately **not touched** per handoff scope.
- **Internal timeout audit:** NO ~90s timeout exists anywhere in this repo on the chat/LLM path. The only related timeouts: NVIDIA `urlopen` HTTP timeout (was hardcoded 120s) and a 15s SSE heartbeat poll (`asyncio.wait_for(q.get(), 15.0)` — a keepalive loop, not a cutoff). The 120s HTTP timeout is now env-configurable: **`SCAL_LLM_HTTP_TIMEOUT`** (default 300s), app.py ~176 + ~2753. The model-level 170K-char proportional-truncation backstop in `_nvidia_generate` remains as the final safety net.

**Verified:**
- `python -m py_compile app.py` — clean.
- `py -3.13 -m pytest tests/` — **293 passed, 0 failed** (10m26s, full suite green).
- Scratchpad stress test (not committed): built a fake 10-sheet × 2000-row inventory (~1.3M chars) in the exact `═══ FILE:` / `  SHEET:` / `    ROW n:` format — truncated output was 6.7K chars (defaults), all 10 sheet headers + COLUMNS + FULL SHAPE lines retained; pathological 600K-single-cell case capped at exactly 120000 chars with the sheet index preserved; env overrides and bogus env values verified.

**For Antigravity:**
- **Injection-site capping is DONE** — the chat path can no longer overflow on large workbooks regardless of file size.
- **The ~90s timeout on `process_single_item_agent` is in the EXTERNAL runner/harness, NOT this repo** — it still needs raising there (suggest honoring `SCAL_LLM_HTTP_TIMEOUT` or an equivalent 300s default). Nothing more can be done in-repo for it.
- **Report pipeline (`sync_document_generation_task` / MasterEngineerNode) is still on Gemini/genkit** — being migrated next (separate task, do not entangle with this change). genkit stays pinned at 0.4.0.
- New env knobs (all optional, sane defaults): `SCAL_GT_MAX_ROWS=6`, `SCAL_GT_MAX_CHARS=120000`, `SCAL_GT_JSON_MAX_CHARS=30000`, `SCAL_LLM_HTTP_TIMEOUT=300`.

### [2026-07-02] Antigravity — openpyxl upgrade + citation verification hardening

**Did:**
- Upgraded `openpyxl` from `3.1.0` to `3.1.5` in SCAL requirements.txt and local `.venv_win` environment. This resolves a critical conflict with the installed Pandas version that crashed Excel ingestion.
- Hardened the citation validation matching in `scal_file_handler.py`. Stopped checking generic well identifier tokens (`t1`, `31`, etc.) and stopwords (`well`, `sample`, etc.) during filename overlap checks. This prevents false positive matches on source mismatched files and makes the regression test pass.
- Verified that all 291 unit, validation, and physics sandbox tests are green and pass.

### [2026-06-30] Claude Code → Antigravity & User (Chat LLM swapped Gemini → NVIDIA NIM; 3 bug fixes; 1 open issue)

**Big change — chat brain is no longer Gemini.** User asked to move the Hviel chat
assistant + petrophysical tool-calling off Gemini onto **NVIDIA NIM** (OpenAI-compatible,
`https://integrate.api.nvidia.com/v1`). Final model: **`openai/gpt-oss-120b`** with
`reasoning_effort: "low"` (started on `nvidia/nemotron-3-super-120b-a12b` but it was too
slow — see open issue). This is a **local change, NOT pushed** to master yet.

**How it was done (contained, low blast-radius):**
- New NVIDIA backend block in `app.py` (just above `_call_gemini_with_retry`): stdlib
  `urllib` HTTP (NO `requests` dep), key-pool failover, and genai-shaped shim classes
  (`_NvResponse/_NvPart/_NvFuncCall…`) so the 5,500-line chat tool-loop is **untouched**.
- The two wrappers **`_call_gemini_with_retry` / `_call_gemini_stream_with_retry`** were
  rewritten to call NVIDIA and return those shims. Genkit (`ai.flow`, `genkit.types`,
  `GLOBAL_STREAM_QUEUES`) is **no longer used by the chat path**. (Genkit pins in
  requirements can stay for now; report-gen still imports them.)
- `_HVIEL_TOOLS` (Gemini uppercase schema) auto-converts to OpenAI tool format via
  `_nvidia_tools()` / `_nv_lower_schema()`; tool_call ids synthesized in
  `_nv_messages_from_neutral()`. Gemini `file_data` parts are **dropped** — the
  deterministic `scal_file_handler` ground-truth is injected as prompt text, so reads
  stay correct.
- Keys: `.env` `NVIDIA_API_KEY` (+ `NVIDIA_API_KEY1..N`), loaded by `_load_nvidia_keys()`
  near the `GEMINI_KEY_POOL` def. Health degraded-check repointed to the NVIDIA pool.
- Model/effort knobs live at module level: `NVIDIA_MODEL`, and `reasoning_effort` in the
  `_nvidia_generate` payload. Swap back to Gemini = git revert; backup at `app.py.bak_nvidia`.

**NOT swapped:** the report/extraction pipeline (`sync_document_generation_task`,
MasterEngineerNode) **still uses Gemini** (`client.models.generate_content`). Its
LLM-JSON extraction is occasionally flaky. If we want full sovereignty/NVIDIA, this is
the next chunk — but it's the heavy provenance path, do it carefully.

**3 bugs fixed this round (all verified live with T1-31 data):**
1. **Server SIGSEGV on any chat file-attach (CRITICAL).** `pd.read_excel` segfaulted in
   pyarrow. Root cause: **pandas 3.0.1** defaults `future.infer_string=True` → pyarrow
   strings, and **pyarrow 24 on Python 3.13 crashes** in `ArrowStringArray._from_sequence`.
   Fix: `pd.set_option("future.infer_string", False)` at the top of `scal_file_handler.py`
   (process-global). faulthandler trace confirmed the site (`scal_file_handler.py`
   `extract_absolute_file_truth`). **Antigravity: keep this option set; do not remove it
   while pandas≥3.0 / pyarrow≥24 are installed.**
2. **False "Source Mismatch / Cannot Verify".** `compress_traceability_ledger`
   (`scal_file_handler.py`) hard-refused when the model cited a paraphrased/spaced
   filename (e.g. dropped `T1-31` from `Mercury Injection Well T1-31.xls`). Loosened to
   token-overlap matching vs the union of expected-filename tokens (still refuses a
   genuinely different file). Unit-verified 7/7.
3. **`name '_os' is not defined`** in `sync_document_generation_task` (~line 9148) —
   added a local `import os as _os`.

**Verified:** SCAL `/health` ok; `.xlsx` chat-attach + summarize returns correct values +
provenance, ~30-40s, no crash, no false mismatch. PVT (sister repo) swapped the same way.

**OPEN ISSUE — need your help:** a single **10-sheet workbook**
(`Mercury Injection Well T1-31.xls`) fails chat-attach with
`[ERROR: Agent failed (Function process_single_item_agent timed out after 90.0 seconds),
API failed (API request returned None after all retries)]`. The string
`process_single_item_agent` is **NOT in any .py file** I could grep — it looks like a
batch/agent wrapper with a hard **90s** timeout that I never located. Small/medium files
(1-3 sheets) work fine. Hypotheses: (a) the 10-sheet ground-truth dump makes the prompt
huge → upstream call slow/None; (b) there's a separate agent path (not the wrappers I
swapped) still doing per-item processing with a 90s cap. **Antigravity: please (1) find
`process_single_item_agent` / the 90s timeout owner, and (2) either raise the cap or
truncate the injected ground-truth for >N-sheet workbooks.** Note the NVIDIA call itself
logs `[NVIDIA] generate -> model=… tools=…` — none appeared for this request, so it may
die before the LLM call.

**Left uncommitted:** `.env` only (key). Code is committed: `f85fcce` (swap + 3 fixes),
`942dc79` (.xls engine + context guard), `a61c71a` (cap tweak). Backup: `app.py.bak_nvidia`.
A temporary `_logger.info("[NVIDIA] generate -> …")` line is in `_nvidia_generate` — low noise.

**UPDATE 2 (same day) — two more fixes + the big-file root cause:**
4. **Legacy `.xls` read failure (was the user-visible "unable to extract usable data").**
   `file_reader._excel_engine()` chose the pandas engine via `zipfile.is_zipfile()`, which
   scans the WHOLE file for a ZIP end-of-central-directory sig and **false-positives on
   genuine OLE2 `.xls`** (they often contain that byte run) → routed real `.xls` to
   openpyxl → `File contains no valid workbook part` → empty ground-truth → model says
   "can't extract." Fixed: detect by HEADER magic bytes (`PK\x03\x04`→openpyxl,
   `D0CF11E0…`→xlrd). **This affects the entire T1-31 `.xls` set.** Verified: RI `.xls`
   now reads + analyzes (86 RI points, cited), ~45s.
5. **NVIDIA 400 `max_tokens must be at least 1, got -N`.** A large multi-sheet workbook's
   un-truncated ground-truth injects to **~800K chars** (the chat handler injects the full
   per-row dump, possibly at multiple points) → ~340K tokens → overflows gpt-oss-120b's
   131K context → NVIDIA returns a negative output budget. Added a backstop in
   `_nvidia_generate`: truncate the largest message so total input ≤ `_MAX_INPUT_CHARS`
   (currently 170000).

**STILL OPEN for you (Antigravity) — the 10-sheet `Mercury Injection Well T1-31.xls`:**
even with the cap, this one workbook is borderline (dense numeric tables tokenize heavily;
~4 min round-trips, sometimes still over context). The **right fix is at the injection
site, not my NVIDIA backstop**: the chat handler in `app.py` (`PRCChatAssistant.chat`,
the `extracted_context += "[MANDATORY GROUND TRUTH INVENTORY]…"` block ~line 5000, and the
`dynamic_system_prompt` ground-truth injection) dumps the FULL un-truncated per-row
inventory for ALL sheets. For big workbooks please (a) cap/sample the injected ground-truth
per sheet (e.g. head+tail rows like the PVT/`format_and_truncate_json_table` pattern already
used elsewhere), and (b) find the `process_single_item_agent` 90s timeout owner and raise
it or make big-file handling async. The deterministic extraction itself is correct now
(229K chars, 10 sheets) — it's purely a context-budget/latency problem downstream.

### [2026-06-29] Claude Code → Antigravity & User (Handover packaging: HANDOVER.md + docs/ tidy)

**Context:** Same day, follow-up to the Graph-RAG/Sandbox/visuals entry below. User is
handing the runnable repo to a new **Data Science team**. Goal was readability, not
behavior. No `.py` logic touched; physics gate unaffected.

**DID — staged (git mv renames + new file), NOT committed:**
1. **`HANDOVER.md` (NEW, root) — the single DS front door.** Run steps (`pip install`,
   `py -3.13 -m pytest tests/`, `run_local.cmd`, PIN 1509, `/health`), the physics-gate
   rule, a full **module map grouped by role** (entry/physics/knowledge/io/output/ops —
   compensates for the flat layout *without* moving the modules), upload→answer data
   flow, the Do-Not-Break invariants inlined, ranked tech-debt backlog (app.py monolith
   #1), and a day-one path. Also documents the new modules + the "health grade ≠ fit
   quality / read r²" gotcha.
2. **Docs de-cluttered.** `git mv` 13 deep-reference docs into `docs/` (ARCHITECTURE,
   DEVELOPER_DOCS, EXECUTIVE_DEMO_SCRIPT, HOST_PROFILE, KNOWLEDGE_BASE,
   PRC_MAINTENANCE_GUIDE, README_DEPLOYMENT, README_PROD, SOVEREIGN_SCAL_OPERATORS_MANUAL,
   SOVEREIGN_VAULT, future_tech_radar, walkthrough, task). Root now holds only the 5
   front-door docs: README, HANDOVER, CLAUDE, TEAM, AGENTS. History preserved (renames,
   `R` in git status).
3. **`README.md`:** fixed the broken `file:///` deployment link → `docs/README_DEPLOYMENT.md`;
   added a Documentation index.
4. **Kept TEAM.md/AGENTS.md framed as internal agent logs** — HANDOVER §6/§9 and the
   README index now explicitly tell the DS team these are *our* dev logs, not their
   operating docs (per user: "TEAM.md is ours"). DS team is NOT directed to read or
   append to TEAM.md.

**Did NOT do (decided against, with user):** the full Python package reorg
(engines/knowledge/io/core). 29 cross-importing modules + 9k-line app.py + your
uncommitted edits (`llm_insight_generator.py`, `requirements.txt`, frontend) → too much
churn/risk right before handoff. The HANDOVER module map gives the DS team the logical
organization at zero import risk. Left as debt item §8.1 for them to do on their terms.

**Verified:** root listing = 5 docs; `docs/` = 13; README link target exists; no `.py`
moved → gate untouched. (The 3 new modules were runtime-verified at their surfaces
earlier — 44 + 97 tests green, rendered PNG inspected.)

**For Antigravity:** doc paths changed — if any of your tooling references a moved doc,
repoint it to `docs/<name>`. Modules + HANDOVER are staged but uncommitted; user is on
`master`, 12 ahead of origin — branch before committing.

---

### [2026-06-29] Claude Code → Antigravity & User (Data-Science handover upgrades: Graph RAG + Physics Sandbox + decoupled visuals)

**Context:** Pre-handover hardening for the Data Science team. Three new production-grade,
strictly-typed, logger-only modules + tests. No existing physics/prompt/model logic touched;
new modules *import* the existing engines rather than duplicating them.

**DID — NOT committed (no git repo in this checkout; leaving staging to you):**
1. **Geological Graph RAG (`geological_graph.py`, NEW).** `GeologicalGraph` — SQLite property
   graph kept fully separate from the ChromaDB vector store. Nodes: Basin/Formation/Lithology/
   Well/FluidType (enum-validated). Edges: LOCATED_IN, HAS_LITHOLOGY, PENETRATES, CONTAINS_FLUID.
   API: `add_relation()` (idempotent upsert), `query_connections(node, depth_limit)` (bounded BFS
   → JSON subgraph), `neighbours_by_relation()`, `import_relations()` (bulk doc ingest, bad rows
   skipped), `hybrid_search(query, porous_range, perm_range, retriever)` (fuses graph BFS + vector
   analog-well lookup; retriever **injected** so it stays offline/CI-safe, mirroring the
   rag_database CI decision in the 2026-06-14 entry). All SQL parameterised (CLAUDE.md §4).
2. **Autonomous Physics Sandbox (`physics_sandbox.py`, NEW).** `PhysicsSandbox` runs
   fit → validate → auto-correct → re-validate. `fit_brooks_corey` / `fit_archie` (FF+RI) /
   `fit_waxman_smits`. Validation reuses `PhysicsGuard` (no duplicated rules). Auto-correct:
   out-of-bounds Archie exponents → bounded `curve_fit` clamp into the same [0.5,1.5]/[1.3,2.5]
   windows PhysicsGuard enforces; Kr anomalies → exponent ladder then escalate to the existing
   `PRCSimulatedAnnealing`. Hard guard: Sw ∉ [0,1] → `PhysicalValidationError` (uncorrectable).
   `run_sandboxed()` — restricted exec (AST audit blocks imports/dunder/open/eval; whitelisted
   builtins + math/numpy/scipy only). **Note:** this is best-effort, not a hardened jail —
   documented as such; don't feed it untrusted third-party code. Directly addresses the
   2026-06-16 Archie-FF "impossible a≈2.85, m≈1.44" risk by clamping into physical bounds.
3. **Decoupled visuals (`visualizer.py`, refactored).** Split coordinate generation from
   rendering: `extract_curve_coordinates()` is now pure → serialisable `{x, y, labels, title,...}`
   (zero matplotlib); `render_coordinate_payloads()` is the thin PNG wrapper; `generate_plots()`
   kept (app.py + test compat) and now just composes the two. All `print()` → `logging`.
4. **Config (`config.py`):** added `GRAPH_DB_PATH`, `SANDBOX_MAX_ITERATIONS`, `SANDBOX_SW_TOLERANCE`
   + `graph_db_path` property (defaults under `DB_DIR` so the graph survives Render redeploys,
   same pattern as the chroma store).
5. **Tests (NEW):** `tests/test_geological_graph.py` (14), `tests/test_physics_sandbox.py` (17),
   `tests/test_visualizer_coordinates.py` (7). Mocks kept out of production code.

**Verified:**
- `py -3.13 -m pytest tests/test_geological_graph.py tests/test_physics_sandbox.py tests/test_visualizer_coordinates.py tests/test_physics_validator.py tests/test_rag_database.py` → **44 passed**.
- Physics gate: `py -3.13 -m pytest tests/test_physics_and_skills_exhaustive.py` → **97 passed**, zero regressions.
- Local `.venv` is MinGW without pytest (CLAUDE.md §1 dev note) — ran via `py -3.13`.

**For Antigravity:** new modules are standalone — not yet wired into `app.py`'s chat/tool path.
If you want the agent to call them, register `PhysicsSandbox.fit_*` as tools and seed the
`GeologicalGraph` from the books/ corpus. `hybrid_search` expects a retriever exposing
`query_analog_wells(...)` — pass a live `RAGDatabase` to bridge graph + vectors. genkit stays
pinned 0.4.0. Run `python -m pytest tests/` before any push.

---

### [2026-06-28] Claude Code → Antigravity & User (Multi-worker hardening on top of the file-isolation fix)

**Context:** Reviewed Antigravity's file-ingestion cache-binding / session-isolation fix. Core fix is sound and tested. Found a gap it did not close: the tool-parameter cache reads bypassed the new content-hash keying, so they broke under `--workers 2`.

**DID — committed:**
1. **Multi-worker tool-param cache (`app.py`):** `get_param()` and the provenance cache-key resolver read `SESSION_DATA_CACHE.get(session_id)` directly — no hash resolve, no DB hydrate. On a worker that did not ingest the file → cache miss → `_MissingParam` / phantom values. Fixed: both now call `load_session_cache_from_db(session_id)` (called BEFORE acquiring `SESSION_DATA_CACHE_LOCK` — the lock is non-reentrant, calling it inside the `with` deadlocks), then read under `resolve_cache_key(session_id)` with a `session_id` fallback for legacy entries.
2. **Regression tests (`tests/test_file_isolation_regressions.py`):** added cross-worker + reference-citation coverage (see PVT note). SCAL suite green.

**Verified:**
- `py -3.13 -m pytest tests/` → exit 0 (full suite green).
- `py -3.13 -m pytest tests/test_file_isolation_regressions.py` → 6/6.

**For Antigravity:** the in-memory populate path (line ~820) still writes under raw `sid` while the DB persists under content hash; reads now reconcile via DB hydrate, but keying populate by hash directly would remove the double-store. Low priority.

---

### [2026-06-17] Antigravity → Claude Code & User (Fixing Physics Gaps & Classifier Alignment)

**DID — committed, all 248 tests green (10 files changed):**
1. **Archie Fit constraint (Gap 1):** Constrained $a \in [0.5, 1.5]$ in `regress_archie_m_a` (`petrophysics.py`). If violated, falls back to single-parameter fit with $a=1.0$, re-estimates $m$, and recalculates $R^2$ to ensure mathematical consistency.
2. **Constant MICP Saturation Rejection (Gap 2):** In `_pick_micp_sat_col` (`extractors/micp.py`), we reject columns with a numerical range $\le 10^{-4}$ (e.g. constant/zero-variance columns). Added a corresponding `HIGH` violation check `MICP_CONSTANT_SATURATION` in `PhysicsGuard.validate_micp` (`physics_validator.py`). Added `test_validate_micp_constant_saturation` in `tests/test_physics_validator.py`.
3. **Forbes Centrifuge Correction (Gap 3):** Implemented `forbes_correction` in `centrifuge_skill.py` using standard radial geometry parameters $B$ and $a_0$. Fallback to Hassler-Brunner occurs if inner/outer radii are missing/invalid. Added `test_forbes_correction` in `tests/test_centrifuge.py`.
4. **CT-scan lithology thresholds (Gap 4):** Refactored `interpret_ct_scan` (`petrophysics.py`) to make HU thresholds mutually exclusive and ordered.
5. **Classifier Alignment & OBP Support (Gap 5):** Unified test-type classification between `SCALFileHandler.identify()` and `file_reader._detect_test_type()` by enforcing word boundaries (`\b...\b`) on short keywords ($\le 4$ chars) like `'ro'`, `'phi'`. Added geomechanics/OBP keywords to `RCAL`. Added `"overburden_compaction"` test type rules and custom extraction to `file_reader.py` and `scal_file_handler.py`.
6. **Incomplete/Truncated Empty Responses Resolution:** Large document contexts caused Gemini's `<thinking>` block to consume the entire output budget. Fixed by adding a strict `<thinking>` length budget (4–5 sentences) in `prompts/hviel_system_prompt.md`, clearing the database query cache (`response_cache`), and deleting empty database responses.
7. **Local Server Setup:** Forcefully terminated any process locked on port 8000 using `kill_8000.cmd` to clean up the port and restarted the uvicorn background server task.

**Verified:**
- `py -3.13 -m pytest tests/` -> **248/248 tests passed** (0 failures).
- Real corpus verification run (`test_classify.py`) confirms `5_Phi_K_OBP.csv` and `6_Compressibility.csv` now classify as `overburden_compaction` with correct row counts.


### [2026-06-16] Claude Code → Antigravity (session 2 — ingestion hardening for tomorrow's data-science demo)

**Context:** Pre-demo push to make Hviel ingest ANY core-lab data type. Ran a 3-agent
parallel audit (ingestion / novel formats / petrophysics) over the real corpus at
`C:\Users\Asus\Downloads\Datasets_and_Spreadsheets\`. Verdict: math engines are sound
(97/97 physics tests), but ~41% of the corpus silently mis-extracted, Petrel XML exports
were 100% unreadable, and a few isolated physics gaps remain.

**DID — committed, all in `file_reader.py` + `scal_file_handler.py`, 246/246 tests green:**
1. **#1 ingestion bug fixed.** `_detect_data_block` (scal_file_handler.py) tested
   `isinstance(v,(int,float))` on `smart_read_csv(header=None)` output — which is ALL strings
   → counted 0 numeric cells → "no data block" on every header-bearing CSV. Added
   `_is_numeric_cell` / `_coerce_number` (coerce numeric strings, tolerate thousands
   separators); used them in block detection + row cleaning. Recovered 9 corpus CSVs
   (3_FF_Ambient 0→5 rows, 4_FF_OBP 0→39, real_data_extracted 0→115, Master_* , etc.).
2. **`.xls` content-sniff.** New `_excel_engine()` (file_reader.py): ZIP magic → openpyxl for
   xlsx-mislabeled-as-`.xls`, else xlrd. Wired into `_read_excel`, `SCALFileHandler.read`,
   `robust_extract_scal`, `extract_absolute_file_truth`. The 1 MB `HU...55plug.xls` (a real
   xlsx) now reads (was dead on every path).
3. **NEW: Petrel/KAPPA XML ingestion.** Added `_read_xml` + `_df_columns_stats` (file_reader.py),
   registered `.xml` in `read_file`, added `.xml` branches to `extract_file_data` and
   `extract_absolute_file_truth`. Parses the `<TabularData>` CDATA (markdown tables / whitespace
   RCAL / CSV templates) → excel/csv-shaped dicts. `Petrel_Export_1775421246.xml` → 3 typed
   tables (overburden φ/k/PV-compressibility, resistivity, MICP); `...3242.xml` → RCAL table with
   correct cols (SAMPLE_NO/DEPTH_FT/POR_PCT/...); `...4195.xml` → txt (template, no real data).
4. **DOCX tables in report pipeline.** `extract_file_data`'s `.docx` branch now routes through
   the table-aware `file_reader.read_file` (was `_extract_docx`, paragraphs-only → silently
   dropped every table), with fallback. (Session 1 also fixed the chat DOCX/PDF/TXT
   summarization refusal — commit 6872dbe.)

**Verified:** 246/246 pytest; module-level battery over the whole corpus (every
previously-failing file now `status=success` with real row counts); ground-truth inventory
now covers XML + .xls.

**YOU (Antigravity) — petrophysics correctness gaps (NOT fixed; these are math/guard files and
need your physics + PhysicsGuard care). Ranked by demo risk:**
1. **Archie FF free fit returns impossible a≈2.85, m≈1.44** on the real 7-sample data (lab pins
   a=1, m≈1.9–2.0). The unconstrained 2-param log-log fit is ill-conditioned over the narrow φ
   range; PhysicsGuard already flags ARCHIE_A_RANGE. **Fix:** force/offer the a=1 single-param
   Archie fit or constrain a∈[0.5,1.5]. File: the calc-skills `petrophysics.py::regress_archie_m_a`
   (grep for `regress_archie_m_a`). HIGHEST risk — a self-contradicting result on screen.
2. **MICP column-binding guard gap.** In `2_Mercury_Injection.csv` the obvious `'Sat. Hg'` column
   is constant junk (=7.0); the real curve is `'Sat. Hg.1'`. PhysicsGuard scores the WRONG column
   100/A. **Fix:** `physics_validator.PhysicsGuard.validate_micp` — reject near-zero-variance /
   constant saturation columns, prefer cumulative-intrusion. HIGH — wrong-column MICP is the most
   likely live failure on messy CSVs (extraction is the LLM's job and these files are pathological).
3. **Forbes centrifuge correction is advertised but has NO implementation anywhere** (only
   Hassler-Brunner exists in `centrifuge_skill.py`). **Fix:** implement Forbes, OR make dispatch
   fall back to HB with an explicit note so a "Forbes" request never errors mid-demo.
4. **CT-scan lithology bands overlap + dead branch** (`petrophysics.py::interpret_ct_scan`):
   shale [800,1400) is shadowed by sandstone [1200,1700); dolomite/limestone overlap. Make the HU
   thresholds mutually exclusive and ordered. Low blast radius (no CT file in corpus).
5. **Two test-type classifiers disagree** (`SCALFileHandler.identify()` vs
   `file_reader._detect_test_type`) → some files still mislabel (5_Phi_K_OBP, 6_Compressibility
   now extract rows fine but come back `data_type=UNKNOWN`; generic substrings porosity/phi/
   saturation pollute scoring). Down-weight those substrings or unify to one scorer. Medium — data
   is correct, only the label / chart-type is wrong.

**Notes:** genkit stays pinned 0.4.0. Server has **no --reload** → restart `run_local.cmd` to load
the file_reader/scal_file_handler changes. Gemini free-tier `gemini-2.5-flash` was intermittently
**503**-ing tonight (transient capacity, not code). Rel-perm (Brooks-Corey/LET) work but **no
Kr-bearing file is in the corpus** — load one before demoing that track.

**State:** master, committed (NOT pushed — Render suspended; deploy on your call).

### [2026-06-16] Claude Code → Antigravity
**Did:** Fixed Hviel refusing to read/summarize uploaded **DOCX** (and PDF/TXT) files in
chat (user hit it on "Draft Final Report CCASCAL Well T1-31"). Root cause in
`PRCChatAssistant.chat()` (`app.py`): freshly-uploaded non-tabular files were extracted to
text but only persisted to the `user_files` DB — never injected into the *current* turn's
prompt. The deterministic pre-parser also emitted a content-free
`[Non-tabular file, no sheet/column inventory applicable]` ground-truth block that (a) was
injected as if it were data and (b) made `extracted_context` non-empty, which suppressed
the follow-up document-recovery block. Net effect: the model saw only a filename +
"non-tabular" and refused.
**Changes (all in `app.py`, chat path only — no prompts/models/physics touched):**
- Inject freshly-uploaded DOCX/PDF/TXT text into the current turn's `extracted_context`
  (via `read_file`→`to_prompt_string`, so tables are preserved).
- Gate the structural ground-truth injection on actual tabular content (`COLUMNS (` or
  labeled_values) so the misleading non-tabular block is no longer injected and follow-up
  recovery can fire.
- Decoupled the hard-refusal gate from `extracted_context` — it now checks `has_cached_data`
  directly (fixes the populated-but-non-tabular cache case; was caught by
  `test_gate_allows_file_ref_when_cache_populated`).
- Capped injected raw doc text at 60k chars (a huge report made the mandated `<thinking>`
  block exhaust the output budget → empty reply) + a handler guard so a fully-stripped
  response never returns silently blank.
**Verified:** `py -3.13 -m pytest tests/` → **246 passed**. End-to-end via `/api/chat`:
small narrative DOCX → clean cited summary; 10 MB report → full executive summary +
petrophysical table, AutoGrader **100/100 Grade A**; follow-up with no re-upload → recovery
injected stored text (224k chars). Remaining intermittent failures were transient Gemini
`503 UNAVAILABLE` (model overload), not code.
**State:** master, committed (**NOT pushed** — Render suspended; deploy on your call).
Server has no `--reload`; relaunch `run_local.cmd` to pick up changes.
**For you:** Heads-up — the doc-generation path (`_detect_type` → `generate_document_json`
→ genkit `hviel_chat_flow`) still throws "Error while running action hviel_chat_flow" on
503s; that's the genkit flow, separate from this chat fix. genkit stays pinned 0.4.0.

### [2026-06-14] Antigravity → Claude Code
**Did:**
- Read `TEAM.md` and reviewed the handoff log.
- Ran the full test suite (`py -3.13 -m pytest`) with 246 tests passing successfully.
- Verified that all environment variables, Genkit version pins (`genkit==0.4.0` / `genkit-plugin-google-genai==0.4.0`), and `/health` liveness checks are active and working.
- Evaluated the ChromaDB analog-well RAG module (`rag_database.py`). Since it is designed to be CI-safe/offline and requires model downloads on first use, keeping it as an offline/legacy path (and not in the live chat flow) prevents high startup latency and network dependencies. Decided to keep the architecture as-is since the CI test suite is green and all invariants are strictly preserved.
**State:** master is fully green, 246 tests passed.
**For you:** The codebase is fully verified, healthy, and all test gates pass cleanly. Maintain Genkit version pins and compile the frontend (`npm run build` inside `frontend/`) if you make any changes to JSX/CSS.

### [2026-06-14] Claude Code → Antigravity
**Did:** Hardened the plumbing around your Genkit migration (I did not change the
AI's behavior/prompts/model). Specifically:
- Fixed the deploy-crasher: pinned `genkit==0.4.0` and added the missing
  `genkit-plugin-google-genai==0.4.0` (bare `genkit` was pulling 0.7.0 → no `genkit.ai`).
- Fixed the "Offline" badge: `App.jsx` `wake()` now polls `/health` not `/api/diag`;
  rebuilt `frontend/dist`.
- Re-enabled the CI suite (was 0 tests running → 243 pass, 3 integration skip on CI).
- Removed dead `streamlit` dep; documented `chromadb`; commented dead `CLAUDE_API_KEY`.
- `rag_database.py` persist dir now honors `DB_DIR`/`CHROMA_DIR`.
- Truth-up of `ARCHITECTURE.md`; removed a leaked credential from it.
- Added `run_local.cmd` (local demo launcher; login PIN 1509, http://127.0.0.1:8000).
**State:** master @ d4e444a, CI green. Verified locally end-to-end (boot, login,
live Brooks-Corey plot, SSE chat). Render is intentionally **suspended-by-user**
(cost) — demo runs locally only for now.
**For you (Antigravity):** Keep genkit pinned. If you touch `App.jsx`/CSS, run
`npm run build`. ChromaDB analog-well RAG (`rag_database.py`) is still NOT wired into
the chat flow — wire it in or remove it, your call.
**Left uncommitted:** nothing of mine. (Your earlier app.py work is committed in
bdbdebf.)

### [2026-06-18] Claude Code — PRC AI Hub Synchronization
**Did:**
- Shared PRC vault: `app.py` now defines `PRC_VAULT` (env `PRC_AI_VAULT`, default
  `C:/Users/Asus/Downloads/PRC_AI_Vault`). `HvielDocEngine(output_dir=PRC_VAULT)`,
  `_DOWNLOAD_ROOT = PRC_VAULT`, and `/api/report/download` now serve from the vault.
  `report_generator.PRCReportEngine.generate` writes the executive `.docx` there too.
- Frontend Glass-Brutalist sync: ported PVT/Aviel tokens + scanline terminal overlay +
  brutalist borders + typewriter cursor into `frontend/src/index.css` (additive — nothing
  removed; PVT global body/scrollbar resets intentionally NOT copied so SCAL keeps its
  Outfit prose font + scroll model). `App.jsx`: scanline overlay on the main panel and
  amber glow on the brand marks. `npm run build` re-run → `frontend/dist` current.
**Verified:** `/health` ok; frontend build green (2.85s). Genkit pins untouched.
**For Antigravity:** keep `PRC_AI_VAULT` consistent with PVT; rebuild the frontend if you
touch JSX/CSS.

### [2026-06-18] Claude Code — Larger upload cap for big lab reports
**Did:** `app.py` `_MAX_UPLOAD_BYTES` is now
`int(os.getenv("SCAL_MAX_UPLOAD_MB","75")) * 1024 * 1024` (was a hard 20 MB), and the
per-file chat-upload guard uses the same constant with a dynamic limit message. The
512 KB streaming size guard is unchanged. SCAL's `file_reader.py` (pdfplumber / docx /
pandas) already reads tables — this only lifts the size ceiling so large PDFs/workbooks
ingest. Override via `SCAL_MAX_UPLOAD_MB`.
**Security note:** this deliberately raises the CWE-400 DoS ceiling for the sovereign
on-prem box — keep behind the LAN. **Verified:** `/health` ok; `py_compile` clean.
**For Antigravity:** run `python -m pytest tests/` before any push (a hardened constant
changed). Frontend untouched this round.

### [2026-06-18] Claude Code — Production Readiness Audit fixes
**Did:**
- `app.py`: fixed `NameError` in the SPA catch-all (`_pathlib.Path` -> `Path`);
  restricted CORS `allow_origin_regex` to localhost/loopback (matches the PVT
  backend); enabled `PRAGMA foreign_keys = ON` in the sqlite `_get_conn` handler;
  the three report call sites now pass `output_dir=str(PRC_VAULT)` explicitly.
- `report_generator.py`: `generate(..., output_dir=None)` with precedence
  `output_dir -> PRC_AI_VAULT env -> os.getcwd()/reports` (restores the unit-test
  default while the app writes to the shared vault).
- `extra_routes.py`: `/api/admin/*` routes gated with `Depends(verify_admin)`,
  injected via `register_extra_routes(app, db, verify_admin=None)`.
- Removed root clutter: `app.py.bak`, `6.31.1`.
**Verified:** `python -m pytest tests/` -> 248 passed. py_compile clean.
