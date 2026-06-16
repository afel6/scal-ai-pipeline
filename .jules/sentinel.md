## 2025-01-28 - Insecure Path Containment Using string.startswith()

**Vulnerability:** Path Traversal via Insecure Prefix Matching (CWE-22)
**Learning:** Checking if a file belongs inside a directory by converting both to strings and using `str(target).startswith(str(root))` is insecure. It fails to account for directory boundaries and allows an attacker to traverse to sibling directories that share the same prefix (e.g., escaping `/app/reports/` by requesting `../reports_secret/foo.txt`, because `/app/reports_secret/foo.txt` starts with `/app/reports`).
**Prevention:** Always use `pathlib.Path` exclusively and enforce directory containment using the secure, boundary-aware `target.is_relative_to(root)` method instead of string comparisons.