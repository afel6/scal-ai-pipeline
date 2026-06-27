## 2024-05-15 - Insecure path comparison using `str.startswith`
**Vulnerability:** Path traversal (Directory Traversal)
**Learning:** Using `str.startswith()` to check if a path is contained within a directory is vulnerable because it can be bypassed. For example, if the safe directory is `/var/www`, a malicious path like `/var/www-secret` would pass the `startswith('/var/www')` check, even though it points to a different directory.
**Prevention:** Always use `pathlib.Path.is_relative_to()` or `os.path.commonpath()` to correctly determine if a path is fully contained within a target directory.
