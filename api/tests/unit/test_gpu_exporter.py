import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from scripts import gpu_exporter

SPARK = "0, NVIDIA GB10, 37, [N/A], 41, 4.2, 208, [N/A], [N/A], [N/A]"
DISCRETE = '1, RTX "X", 90, 55, 80, 250.5, 1800, 9000, 1024, 24576'


def reading(*lines):
    return subprocess.CompletedProcess([], 0, stdout="\n".join(lines) + "\n")


class TestQuery(unittest.TestCase):
    def test_parses_one_row_per_gpu_and_skips_malformed_lines(self):
        with patch("subprocess.run", return_value=reading(SPARK, "garbage", DISCRETE)) as run:
            rows = gpu_exporter.query_gpus()

        self.assertEqual([r["index"] for r in rows], ["0", "1"])
        self.assertEqual(rows[0]["utilization.gpu"], "37")
        self.assertIn("--query-gpu=index,name,utilization.gpu", run.call_args.args[0][1])

    def test_numbers_and_missing_readings(self):
        self.assertEqual(gpu_exporter.to_number("12.5"), 12.5)
        self.assertIsNone(gpu_exporter.to_number("[N/A]"))
        self.assertIsNone(gpu_exporter.to_number("[Not Supported]"))


class TestRender(unittest.TestCase):
    def rows(self, *lines):
        with patch("subprocess.run", return_value=reading(*lines)):
            return gpu_exporter.query_gpus()

    def test_unified_memory_gpu_has_no_memory_series(self):
        text = gpu_exporter.render(self.rows(SPARK))

        self.assertIn("gpu_up 1", text)
        self.assertIn('gpu_utilization_percent{gpu="0",name="NVIDIA GB10"} 37', text)
        self.assertIn('gpu_temperature_celsius{gpu="0",name="NVIDIA GB10"} 41', text)
        self.assertIn('gpu_power_watts{gpu="0",name="NVIDIA GB10"} 4.2', text)
        self.assertNotIn("gpu_memory_used_bytes", text)
        self.assertNotIn("gpu_clock_memory_mhz", text)
        self.assertNotIn("N/A", text)

    def test_memory_is_reported_in_bytes_and_names_are_escaped(self):
        text = gpu_exporter.render(self.rows(DISCRETE))

        self.assertIn('gpu_memory_used_bytes{gpu="1",name="RTX \\"X\\""} 1.07374e+09', text)
        self.assertIn("gpu_memory_total_bytes", text)

    def test_a_failed_query_reports_gpu_down_and_nothing_else(self):
        self.assertEqual(gpu_exporter.render(None).splitlines()[2], "gpu_up 0")
        self.assertNotIn("gpu_utilization", gpu_exporter.render(None))


class TestServer(unittest.TestCase):
    def serve(self, reader):
        server = gpu_exporter.make_server("127.0.0.1", 0, reader)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_serves_metrics_and_404s_elsewhere(self):
        with patch("subprocess.run", return_value=reading(SPARK)):
            base = self.serve(gpu_exporter.Reader())
            with urllib.request.urlopen(base + "/metrics?x=1") as response:  # noqa: S310
                body = response.read().decode()
                content_type = response.headers["Content-Type"]
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "/other")  # noqa: S310

        self.assertIn("gpu_up 1", body)
        self.assertTrue(content_type.startswith("text/plain"))
        self.assertEqual(caught.exception.code, 404)

    def test_nvidia_smi_is_called_once_per_cache_window(self):
        reader = gpu_exporter.Reader()
        with patch("subprocess.run", return_value=reading(SPARK)) as run:
            reader.text()
            reader.text()
            self.assertEqual(run.call_count, 1)
            reader._at -= 5
            reader.text()
            self.assertEqual(run.call_count, 2)

    def test_a_missing_nvidia_smi_means_gpu_down(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            text = gpu_exporter.Reader().text()

        self.assertIn("gpu_up 0", text)


if __name__ == "__main__":
    unittest.main()
