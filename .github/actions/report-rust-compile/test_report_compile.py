import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("rc", Path(__file__).parent / "report-compile.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

HTML = """<script>
const UNIT_DATA = [
  {"i": 0, "name": "serde", "version": "1", "mode": "todo", "start": 0.1, "duration": 4.0, "sections": [["a", {"start": 0}]]},
  {"i": 1, "name": "a", "version": "0.1.0", "mode": "run-custom-build", "start": 0.2, "duration": 0.5},
  {"i": 2, "name": "a", "version": "0.1.0", "mode": "todo", "start": 4.1, "duration": 2.004},
  {"i": 3, "name": "b", "version": "0.1.0", "mode": "todo", "start": 6.2, "duration": 1.5}
];
const CONCURRENCY_DATA = [
  {"t": 0}
];
</script>"""


class T(unittest.TestCase):
    def test_convert(self):
        r = m.convert(m.unit_data(HTML), {"a", "b"}, "sha", "rustc 1", None, "github-hosted", "release")
        self.assertEqual(r["units"], {"a": {"seconds": 2.5}, "b": {"seconds": 1.5}})
        self.assertEqual(r["total_seconds"], 7.7)
        self.assertEqual((r["format"], r["runner"], r["profile"]), (1, "github-hosted", "release"))

    def test_profile(self):
        self.assertEqual(m.profile_of("--workspace --release"), "release")
        self.assertEqual(m.profile_of("--profile=ci -p x"), "ci")
        self.assertEqual(m.profile_of("--workspace"), "dev")

    def test_missing(self):
        with self.assertRaises(SystemExit):
            m.unit_data("<html></html>")


if __name__ == "__main__":
    unittest.main()
