## 2024-07-01 - Prevent Timing Attacks and Log Leakage in Authentication
**Vulnerability:** Timing attacks on PIN validation (using `!=` instead of `hmac.compare_digest`) and sensitive inputs (`{pin}`) exposed in application warning logs.
**Learning:** Standard string comparisons fail early on mismatch, allowing attackers to guess valid PINs based on response time. Additionally, logging raw inputs can expose credentials if logs are intercepted or improperly stored.
**Prevention:** Always use constant-time comparison methods (`hmac.compare_digest`) for secrets and ensure variables containing sensitive material are excluded from log outputs.
