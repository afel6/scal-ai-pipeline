## 2026-06-26 - [CRITICAL] Fix Path Traversal using startswith

**Vulnerability:** The application was using `str(target).startswith(str(_DOWNLOAD_ROOT))` (and similar constructs in other path handlers) to restrict access to local directories. This allowed path traversal using crafted directory structures (e.g. `_DOWNLOAD_ROOT_secrets/key.txt` starts with `_DOWNLOAD_ROOT`, bypassing the validation entirely).

**Learning:** String comparisons like `startswith()` do not validate path directory structures logically, leaving paths vulnerable to prefix attacks. It only checks the characters of the string.

**Prevention:** Always use `pathlib.Path.is_relative_to(base_dir)` (or `os.path.commonpath`) to logically enforce directory boundaries and securely evaluate path containment.
