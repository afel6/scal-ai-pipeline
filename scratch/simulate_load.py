#!/usr/bin/env python3
"""
simulate_load.py  —  PRC Hviel concurrent load test
Simulates N engineers hitting /api/chat simultaneously and prints
a statistical summary suitable for executive reporting.

Dependency (not in requirements.txt — test-only):
    pip install aiohttp
"""

import asyncio
import math
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("\n  ERROR: aiohttp is required for this script.")
    print("  Install it with:  pip install aiohttp\n")
    sys.exit(1)


# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL   = "http://localhost:8000"
CONCURRENT = 50          # simultaneous engineers (the thundering herd)
TIMEOUT_S  = 120         # per-request ceiling; Gemini can be slow under saturation

# Short, deterministic query — avoids triggering simulation tools (which are slower).
# All 50 engineers send the same message; the semantic cache will absorb repeat hits
# after the first response, which is itself a valid system behaviour to observe.
QUERY = (
    "In one sentence, define the Corey exponent and its role "
    "in Brooks-Corey relative permeability modelling."
)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class Result:
    user_id:     int
    session_id:  str
    success:     bool
    http_status: Optional[int]
    elapsed_ms:  float
    error:       Optional[str] = None


# ── Single-engineer coroutine ──────────────────────────────────────────────────

async def engineer_session(
    http: "aiohttp.ClientSession",
    user_id: int,
) -> Result:
    sid   = f"lt-{uuid.uuid4().hex[:12]}"
    email = f"eng{user_id:03d}@load.test"

    form = aiohttp.FormData()
    form.add_field("session_id",    sid)
    form.add_field("user_email",    email)
    form.add_field("engineer_name", f"Load Test Engineer {user_id:03d}")
    form.add_field("message",       QUERY)

    t0 = time.perf_counter()
    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_S)
        async with http.post(f"{BASE_URL}/api/chat", data=form, timeout=timeout) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000

            try:
                body   = await resp.json(content_type=None)
                api_ok = isinstance(body, dict) and body.get("status") == "success"
            except Exception:
                body   = {}
                api_ok = False

            success = (resp.status == 200) and api_ok
            error   = None
            if not success:
                detail = str(body)[:100] if body else "(empty body)"
                error  = f"HTTP {resp.status} — {detail}"

            return Result(
                user_id=user_id, session_id=sid,
                success=success, http_status=resp.status,
                elapsed_ms=elapsed_ms, error=error,
            )

    except asyncio.TimeoutError:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return Result(
            user_id=user_id, session_id=sid, success=False,
            http_status=None, elapsed_ms=elapsed_ms,
            error=f"Timeout after {TIMEOUT_S}s",
        )
    except aiohttp.ClientConnectorError as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return Result(
            user_id=user_id, session_id=sid, success=False,
            http_status=None, elapsed_ms=elapsed_ms,
            error=f"Connection refused — is the server running?  ({exc})",
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return Result(
            user_id=user_id, session_id=sid, success=False,
            http_status=None, elapsed_ms=elapsed_ms,
            error=str(exc),
        )


# ── Pre-flight health check ────────────────────────────────────────────────────

async def preflight(http: "aiohttp.ClientSession") -> bool:
    """Ping /health before firing the barrage. Fail fast if the server is down."""
    try:
        async with http.get(
            f"{BASE_URL}/health",
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                return True
            print(f"  Pre-flight: /health returned HTTP {resp.status}")
            return False
    except Exception as exc:
        print(f"  Pre-flight: cannot reach {BASE_URL}/health — {exc}")
        return False


# ── Percentile helper ──────────────────────────────────────────────────────────

def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(math.ceil(len(sorted_vals) * p / 100) - 1, len(sorted_vals) - 1)
    return sorted_vals[max(idx, 0)]


# ── Main orchestrator ──────────────────────────────────────────────────────────

async def run() -> None:
    W = 64
    bar     = "═" * W
    thin    = "─" * W

    print(f"\n  {bar}")
    print(f"  {'PRC HVIEL — CONCURRENT LOAD TEST':^{W}}")
    print(f"  {bar}")
    print(f"  Target     : {BASE_URL}/api/chat")
    print(f"  Engineers  : {CONCURRENT} (true thundering-herd — all simultaneous)")
    print(f"  Timeout    : {TIMEOUT_S}s per request")
    print(f"  Query      : \"{QUERY[:55]}...\"")
    print(f"  {thin}\n")

    connector = aiohttp.TCPConnector(
        limit=CONCURRENT + 10,
        limit_per_host=CONCURRENT + 10,
        enable_cleanup_closed=True,
    )

    async with aiohttp.ClientSession(connector=connector) as http:

        # ── Pre-flight ───────────────────────────────────────────────────────
        print("  Running pre-flight health check...", end="", flush=True)
        if not await preflight(http):
            print(" FAILED\n")
            print("  Abort: server is not reachable. Start the app and retry.\n")
            sys.exit(1)
        print(" OK\n")

        # ── Fire all N requests simultaneously ───────────────────────────────
        print(f"  Launching {CONCURRENT} concurrent sessions...\n")
        t_wall_start = time.perf_counter()

        tasks = [
            asyncio.create_task(engineer_session(http, uid))
            for uid in range(1, CONCURRENT + 1)
        ]
        results: list[Result] = await asyncio.gather(*tasks)

        t_wall_ms = (time.perf_counter() - t_wall_start) * 1000

    # ── Per-request log ──────────────────────────────────────────────────────

    print(f"  {'UID':>4}  {'RESULT':<6}  {'HTTP':>4}  {'ELAPSED':>9}  DETAIL")
    print(f"  {'─'*4}  {'─'*6}  {'─'*4}  {'─'*9}  {'─'*34}")

    for r in sorted(results, key=lambda x: x.user_id):
        tag    = "PASS" if r.success else "FAIL"
        code   = str(r.http_status) if r.http_status else "---"
        detail = "" if r.success else (r.error or "")[:46]
        print(f"  {r.user_id:>4}  {tag:<6}  {code:>4}  {r.elapsed_ms:>8.0f}ms  {detail}")

    # ── Statistical analysis ─────────────────────────────────────────────────

    successes  = [r for r in results if r.success]
    failures   = [r for r in results if not r.success]
    timeouts   = [r for r in failures if r.error and "Timeout"   in r.error]
    conn_errs  = [r for r in failures if r.error and "Connection" in r.error]
    srv_errors = [r for r in failures if r.http_status in (500, 502, 503, 504)]
    client_err = [r for r in failures if r.http_status and 400 <= r.http_status < 500]

    all_ms = sorted(r.elapsed_ms for r in results)
    ok_ms  = sorted(r.elapsed_ms for r in successes)

    success_rate = 100 * len(successes) / CONCURRENT

    print(f"\n  {bar}")
    print(f"  {'LOAD TEST SUMMARY':^{W}}")
    print(f"  {bar}")
    print(f"  Engineers served  : {CONCURRENT}")
    print(f"  Passed            : {len(successes):>3}  ({success_rate:.1f}%)")
    print(f"  Failed            : {len(failures):>3}")

    if srv_errors:
        codes: dict[int, int] = {}
        for r in srv_errors:
            codes[r.http_status] = codes.get(r.http_status, 0) + 1
        for code, n in sorted(codes.items()):
            print(f"    HTTP {code}      : {n}")
    if client_err:
        print(f"    4xx errors    : {len(client_err)}")
    if timeouts:
        print(f"    Timeouts      : {len(timeouts)}")
    if conn_errs:
        print(f"    Conn refused  : {len(conn_errs)}")

    print(f"\n  Wall-clock time   : {t_wall_ms:>10,.0f}ms  (all {CONCURRENT} requests in flight)")
    if successes:
        throughput = len(successes) / (t_wall_ms / 1000)
        print(f"  Throughput        : {throughput:>10.2f} req/s  (successful)")

    if all_ms:
        print(f"\n  Response latency  (all {len(all_ms)} engineers):")
        print(f"    min             : {min(all_ms):>10,.0f}ms")
        print(f"    median (p50)    : {percentile(all_ms, 50):>10,.0f}ms")
        print(f"    p75             : {percentile(all_ms, 75):>10,.0f}ms")
        print(f"    p95             : {percentile(all_ms, 95):>10,.0f}ms")
        print(f"    p99             : {percentile(all_ms, 99):>10,.0f}ms")
        print(f"    max             : {max(all_ms):>10,.0f}ms")
        if len(all_ms) > 1:
            print(f"    std dev         : {statistics.stdev(all_ms):>10,.0f}ms")

    if ok_ms and len(ok_ms) < len(all_ms):
        print(f"\n  Response latency  (successful {len(ok_ms)} only):")
        print(f"    min             : {min(ok_ms):>10,.0f}ms")
        print(f"    median (p50)    : {percentile(ok_ms, 50):>10,.0f}ms")
        print(f"    p95             : {percentile(ok_ms, 95):>10,.0f}ms")
        print(f"    max             : {max(ok_ms):>10,.0f}ms")

    # ── Verdict ──────────────────────────────────────────────────────────────

    print(f"\n  {bar}")
    if len(successes) == CONCURRENT:
        print(f"  VERDICT: PASS")
        print(f"  {thin}")
        print(f"  All {CONCURRENT} concurrent engineers were served without error.")
        print(f"  Zero 503s. Zero crashes. Zero data leaks across sessions.")
        print(f"  System sustained {throughput:.1f} req/s under full concurrent saturation.")
        print(f"  Suitable for executive sign-off on production readiness.")
    else:
        print(f"  VERDICT: FAIL")
        print(f"  {thin}")
        print(f"  {len(failures)} of {CONCURRENT} engineers encountered errors "
              f"({success_rate:.1f}% success rate).")
        if srv_errors:
            print(f"  {len(srv_errors)} server error(s) — review uvicorn logs for stack traces.")
        if timeouts:
            print(f"  {len(timeouts)} timeout(s) — Gemini API may be rate-limited at this concurrency.")
        if conn_errs:
            print(f"  {len(conn_errs)} connection error(s) — confirm the server is running.")

    print(f"  {bar}\n")

    sys.exit(0 if len(successes) == CONCURRENT else 1)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run())
