## 2025-02-27 - Path Traversal Prevention via is_relative_to
**Vulnerability:** Found uses of `str(path).startswith(str(base_path))` when checking if a file or directory path was contained within a safe root directory.
**Learning:** Checking directory containment using `str.startswith()` is vulnerable if the base path happens to be a prefix of another directory (e.g., comparing `/app/dist` vs `/app/dist_secrets`). Even though `resolve()` removes `../` components, `startswith` does not verify directory boundaries.
**Prevention:** When enforcing directory bounds to prevent path traversal vulnerabilities, use `pathlib.Path.is_relative_to(base_path)` or `os.path.commonpath([base_path, path]) == base_path` rather than insecure string comparisons.
