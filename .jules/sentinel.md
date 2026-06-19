## 2026-05-10 - [Path Traversal] Path containment bypass via substring match
**Vulnerability:** Endpoints serving files used `str.startswith()` to enforce path containment. A malicious filename could start with the same directory prefix (e.g. `/app/reports_secret_key.txt` starts with `/app/reports`), successfully bypassing the check.
**Learning:** `startswith` checks string prefixes, not path hierarchy. It is inadequate for directory traversal mitigation because it matches any text appended to a directory name.
**Prevention:** Always use `pathlib.Path.is_relative_to` or `os.path.commonpath` to enforce absolute directory containment.

## 2026-05-10 - [Timing Attack] String comparison of sensitive tokens
**Vulnerability:** The `/api/auth` and `/api/admin/auth` endpoints used the `!=` operator to validate the `ADMIN_PIN`.
**Learning:** Python's `==` and `!=` operators exit early on the first mismatched character. This allows attackers to iteratively guess the PIN by measuring the response time (a side-channel timing attack).
**Prevention:** Use `hmac.compare_digest` for all comparisons involving secrets, PINs, passwords, and authorization tokens to ensure constant-time checking.
