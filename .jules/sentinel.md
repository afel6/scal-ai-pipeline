## 2026-07-31 - Fix timing attack vulnerability in PIN validation
**Vulnerability:** Timing attack vulnerability in PIN validation where `!=` string comparison was used to check `pin` against `target_pin` in `user_login` and `admin_login` routes.
**Learning:** Standard string comparison operators (`==`, `!=`) return immediately upon finding a mismatch, leaking the length of the matching prefix via execution time, which allows attackers to brute-force secrets character by character.
**Prevention:** Always use `hmac.compare_digest` with properly encoded byte strings and pre-check for null values when comparing sensitive data like passwords, PINs, tokens, or API keys.
