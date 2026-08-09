"""A per-caller ceiling on requests that cost money.

Distinct from :class:`services.auth.LoginThrottle`, which counts *failures* and locks
an identity out after too many. This counts *successes* — every AI request reaches a
provider and is billed whether or not it goes well, so the thing to bound is the call,
not the mistake. One class cannot be both without becoming a configuration exercise.

In memory, for the same reason and with the same limit as the sign-in throttle: this
is a single-process, self-hosted application, the counters reset on restart, and if a
second process ever appears this is one of the two things that must move. See
``docs/DECISIONS.md``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from notenverwaltung.exceptions import GradeBookError


class QuotaExceededError(GradeBookError):
    """Raised when a caller has spent their allowance of billable calls.

    A different code from the provider's own 429 (``AI_RATE_LIMITED``) on purpose:
    one says this installation stopped you, the other says the vendor did, and the
    only useful answer differs. Ours resets on a schedule we can state.
    """

    code = "AI_QUOTA_EXCEEDED"
    http_status = 429


@dataclass
class _Window:
    """One caller's usage inside the current window."""

    started: float = field(default_factory=time.monotonic)
    count: int = 0


class CallQuota:
    """How many billable calls one caller may make per hour.

    A fixed window rather than a sliding one. A sliding window means keeping every
    timestamp per caller and pruning them on each request; a fixed window is a counter
    and a start time. The cost is that a caller can spend twice the limit across a
    window boundary, which for a spending cap on a school's own staff is a bound worth
    having rather than a hole worth closing.
    """

    def __init__(self, max_calls: int, window_seconds: int = 3600) -> None:
        """Configure the quota.

        Args:
            max_calls: Calls allowed per window. Zero or less disables the feature
                entirely rather than allowing everything — a limit of nothing is a
                clearer way to turn AI off than an unbounded one is to leave it on.
            window_seconds: Length of the window.
        """
        self._max = max_calls
        self._window = window_seconds
        self._callers: dict[str, _Window] = {}

    def check(self, key: str) -> None:
        """Count one call against a caller's allowance.

        Args:
            key: Who is calling — an account id, not an address. The bill follows the
                account, and an address is shared by everyone behind one router.

        Raises:
            QuotaExceededError: If the allowance is spent. Carries the seconds until
                the window resets, so the client can say when rather than that.
        """
        now = time.monotonic()
        window = self._callers.get(key)
        if window is None or now - window.started >= self._window:
            window = _Window(started=now)
            self._callers[key] = window

        if window.count >= self._max:
            raise QuotaExceededError(
                "Too many AI requests.",
                retry_after_seconds=int(self._window - (now - window.started)) + 1,
            )
        window.count += 1
