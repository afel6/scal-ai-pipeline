# Security Learnings & Sentinel Journal

## Missing Authentication on Admin Endpoints

* **Vulnerability Pattern:** Exposing admin/internal APIs without requiring proper authentication headers (e.g. Bearer token) or authorization checks.
* **Risk/Impact:** Internal data (system metrics, feedback logs, session events, total registered users, knowledge base size, etc.) is leaked to any unauthenticated client who knows the endpoint URL. For competitive or state-affiliated software, internal system metrics and usage numbers could be sensitive intelligence. Unbounded unauthenticated queries could also lead to a Denial of Service (DoS) since metrics queries may do full table scans across large tables (`SELECT COUNT(*) FROM...`).
* **Prevention Strategy:**
  1. Adhere to the DRY (Don't Repeat Yourself) principle. Defining similar endpoint structures in different files (`extra_routes.py` and `app.py`) without checking for their redundant definitions resulted in `app.py` correctly implementing `Depends(verify_admin)` while the duplicate endpoints in `extra_routes.py` circumvented the protection completely.
  2. Implement proper authentication dependency injections systematically to all internal APIs.
  3. Prefer centralizing route configuration for sensitive administrative features, making audits simpler and discrepancies easier to spot.
