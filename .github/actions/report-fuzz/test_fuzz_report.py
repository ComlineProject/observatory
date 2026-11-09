import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "fuzz-report.py"

SINGLE = """INFO: Seed: 1
#1000 DONE cov: 10 ft: 20 corp: 5/100b exec/s: 100 rss: 30Mb
Done 1000 runs in 10 second(s)
stat::number_of_executed_units: 1000
stat::average_exec_per_sec:     100
"""

# A fork-mode parent: no `stat::` lines of its own, but a crashed child's
# log echoed with its own, which must not win.
FORK = """#5000: cov: 10 ft: 20 corp: 5 exec/s: 500 oom/timeout/crash: 0/0/0 time: 10s job: 1 dft_time: 0
#9000: cov: 11 ft: 21 corp: 6 exec/s: 450 oom/timeout/crash: 0/0/0 time: 20s job: 2 dft_time: 0
stat::number_of_executed_units: 123
INFO: exiting: 0 time: 21s
"""


def run(*args):
    subprocess.run([sys.executable, str(SCRIPT), *args], check=True)


class T(unittest.TestCase):
    def target(self, d, name, log):
        Path(f"{d}/{name}.log").write_text(log)
        Path(f"{d}/corpus/{name}").mkdir(parents=True)
        Path(f"{d}/corpus/{name}/a").write_text("x")
        run("target", "--name", name, "--toolchain", "rustc 1.0", "--log", f"{d}/{name}.log",
            "--corpus", f"{d}/corpus/{name}", "--artifacts", f"{d}/none", "--wall-seconds", "99",
            "--out", f"{d}/stats/{name}.json")

    def test_single_fork_and_combine(self):
        with tempfile.TemporaryDirectory() as d:
            self.target(d, "one", SINGLE)
            self.target(d, "two", FORK)
            run("combine", "--commit", "abc", "--run", "http://run", "--fragments", f"{d}/stats",
                "--expect", "one", "two", "gone", "--report", f"{d}/r.json", "--markdown", f"{d}/r.md")
            rep = json.loads(Path(f"{d}/r.json").read_text())
        self.assertNotIn("runtime", rep)
        self.assertIsNone(rep["proptest"])
        self.assertEqual(rep["targets"]["one"], {"seconds": 10, "executions": 1000, "corpus": 1, "findings": 0})
        self.assertEqual(rep["targets"]["two"], {"seconds": 21, "executions": 9000, "corpus": 1, "findings": 0})
        self.assertIn("error", rep["targets"]["gone"])

    def test_subject(self):
        with tempfile.TemporaryDirectory() as d:
            self.target(d, "one", SINGLE)
            run("combine", "--commit", "abc", "--run", "r", "--fragments", f"{d}/stats",
                "--subject", "rust", "--report", f"{d}/r.json")
            self.assertEqual(json.loads(Path(f"{d}/r.json").read_text())["runtime"], "rust")


if __name__ == "__main__":
    unittest.main()
