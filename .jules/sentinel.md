## 2025-05-18 - Fix Prefix Path Traversal in File Download and Serve Routes
**Vulnerability:** The application used insecure `str.startswith()` logic to verify if user-requested file paths were contained within allowed directories, such as `/api/download/{filename:path}` and `/{full_path:path}`. Since strings do not understand path delimiters, `/app/dist_secret` successfully matched as "starting with" `/app/dist`, allowing malicious users to read files from sibling directories that share a prefix with the targeted directory.
**Learning:** `startswith` string matching is insufficient for path security checking.
**Prevention:** Use `os.path.commonpath([target, base]) == base` or `pathlib.Path.is_relative_to` to verify true directory containment.
