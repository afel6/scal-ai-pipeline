## 2026-06-13 - Path Traversal bypass fixed
**Vulnerability:** Path containment checks using `startswith()` could be bypassed if an attacker specified a folder named as a prefix extension of the restricted directory.
**Learning:** Relying on simple string matching for path structures allows semantic logic bypasses because strings don't respect filesystem boundaries.
**Prevention:** Always use semantic path functions like `pathlib.Path.is_relative_to()` or `os.path.commonpath()`.
