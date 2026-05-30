# Emergency Chat Pipeline Realignment Checklist

- `[x]` Phase 1: Force Chat Ingestion to call deterministic Report Extraction
  - `[x]` Replaced redundant context assembler loop inside `PRCChatAssistant.chat(...)` with shared parser: `extract_absolute_file_truth`
  - `[x]` Populate thread-safe cache `SESSION_DATA_CACHE[sid]` with ground-truth inventory
  - `[x]` Persist layout-aware text parsing inside `user_files` table to enable high-fidelity context recovery on follow-up chat turns

- `[x]` Phase 2: High-Fidelity Data & Vector Ingestion
  - `[x]` Cache full Excel numeric vectors as lists of floats inside `SESSION_DATA_CACHE[sid]["flat_vectors"]` via `cache_excel_data_vectors`
  - `[x]` Prepend ground-truth structural inventory, labeled cell values, and raw flat vectors to `dynamic_system_prompt` on every chat turn

- `[x]` Phase 3: Remove Hard-Coded Blanket Refusal Gate
  - `[x]` Locate strict provenance filter at the end of `process_provenance_tokens` in [app.py](file:///c:/Users/Asus/Downloads/scal-ai-pipeline/app.py)
  - `[x]` Delete the `[unverified` interception block completely to prevent dropping user queries and throwing error strings

- `[x]` Phase 4: Synchronous Ingestion Cache Hydration Hotfix
  - `[x]` Implement synchronous file reading and cache hydration inside `/api/v1/analyze-scal`
  - `[x]` Synchronously extract ground truth via `extract_absolute_file_truth` and populate labeled values / flat vectors on upload
  - `[x]` Seek the uploaded file stream back to 0 so that background and downstream streams remain fully functional

- `[x]` Phase 5: Lock Petrophysical Math & CORS Settings
  - `[x]` Freeze Displacement Efficiency equation to the mobile-volume standard: $Ed = (1 - Swi - Sor) / (1 - Swi)$
  - `[x]` Maintain non-blocking `Path.iterdir()` traversal for fast Render container bootup
  - `[x]` Keep compliant dynamic CORS origin matching policies active

- `[x]` Phase 6: Verification & Documentation
  - `[x]` Execute automated chat cache test suite `pytest tests/test_chat_cache_refactor.py` (8/8 PASSED)
  - `[x]` Update [walkthrough.md](file:///C:/Users/Asus/.gemini/antigravity/brain/778f8c70-66f3-424d-b591-eeb9a98b09ae/walkthrough.md) with exact git diff details and hotfix summaries
