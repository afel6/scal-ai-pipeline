## 2025-01-01 - Path Traversal Vulnerability via Insecure startswith
**Vulnerability:** Insecure path containment checks using `str.startswith` allowed path traversal.
**Learning:** `str.startswith` is unsafe for path validation. For example, `str("/app/dist_secrets/key.txt").startswith("/app/dist")` evaluates to `True`, allowing access to unintended files outside the intended directory.
**Prevention:** Always use `pathlib.Path.is_relative_to()` for path containment validation. It correctly checks if a path is a true subdirectory.