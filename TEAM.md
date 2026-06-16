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

### [2026-06-17] Antigravity → Claude Code & User (Fixing Physics Gaps & Classifier Alignment)

**DID — committed, all 248 tests green (9 files changed):**
1. **Archie Fit constraint (Gap 1):** Constrained $a \in [0.5, 1.5]$ in `regress_archie_m_a` (`petrophysics.py`). If violated, falls back to single-parameter fit with $a=1.0$, re-estimates $m$, and recalculates $R^2$ to ensure mathematical consistency.
2. **Constant MICP Saturation Rejection (Gap 2):** In `_pick_micp_sat_col` (`extractors/micp.py`), we reject columns with a numerical range $\le 10^{-4}$ (e.g. constant/zero-variance columns). Added a corresponding `HIGH` violation check `MICP_CONSTANT_SATURATION` in `PhysicsGuard.validate_micp` (`physics_validator.py`). Added `test_validate_micp_constant_saturation` in `tests/test_physics_validator.py`.
3. **Forbes Centrifuge Correction (Gap 3):** Implemented `forbes_correction` in `centrifuge_skill.py` using standard radial geometry parameters $B$ and $a_0$. Fallback to Hassler-Brunner occurs if inner/outer radii are missing/invalid. Added `test_forbes_correction` in `tests/test_centrifuge.py`.
4. **CT-scan lithology thresholds (Gap 4):** Refactored `interpret_ct_scan` (`petrophysics.py`) to make HU thresholds mutually exclusive and ordered.
5. **Classifier Alignment & OBP Support (Gap 5):** Unified test-type classification between `SCALFileHandler.identify()` and `file_reader._detect_test_type()` by enforcing word boundaries (`\b...\b`) on short keywords ($\le 4$ chars) like `'ro'`, `'phi'`. Added geomechanics/OBP keywords to `RCAL`. Added `"overburden_compaction"` test type rules and custom extraction to `file_reader.py` and `scal_file_handler.py`.
6. **Local Server Setup:** Forcefully terminated any process locked on port 8000 using `kill_8000.cmd` to clean up the port.

**Verified:**
- `py -3.13 -m pytest tests/` -> **248/248 tests passed** (0 failures).
- Real corpus verification run (`test_classify.py`) confirms `5_Phi_K_OBP.csv` and `6_Compressibility.csv` now correctly classify as `overburden_compaction` with correct row counts.

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
