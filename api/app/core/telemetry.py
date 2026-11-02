"""In-process counters for the status page and /metrics.

Everything here lives in memory and starts from zero when the process restarts, so a dashboard
should read it as "since the last start" (the `uptime_seconds` field says how long that is).
With several workers each one has its own counters.
"""

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class ProviderStats:
    ok: int = 0
    error: int = 0
    seconds: float = 0.0
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None


class Telemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = time.time()
            self.requests_by_status: dict[str, int] = {}
            self.request_seconds = 0.0
            self.requests_total = 0
            self.providers: dict[tuple[str, str], ProviderStats] = {}

    def request(self, status_code: int, seconds: float) -> None:
        with self._lock:
            key = f"{status_code // 100}xx"
            self.requests_by_status[key] = self.requests_by_status.get(key, 0) + 1
            self.requests_total += 1
            self.request_seconds += seconds

    def provider_call(self, provider: str, operation: str, ok: bool, seconds: float) -> None:
        """Record one call to a provider; `operation` is complete, stream or embed."""
        with self._lock:
            stats = self.providers.setdefault((provider, operation), ProviderStats())
            stats.seconds += seconds
            if ok:
                stats.ok += 1
                stats.last_success_at = datetime.now(UTC)
            else:
                stats.error += 1
                stats.last_error_at = datetime.now(UTC)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "requests_by_status": dict(self.requests_by_status),
                "request_seconds": self.request_seconds,
                "providers": {key: ProviderStats(**vars(s)) for key, s in self.providers.items()},
            }


telemetry = Telemetry()
