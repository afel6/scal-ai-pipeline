## 2024-06-13 - Path Traversal Vulnerability with string startswith
**Vulnerability:** Path containment checks in `app.py` were using `str(target).startswith(str(ROOT))` (e.g., in `/api/download/{filename:path}`, `/api/reports/{filename:path}`, and `serve_spa(full_path: str)`). This is vulnerable to path traversal because a directory like `/app/reports_secret` starts with the prefix `/app/reports`, meaning the check could be bypassed if a similarly named directory is accessed.
**Learning:** Using string manipulation for path checks is inherently flawed. Even with string prefixes, an attacker can exploit the boundaries of directory names.
**Prevention:** Always use `pathlib.Path.is_relative_to(ROOT)` or `os.path.commonpath` to robustly enforce directory containment.
