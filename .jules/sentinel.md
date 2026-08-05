## 2024-08-05 - Insecure Path Containment Checks
**Vulnerability:** Path traversal checks were using string comparison (str.startswith) rather than path hierarchy checks.
**Learning:** String comparisons for path containment allow paths like /target-dir-spoof to bypass checks intended for /target-dir.
**Prevention:** Always use pathlib.Path.is_relative_to() or os.path.commonpath() for path containment validation.
