"""In-process counters for the status page and /metrics.

Everything here lives in memory and starts from zero when the process restarts, so a dashboard
should read it as "since the last start" (the `uptime_seconds` field says how long that is).
With several workers each one has its own counters.
"""

import bisect
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Upper bounds in seconds. They run from a cache hit to a slow local model.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

# Spans that are also timed as stages (see tracing.span).
STAGES = frozenset(
    {
        "chat.prepare",
        "rag.retrieve",
        "embed.query",
        "embed.batch",
        "vector.search",
        "llm.complete",
        "chat.persist",
    }
)

Labels = tuple[tuple[str, str], ...]


@dataclass
class Histogram:
    """Counts per bucket (not cumulative), plus the sum and number of observations."""

    counts: list[int] = field(default_factory=lambda: [0] * (len(BUCKETS) + 1))
    total: float = 0.0
    count: int = 0

    def observe(self, seconds: float) -> None:
        self.counts[bisect.bisect_left(BUCKETS, seconds)] += 1
        self.total += seconds
        self.count += 1

    def copy(self) -> "Histogram":
        return Histogram(list(self.counts), self.total, self.count)


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
            self.histograms: dict[str, dict[Labels, Histogram]] = {}
            self.tokens: dict[tuple[str, str, str], int] = {}
            self.in_flight = 0

    def observe(self, name: str, seconds: float, **labels: str) -> None:
        """Add one timing to the histogram `name` (series are told apart by their labels)."""
        key: Labels = tuple(sorted(labels.items()))
        with self._lock:
            self.histograms.setdefault(name, {}).setdefault(key, Histogram()).observe(seconds)

    def request(self, status_code: int, seconds: float, route: str = "unmatched") -> None:
        """Record one response. `route` is the path template, never the concrete URL."""
        status = f"{status_code // 100}xx"
        with self._lock:
            self.requests_by_status[status] = self.requests_by_status.get(status, 0) + 1
            self.requests_total += 1
            self.request_seconds += seconds
        self.observe("request_duration_seconds", seconds, route=route, status=status)

    def request_started(self) -> None:
        with self._lock:
            self.in_flight += 1

    def request_finished(self) -> None:
        with self._lock:
            self.in_flight -= 1

    def tokens_used(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            for direction, count in (("input", input_tokens), ("output", output_tokens)):
                key = (provider, model, direction)
                self.tokens[key] = self.tokens.get(key, 0) + count

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
        self.observe(
            "provider_call_duration_seconds",
            seconds,
            provider=provider,
            operation=operation,
            outcome="ok" if ok else "error",
        )

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
                "histograms": {
                    name: {labels: h.copy() for labels, h in series.items()}
                    for name, series in self.histograms.items()
                },
                "tokens": dict(self.tokens),
                "in_flight": self.in_flight,
            }


telemetry = Telemetry()
