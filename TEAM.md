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
