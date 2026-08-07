## 2025-02-12 - Timing Attack in PIN Authentication
**Vulnerability:** The application used a standard inequality operator (`!=`) to compare the user-provided PIN against the target ADMIN_PIN in the authentication endpoints (`/api/auth` and `/api/admin/auth`).
**Learning:** String comparison with `!=` or `==` stops at the first mismatch, allowing an attacker to deduce the string character by character by measuring the response time (timing attack).
**Prevention:** To prevent timing attacks when validating sensitive strings like passwords, PINs, or tokens, use Python's `hmac.compare_digest` instead of standard equality operators. Ensure both arguments are encoded to bytes before comparison to avoid type mismatch errors, and include null checks prior to encoding to prevent AttributeErrors.
