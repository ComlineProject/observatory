import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("report_size", Path(__file__).parent / "report-size.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class T(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f"{d}/t")
            Path(f"{d}/t/a.so").write_bytes(b"x" * 5000)
            Path(f"{d}/t/b-123.wasm").write_bytes(b"\0" * 10)
            old = os.getcwd()
            os.chdir(d)
            try:
                arts = m.parse_artifacts("ffi/cdylib=t/a.so\n\n# c\nffi/wasm=t/b-*.wasm\n")
                rep = m.build(arts, "abc", "http://run", "")
                with self.assertRaises(SystemExit):
                    m.parse_artifacts("x=t/*")
                with self.assertRaises(SystemExit):
                    m.parse_artifacts("x=t/nope")
            finally:
                os.chdir(old)
        self.assertEqual(rep["artifacts"]["ffi/cdylib"]["bytes"], 5000)
        self.assertLess(rep["artifacts"]["ffi/cdylib"]["gzip_bytes"], 100)
        self.assertEqual(rep["artifacts"]["ffi/wasm"]["bytes"], 10)
        self.assertEqual((rep["format"], rep["commit"], rep["toolchain"]), (1, "abc", None))
        json.dumps(rep)


if __name__ == "__main__":
    unittest.main()
