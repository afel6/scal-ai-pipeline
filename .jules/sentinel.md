
## 2025-02-15 - Prevent Timing Attacks and Secure Logging in Auth Endpoints
**Vulnerability:** Authentication endpoints used a standard inequality operator (`!=`) for PIN verification and logged the input PIN on failure.
**Learning:** Using standard comparison operators for authentication allows timing attacks, as they return early on mismatches. Also, logging sensitive input strings like failed PINs exposes them to anyone with log access.
**Prevention:** Use `hmac.compare_digest` with UTF-8 byte encoding for constant-time comparisons, and avoid inserting sensitive input values into log messages.
