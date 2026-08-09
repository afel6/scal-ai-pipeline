## 2026-08-09 - Fix Timing Attack Vulnerability in Authentication
**Vulnerability:** Timing attack vulnerability due to simple string inequality comparisons (`!=`) for sensitive authentication pins.
**Learning:** Using simple string comparison for authentication secrets allows attackers to measure the time taken to evaluate the condition, potentially revealing the secret length or prefix.
**Prevention:** Use `hmac.compare_digest` for all string comparisons involving passwords, pins, tokens, or other sensitive authentication secrets to ensure constant-time comparison. Both inputs should be encoded to bytes to avoid type mismatch errors.
