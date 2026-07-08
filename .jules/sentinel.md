## 2024-07-08 - [CRITICAL/HIGH] Fix path traversal vulnerability bypass
**Vulnerability:** Path traversal due to string-based path containment checks (`str.startswith()`) which can be bypassed if an attacker can construct a path with a suffix (e.g. `/app-backup/secret.txt` passes `startswith('/app')`).
**Learning:** String containment on file paths is inherently flawed.
**Prevention:** Always use `pathlib.Path.is_relative_to()` or `os.path.commonpath()` for boundary checks.
