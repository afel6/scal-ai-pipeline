## 2025-02-23 - Path Traversal Vulnerability Fix
**Vulnerability:** Path traversal vulnerabilities via insecure `str.startswith()` used for directory containment checks in `app.py`'s file serving logic.
**Learning:** `str.startswith()` is insecure because it can be bypassed using manipulated paths or common prefixes (e.g. `/app/dist_secrets` starts with `/app/dist`). `pathlib.Path.is_relative_to()` or `os.path.commonpath` must be used for secure containment checks.
**Prevention:** Always use `pathlib.Path.is_relative_to()` for path containment checks instead of error-prone string operations like `str.startswith()`.
