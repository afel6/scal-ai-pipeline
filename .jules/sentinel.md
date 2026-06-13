
## Security Fix: Unsafe Deserialization via ast.literal_eval in Ground Truth Cache Population

**Date:** $(date +%Y-%m-%d)
**File:** app.py
**Vulnerability Type:** Insecure Deserialization / Denial of Service (DoS)

### 🎯 What
The application previously used `ast.literal_eval` to parse strings representing lists of columns and rows into Python list objects within the `populate_cache_from_ground_truth` function. `ast.literal_eval`, while safer than `eval`, is still vulnerable to Denial of Service attacks when parsing deeply nested structures. By providing heavily nested arrays, an attacker could trigger excessive recursion or high memory usage, leading to an application crash.

### ⚠️ Risk
If an attacker can manipulate or upload the "ground truth" input containing deeply nested string structures, the subsequent calls to `ast.literal_eval` during parsing would consume disproportionate system resources, leading to Denial of Service for the application instance.

### 🛡️ Solution
The vulnerable `ast.literal_eval` calls were replaced with a new internal helper function, `_safe_parse_list`. This function implements a robust, manual, shallow tokenization parser. It extracts elements by commas (respecting string literals and escapes) and natively parses booleans (`True`, `False`), `None`, floats, and integers. Crucially, it inherently ignores deep nesting and does not recurse, executing in linear time $O(N)$. This completely eliminates the Denial of Service vector associated with deeply nested structures.
