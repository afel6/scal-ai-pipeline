## 2024-05-18 - Prevent Timing Attacks in Login Endpoints
**Vulnerability:** Direct string comparison (`!=`) was used to compare user-provided PINs against the expected `ADMIN_PIN`.
**Learning:** Standard string comparisons in Python return early as soon as a mismatch is found, meaning the time taken to check a string is proportional to the number of correctly guessed characters. This exposes the application to timing attacks, where an attacker can systematically guess the PIN by measuring the response time.
**Prevention:** Always use constant-time string comparison functions like `hmac.compare_digest()` for comparing sensitive information such as passwords, PINs, or authentication tokens.
