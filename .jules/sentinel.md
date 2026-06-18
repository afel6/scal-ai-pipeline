## 2024-05-24 - Fix path traversal string comparison vulnerability
**Vulnerability:** String comparison `str.startswith()` used for path containment checks.
**Learning:** `startswith()` on path strings allows path traversal bypass, e.g. `/dist_secrets/` starts with `/dist`, but it is not contained within it.
**Prevention:** Use `pathlib.Path.is_relative_to()` to ensure correct path containment.
