# Emergency Chat Cache & Negation Classifier Realignment Checklist

- `[x]` Phase 1: Negation-Aware Document Classifier
  - `[x]` Add explicit negation patterns (e.g. `'no word'`, `'answer them here'`) in `_detect_type` in [hviel_doc_engine.py](file:///c:/Users/Asus/Downloads/scal-ai-pipeline/hviel_doc_engine.py)
  - `[x]` Verify that negation pattern matches return `None` to bypass document compilation

- `[x]` Phase 2: Database-Backed Session Cache Schema
  - `[x]` Implement `session_cache` database table schema inside `init_db()` in [app.py](file:///c:/Users/Asus/Downloads/scal-ai-pipeline/app.py)
  - `[x]` Enforce absolute cleanups inside `evict_session` to clear session cache rows in the DB

- `[x]` Phase 3: DB Cache Persistence (Write)
  - `[x]` Create thread-safe serializer helper `save_session_cache_to_db(sid)`
  - `[x]` Trigger database persistence at the end of `populate_cache_from_ground_truth`
  - `[x]` Trigger database persistence at the end of `cache_excel_data_vectors`

- `[x]` Phase 4: DB Cache Dynamic Re-Hydration (Read)
  - `[x]` Create thread-safe deserializer helper `load_session_cache_from_db(sid)`
  - `[x]` Call cache hydration at the start of `PRCChatAssistant.chat(...)`
  - `[x]` Call cache hydration at the start of `find_cached_vector(...)`

- `[x]` Phase 5: Re-Entrancy Deadlock Remediation
  - `[x]` Audit and fix `save_session_cache_to_db` indentation inside `populate_cache_from_ground_truth`
  - `[x]` Ensure no DB queries run while holding `SESSION_DATA_CACHE_LOCK`

- `[x]` Phase 6: Full Verification
  - `[x]` Execute automated chat cache test suite `pytest tests/test_chat_cache_refactor.py` (8/8 PASSED)
  - `[x]` Execute automated async remediation suite `pytest tests/test_async_remediation_hardened.py` (8/8 PASSED)
  - `[x]` Execute petrophysical math suite `pytest tests/test_displacement_efficiency.py` (4/4 PASSED)

- `[x]` Phase 7: Redirect Loop Remediation
  - `[x]` Lock `initialLoadGuard.current = true` immediately in `frontend/src/App.jsx` if `prc_session_id` in localStorage is empty.

- `[x]` Phase 8: Session Registration & Naming Synchronicity
  - `[x]` Synchronously insert session row at the start of `/api/chat/stream` before returning StreamingResponse.
  - `[x]` Synchronously insert session row at the start of `handle` in `POST /api/chat`.
  - `[x]` Add session registration and auto-renaming to `/api/v1/analyze-scal`.

- `[x]` Phase 9: Compressibility Keyword Standardisation
  - `[x]` Add `"compressibility"` keyword mapping in `populate_cache_from_ground_truth` to standardise `"pore_volume_compressibility"`.
