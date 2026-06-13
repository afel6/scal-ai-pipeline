
## Security Learnings: 2024-xx-xx - Mitigating DoS in Deserialization

**Vulnerability Pattern:**
The use of `ast.literal_eval` on user-supplied strings can be manipulated to cause a Denial of Service (DoS). While safer than `eval()` against RCE, deep structures in `ast.literal_eval` can hit the recursion limit, cause a segmentation fault, or trigger CPU/Memory exhaustion during AST parsing. In `app.py`, this was used to deserialize lists of strings representing spreadsheet columns and rows from unstructured outputs.

**Prevention Strategy:**
Avoid `ast.literal_eval` for parsing user-supplied data unless absolutely necessary and heavily sanitized.
We created a custom parser `safe_parse_list` that avoids the Python AST module entirely. It tokenizes scalar primitive lists iteratively, providing high-performance parsing of structured outputs without the risk of deep recursion or AST memory explosion.
