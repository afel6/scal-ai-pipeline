## 2024-07-16 - Timing Attack Vulnerability in Authentication

**Vulnerability:** The application used insecure string comparison (`pin != target_pin`) to validate user and admin PINs in the `/api/auth` and `/api/admin/auth` endpoints. This approach is susceptible to timing attacks, as string comparison stops at the first differing character, leaking the expected string character by character based on the time it takes to process the request.

**Learning:** When validating sensitive information like passwords, PINs, tokens, or API keys, standard equality operators (`==` or `!=`) expose the system to timing side-channels. Attackers can exploit this by measuring minute differences in response times to brute-force the secret sequentially.

**Prevention:** To prevent timing attacks, always use constant-time comparison functions, such as Python's `hmac.compare_digest(a, b)`, when comparing sensitive strings. Ensure that the target secret exists to avoid unexpected behavior with empty strings.
