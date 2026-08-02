## 2024-05-24 - Timing Attacks on Login Endpoints
**Vulnerability:** Found insecure string comparison (`!=`) used for PIN validation in `user_login` and `admin_login` endpoints, which is susceptible to timing attacks.
**Learning:** Standard string comparisons fail fast upon encountering the first differing character, leaking the length of the matching prefix through execution time, which allows attackers to brute-force the pin character-by-character.
**Prevention:** Always use `hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))` for sensitive string validations to ensure constant-time comparison, including null checks prior to comparison to prevent `AttributeError`.
