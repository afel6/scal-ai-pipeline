## 2024-05-18 - Fix path traversal vulnerability in static file serving
**Vulnerability:** Found `str.startswith()` being used for path containment checks, which allows path traversal attacks. For example, if a directory is `/foo/dist` and the requested path resolves to `/foo/dist_secrets/key.txt`, the string comparison `startswith("/foo/dist")` will evaluate to `True`, bypassing the check.
**Learning:** String comparisons are insecure for path validation because they don't respect directory boundaries.
**Prevention:** Always use `pathlib.Path.is_relative_to()` or `os.path.commonpath()` for path containment checks.
