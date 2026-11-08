import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("rc", Path(__file__).parent / "report-coverage.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def summ(lc, lt, fc, ft, bc=0, bt=0):
    return {"lines": {"count": lt, "covered": lc, "percent": 0},
            "functions": {"count": ft, "covered": fc, "percent": 0},
            "regions": {"count": 9, "covered": 9, "percent": 100},
            "branches": {"count": bt, "covered": bc, "percent": 0}}


LLVM = {"type": "llvm.coverage.json.export", "version": "2.0.1", "data": [{
    "files": [
        {"filename": "/w/crates/a/src/lib.rs", "summary": summ(8, 10, 1, 2)},
        {"filename": "/w/crates/a/src/x.rs", "summary": summ(1, 5, 0, 1)},
        {"filename": "/w/crates/a-extra/src/lib.rs", "summary": summ(3, 3, 1, 1)},
        {"filename": "/w/crates/a/tests/t.rs", "summary": summ(2, 2, 1, 1)},
        {"filename": "/w/other/z.rs", "summary": summ(9, 9, 9, 9)}],
    "totals": summ(23, 29, 12, 14)}]}
PKGS = [("a", "/w/crates/a"), ("a-extra", "/w/crates/a-extra")]


class T(unittest.TestCase):
    def test_convert(self):
        r = m.convert(LLVM, PKGS, "sha", "rustc 1", "http://run", "cargo-llvm-cov 0.6")
        self.assertEqual(r["totals"], {"lines": {"covered": 23, "total": 29},
                                       "functions": {"covered": 12, "total": 14}})
        self.assertEqual(sorted(r["units"]), ["a", "a-extra"])
        self.assertEqual(r["units"]["a"]["lines"], {"covered": 11, "total": 17})
        self.assertEqual(r["units"]["a"]["functions"], {"covered": 2, "total": 4})
        self.assertNotIn("branches", r["units"]["a"])
        self.assertEqual((r["format"], r["commit"], r["tool"]), (1, "sha", "cargo-llvm-cov 0.6"))

    def test_branches_when_present(self):
        l = {"data": [{"files": [{"filename": "/w/crates/a/src/lib.rs", "summary": summ(1, 1, 1, 1, 2, 4)}],
                       "totals": summ(1, 1, 1, 1, 2, 4)}]}
        r = m.convert(l, PKGS, None, "", None, "")
        self.assertEqual(r["totals"]["branches"], {"covered": 2, "total": 4})
        self.assertEqual(r["units"]["a"]["branches"], {"covered": 2, "total": 4})


if __name__ == "__main__":
    unittest.main()
