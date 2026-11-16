"""Who may call the server, and how often.

Each installation of the app registers once and gets a token. The token is the
device id signed with the server's secret, so the server keeps no database of
devices. Limits are counted per device and for the whole service, which puts a
ceiling on what a leaked app key can cost.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque


def new_device_id() -> str:
    return secrets.token_urlsafe(12)


def sign(device_id: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), device_id.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{device_id}.{mac}"


def verify(token: str, secret: str) -> str | None:
    """Return the device id if the token is genuine."""
    device_id, _, mac = token.partition(".")
    if not device_id or not mac:
        return None
    expected = sign(device_id, secret).partition(".")[2]
    return device_id if hmac.compare_digest(mac, expected) else None


class LimitExceeded(Exception):
    def __init__(self, scope: str, retry_after: int):
        super().__init__(scope)
        self.scope = scope
        self.retry_after = retry_after


class Limiter:
    """Sliding-window counters, kept in memory (they reset when the server restarts)."""

    HOUR = 3600
    DAY = 86400

    def __init__(self, per_device_hourly: int, per_device_daily: int, global_daily: int, clock=time.monotonic):
        self.per_device_hourly = per_device_hourly
        self.per_device_daily = per_device_daily
        self.global_daily = global_daily
        self._clock = clock
        self._device: dict[str, deque[float]] = defaultdict(deque)
        self._all: deque[float] = deque()

    def _trim(self, events: deque[float], window: float, now: float) -> None:
        while events and now - events[0] >= window:
            events.popleft()

    def check(self, device_id: str, cost: int = 1) -> None:
        """Raise LimitExceeded if `cost` more generations would go over a limit."""
        now = self._clock()
        events = self._device[device_id]
        self._trim(events, self.DAY, now)
        self._trim(self._all, self.DAY, now)

        last_hour = [t for t in events if now - t < self.HOUR]
        if len(last_hour) + cost > self.per_device_hourly:
            raise LimitExceeded("device_hourly", int(self.HOUR - (now - last_hour[0])) + 1 if last_hour else self.HOUR)
        if len(events) + cost > self.per_device_daily:
            raise LimitExceeded("device_daily", int(self.DAY - (now - events[0])) + 1 if events else self.DAY)
        if len(self._all) + cost > self.global_daily:
            raise LimitExceeded("service_daily", int(self.DAY - (now - self._all[0])) + 1 if self._all else self.DAY)

    def record(self, device_id: str, cost: int = 1) -> None:
        """Count generations that actually ran (failed ones are not counted)."""
        now = self._clock()
        for _ in range(cost):
            self._device[device_id].append(now)
            self._all.append(now)

    def remaining(self, device_id: str) -> dict[str, int]:
        now = self._clock()
        events = self._device[device_id]
        self._trim(events, self.DAY, now)
        hour = sum(1 for t in events if now - t < self.HOUR)
        return {"hour": max(0, self.per_device_hourly - hour), "day": max(0, self.per_device_daily - len(events))}
