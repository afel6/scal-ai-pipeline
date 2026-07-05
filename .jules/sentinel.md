## 2024-07-05 - Path Traversal (startswith check bypass)
**Vulnerability:** Path containment checks in file download endpoints used string comparison (`startswith`) instead of robust path resolution, allowing potential bypasses (e.g. `reports/../reports-secret` vs `reports/`).
**Learning:** Using `str.startswith()` on paths is insecure because it only checks string prefixes, not actual path hierarchy.
**Prevention:** Always use `pathlib.Path.is_relative_to()` or `os.path.commonpath()` for path containment checks.
