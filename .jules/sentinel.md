
## 2024-05-24 - Timing Attack Vulnerability in Authentication

**Vulnerability:** Found insecure string comparison (`!=`) being used to verify authentication PINs in `user_login` and `admin_login` routes in `app.py`.

**Learning:** Standard string comparisons can be vulnerable to timing attacks, allowing attackers to incrementally guess the secret PIN byte-by-byte by measuring the time taken for the comparison to fail.

**Prevention:** Always use constant-time comparison functions like `hmac.compare_digest()` (or `secrets.compare_digest()`) for validating sensitive secrets like passwords, PINs, or API keys.
