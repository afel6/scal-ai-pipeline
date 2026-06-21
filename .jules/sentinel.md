## 2026-05-10 - [Path Traversal via Python String startswith]
**Vulnerability:** A path traversal vulnerability existed in file download and static file serving routes because path containment was validated using `str(target).startswith(str(base_dir))`.
**Learning:** `startswith` checks string prefixes, not path hierarchies. For example, `"/tmp/dist_hacked".startswith("/tmp/dist")` evaluates to `True`, allowing attackers to access parallel directories that share the same string prefix by manipulating URLs to resolve to them.
**Prevention:** Always use structural path containment methods like `pathlib.Path.is_relative_to(base_dir)` or `os.path.commonpath([base_dir, target]) == base_dir` when validating if a file path safely resides within an allowed directory.
