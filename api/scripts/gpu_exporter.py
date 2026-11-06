"""Serve GPU numbers for Prometheus, read from `nvidia-smi` (no extra packages).

    cd api && uv run python -m scripts.gpu_exporter              # http://0.0.0.0:9835/metrics
    cd api && uv run python -m scripts.gpu_exporter --host 127.0.0.1 --port 9835

Run it on the machine that owns the GPU. Fields the driver does not report are left out; on
unified-memory systems (such as the DGX Spark) that means no memory figures, only utilization,
clocks, temperature and power. The output holds hardware numbers only.
"""

import argparse
import logging
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("gpu_exporter")

# nvidia-smi query field -> (metric name, help text, scale to the metric's unit)
FIELDS: dict[str, tuple[str, str, float]] = {
    "utilization.gpu": ("gpu_utilization_percent", "GPU busy time over the last sample.", 1),
    "utilization.memory": ("gpu_memory_utilization_percent", "Memory controller busy time.", 1),
    "temperature.gpu": ("gpu_temperature_celsius", "GPU temperature.", 1),
    "power.draw": ("gpu_power_watts", "Power draw.", 1),
    "clocks.sm": ("gpu_clock_sm_mhz", "Streaming multiprocessor clock.", 1),
    "clocks.mem": ("gpu_clock_memory_mhz", "Memory clock.", 1),
    "memory.used": ("gpu_memory_used_bytes", "Memory in use.", 1024 * 1024),
    "memory.total": ("gpu_memory_total_bytes", "Memory installed.", 1024 * 1024),
}
QUERY = ["index", "name", *FIELDS]
CACHE_SECONDS = 1.0


def query_gpus() -> list[dict[str, str]]:
    """One dict per GPU, keyed by query field. Raises if nvidia-smi is missing or fails."""
    command = [
        "nvidia-smi",
        f"--query-gpu={','.join(QUERY)}",
        "--format=csv,noheader,nounits",
    ]
    output = subprocess.run(command, capture_output=True, text=True, check=True, timeout=10).stdout
    rows = []
    for line in output.strip().splitlines():
        values = [v.strip() for v in line.split(",")]
        if len(values) == len(QUERY):
            rows.append(dict(zip(QUERY, values, strict=True)))
    return rows


def to_number(value: str) -> float | None:
    """A reading, or None for "[N/A]", "[Not Supported]" and anything else that is not a number."""
    try:
        return float(value)
    except ValueError:
        return None


def render(rows: list[dict[str, str]] | None) -> str:
    """Prometheus text for one reading; `None` means the query failed."""
    lines = ["# HELP gpu_up 1 when nvidia-smi answered.", "# TYPE gpu_up gauge"]
    lines.append(f"gpu_up {int(rows is not None)}")
    series: dict[str, list[str]] = {name: [] for name, _, _ in FIELDS.values()}
    for row in rows or []:
        name = row["name"].replace("\\", "\\\\").replace('"', '\\"')
        labels = f'{{gpu="{row["index"]}",name="{name}"}}'
        for field, (metric, _, scale) in FIELDS.items():
            number = to_number(row[field])
            if number is not None:
                series[metric].append(f"{metric}{labels} {number * scale:g}")
    for metric, help_text, _ in FIELDS.values():
        if series[metric]:
            lines += [f"# HELP {metric} {help_text}", f"# TYPE {metric} gauge", *series[metric]]
    return "\n".join(lines) + "\n"


class Reader:
    """Calls nvidia-smi at most once per CACHE_SECONDS, however many scrapers ask."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._at = 0.0
        self._text = ""

    def text(self) -> str:
        with self._lock:
            if time.monotonic() - self._at > CACHE_SECONDS or not self._text:
                try:
                    rows: list[dict[str, str]] | None = query_gpus()
                except (OSError, subprocess.SubprocessError):
                    logger.warning("nvidia-smi failed")
                    rows = None
                self._text = render(rows)
                self._at = time.monotonic()
            return self._text


def make_server(host: str, port: int, reader: Reader | None = None) -> ThreadingHTTPServer:
    source = reader or Reader()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] != "/metrics":
                self.send_error(404)
                return
            body = source.text().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover (starts a server)
    parser = argparse.ArgumentParser(description="Expose GPU metrics for Prometheus.")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on")
    parser.add_argument("--port", type=int, default=9835)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    server = make_server(args.host, args.port)
    logger.info("serving GPU metrics on http://%s:%d/metrics", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
