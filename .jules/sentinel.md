## 2024-07-03 - Path Traversal Vulnerability using startswith

**Vulnerability:** Path traversal checks in `app.py` were using `str(target).startswith(str(dir))` to verify if a resolved path was inside a target directory.
**Learning:** Checking paths using string `.startswith()` is insecure because a directory like `/tmp/secrets` will pass the `.startswith('/tmp/secret')` check.
**Prevention:** Use `pathlib.Path.is_relative_to(target_dir)` or `os.path.commonpath()` for secure directory containment checks instead of plain string prefixes.
