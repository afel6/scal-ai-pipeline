"""One retry budget per chat request (D3.3).

Bounded attempts AND bounded wall clock, the wall clock being the outer
guarantee: on a single local model server one stuck request holds the server
while every other agent — the supervisor mid-delegation included — queues
behind it, so the budget is sized for that box, not for a cloud endpoint with
parallel capacity.

    LLM_MAX_ATTEMPTS      FAILED provider calls tolerated per request (default 2);
                          successful turns of a multi-turn conversation are not attempts
    LLM_MAX_WALL_SECONDS  wall-clock seconds per request    (default 300)

The next attempt's HTTP timeout is capped to what is left of the wall clock;
exhaustion ends the request with a plain statement of the facts and nothing
invented in place of an answer.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Mapping, Optional

DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_MAX_WALL_SECONDS = 300.0

_now: Callable[[], float] = time.monotonic          # module-level so tests can substitute a fake clock


class BudgetExhausted(RuntimeError):
    """The request's attempt or wall-clock budget is spent."""


class RetryBudget:
    def __init__(self, max_attempts: Optional[int] = None, max_wall_seconds: Optional[float] = None,
                 clock: Optional[Callable[[], float]] = None) -> None:
        self.max_attempts = int(DEFAULT_MAX_ATTEMPTS if max_attempts is None else max_attempts)
        self.max_wall_seconds = float(DEFAULT_MAX_WALL_SECONDS if max_wall_seconds is None else max_wall_seconds)
        self._clock = clock
        self.started = self._tick()
        self.attempts = 0            # provider calls made
        self.failures = 0            # provider calls that failed — the bounded quantity
        self.last_error: str = ""

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "RetryBudget":
        e = os.environ if env is None else env
        try:
            attempts = int((e.get("LLM_MAX_ATTEMPTS") or "").strip() or DEFAULT_MAX_ATTEMPTS)
        except ValueError:
            attempts = DEFAULT_MAX_ATTEMPTS
        try:
            wall = float((e.get("LLM_MAX_WALL_SECONDS") or "").strip() or DEFAULT_MAX_WALL_SECONDS)
        except ValueError:
            wall = DEFAULT_MAX_WALL_SECONDS
        return cls(max(1, attempts), max(1.0, wall))

    def _tick(self) -> float:
        return (self._clock or _now)()

    def elapsed(self) -> float:
        return self._tick() - self.started

    def remaining(self) -> float:
        return self.max_wall_seconds - self.elapsed()

    def begin_attempt(self) -> int:
        """Reserve the next provider call or raise BudgetExhausted (never silently).

        Refused when the tolerated failures are spent or the wall clock is."""
        if self.failures >= self.max_attempts:
            raise BudgetExhausted(self.exhausted_message(self.last_error))
        if self.remaining() <= 0:
            raise BudgetExhausted(self.exhausted_message(self.last_error))
        self.attempts += 1
        return self.attempts

    def attempt_timeout(self, default: float) -> float:
        """HTTP timeout for the attempt about to start: the provider default,
        capped to the wall clock that is left (never below one second)."""
        return max(1.0, min(float(default), self.remaining()))

    def record_failure(self, error: str) -> None:
        self.failures += 1
        self.last_error = str(error)[:300]

    @property
    def spent(self) -> bool:
        return self.failures >= self.max_attempts or self.remaining() <= 1.0

    def exhausted_message(self, last_error: str = "") -> str:
        msg = (f"The model did not answer: {self.failures} attempt(s) failed in {self.elapsed():.0f} s "
               f"(budget: {self.max_attempts} attempts, {self.max_wall_seconds:.0f} s wall clock)")
        if last_error:
            msg += f" - last error: {last_error}"
        return msg + ". Nothing was substituted or invented."
