"""Tests for the collector.  Run: python3 -m unittest discover -s collector"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import collect  # noqa: E402

TAG = r"^v(?P<version>\d+\.\d+\.\d+(?:[-+].*)?)$"


def git(cwd, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, env=env, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


def commit(cwd, files, msg, date):
    for rel, content in files.items():
        f = Path(cwd) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content if isinstance(content, str) else json.dumps(content))
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", msg, date=date)
    return git(cwd, "rev-parse", "HEAD")


def bench(commit_, **ir):
    return {"runtime": "rust", "commit": commit_, "toolchain": "rustc 1.0",
            "metric": "instructions", "benches": {k.replace("__", "/"): {"ir": v} for k, v in ir.items()}}


FEATURES = {"features": [{"id": "envelope", "title": "Envelope", "description": "d1"},
                         {"id": "handshake", "title": "Handshake", "description": "d2"}]}


class Fixture(unittest.TestCase):
    """A repo with main (tag v0.1.0, later commits) and reports (bench, fuzz,
    wire, a report measuring a missing commit), cloned so origin/* refs exist."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        w = root / "work"
        w.mkdir()
        git(w, "init", "-q", "-b", "main")
        c1 = commit(w, {"src.txt": "1", "features.json": FEATURES}, "c1", "2026-01-01T10:00:00+00:00")
        wire = lambda s: {"runtime": "rust", "support": s}  # noqa: E731
        c2 = commit(w, {"src.txt": "2", "wire.json": wire(
            {"envelope": {"state": "supported", "proven_by": ["b", "a"]}})}, "c2", "2026-01-02T10:00:00+00:00")
        git(w, "tag", "v0.1.0", date="2026-01-03T10:00:00+00:00")
        c3 = commit(w, {"src.txt": "3"}, "c3", "2026-01-04T10:00:00+00:00")
        c4 = commit(w, {"src.txt": "4"}, "c4", "2026-01-05T10:00:00+00:00")
        commit(w, {"wire.json": wire({"envelope": {"state": "partial", "proven_by": ["a"], "note": "n"},
                                      "handshake": {"state": "ignored", "failing": ["z", "y"]}})},
               "wire2", "2026-01-06T12:00:00+00:00")
        git(w, "checkout", "-q", "--orphan", "reports")
        git(w, "rm", "-rqf", ".")
        r1 = commit(w, {"rust.bench.json": bench(c1, a__b__16=10, a__b__256=20, solo=5)}, "r1", "2026-01-02T08:00:00+00:00")
        commit(w, {"rust.bench.json": bench(c2, a__b__16=11, a__b__256=21)}, "r2", "2026-01-03T08:00:00+00:00")
        commit(w, {"rust.bench.json": bench(c3, a__b__16=12, a__b__256=22, solo=6)}, "r3", "2026-01-04T08:00:00+00:00")
        commit(w, {"rust.bench.json": bench("0" * 40, a__b__16=13, a__b__256=23)}, "r4", "2026-01-05T08:00:00+00:00")
        commit(w, {"rust.bench.json": bench(c4, a__b__16=14, a__b__256=24, solo=7)}, "r5", "2026-01-06T08:00:00+00:00")
        commit(w, {"rust.fuzz.json": {
            "commit": c1, "toolchain": "nightly", "date": "2026-01-02T00:00:00Z", "run": "http://run/1",
            "targets": {"t1": {"seconds": 60, "executions": 100, "corpus": 5, "findings": 0},
                        "t2": {"error": "build failed"}},
            "proptest": {"cases": 1000, "properties": {"p_ok": "pass", "p_bad": "fail"}}}},
            "f1", "2026-01-02T09:00:00+00:00")
        git(w, "checkout", "-q", "main")
        cls.c = [c1, c2, c3, c4]
        cls.r1 = r1
        cls.clone = root / "clone"
        subprocess.run(["git", "clone", "-q", str(w), str(cls.clone)], check=True, capture_output=True)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sources(self, extra="", name="s.toml"):
        p = self.root / name
        p.write_text(f'''
[[repo]]
name = "r"
url = "{self.root / 'work'}"
default_branch = "main"
tag = '{TAG}'

[[source]]
id = "bench"
kind = "bench"
title = "Bench"
repo = "r"
branch = "reports"
path = "rust.bench.json"

[[source]]
id = "fuzz"
kind = "fuzz"
title = "Fuzz"
repo = "r"
branch = "reports"
path = "rust.fuzz.json"

[[source]]
id = "wire"
kind = "conformance"
matrix = "wire"
title = "Wire"
repo = "r"
branch = "main"
path = "wire.json"
features = {{ repo = "r", path = "features.json" }}

[[source]]
id = "gone"
kind = "bench"
title = "Gone"
repo = "r"
branch = "reports"
path = "nope.json"
{extra}
''')
        return str(p)

    def collect(self, out, extra_args=(), **kw):
        env = dict(SOURCE_DATE_EPOCH="1700000000")
        old = dict(os.environ)
        os.environ.update(env)
        try:
            return collect.main(["--sources", self.sources(**kw), "--out", str(out),
                                 "--local", f"r={self.clone}", *extra_args])
        finally:
            os.environ.clear()
            os.environ.update(old)

    def load(self, out, sid):
        out = Path(out)
        manifest = json.loads((out / "manifest.json").read_text())
        entry = next(s for s in manifest["sources"] if s["id"] == sid)
        if entry["status"] != "ok":
            return entry, None
        return entry, json.loads((out / entry["index"]).read_text())

    def chunk(self, out, rel):
        return json.loads((Path(out) / rel).read_text())


class RunTests(Fixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.out = cls.root / "out"
        assert collect.main(["--sources", str(Fixture.sources(cls, name="a.toml")), "--out", str(cls.out),
                             "--local", f"r={cls.clone}"]) == 0

    def test_bench_versions_cycles_labels(self):
        _, idx = self.load(self.out, "bench")
        vs = idx["versions"]
        self.assertEqual([v["label"] for v in vs],
                         ["0.1.0-dev.1", "0.1.0-dev.2", "unreleased-dev.1", "unreleased-dev.2", "unreleased-dev.3"])
        self.assertEqual([v["cycle"] for v in vs], ["0.1.0", "0.1.0", "unreleased", "unreleased", "unreleased"])
        self.assertEqual([v["commit"] for v in vs[:3]], self.c[:3])
        self.assertEqual(vs[3]["commit"], "0" * 40)  # missing commit is kept as reported
        self.assertEqual(vs[0]["id"], self.r1)
        self.assertEqual(vs[0]["date"], "2026-01-02T08:00:00Z")
        self.assertEqual(vs[0]["toolchain"], "rustc 1.0")
        self.assertIsNone(vs[0]["run"])
        self.assertEqual([v["date"] for v in vs], sorted(v["date"] for v in vs))

    def test_release_only_on_last_of_released_cycle(self):
        _, idx = self.load(self.out, "bench")
        self.assertEqual([v["release"] for v in idx["versions"]], [None, "0.1.0", None, None, None])
        rel = self.chunk(self.out, idx["releases"])
        self.assertEqual(rel["versions"], [1])
        self.assertEqual(len(rel["values"]), len(idx["metrics"]))

    def test_cycles_list(self):
        _, idx = self.load(self.out, "bench")
        self.assertEqual([c["id"] for c in idx["cycles"]], ["0.1.0", "unreleased"])
        self.assertEqual(idx["cycles"][0]["tag"], "v0.1.0")
        self.assertEqual(idx["cycles"][0]["date"], "2026-01-02T10:00:00Z")  # the tag commit's date
        self.assertIsNone(idx["cycles"][1]["tag"])
        self.assertIsNone(idx["cycles"][1]["date"])

    def test_chunks_align_with_nulls(self):
        _, idx = self.load(self.out, "bench")
        keys = [(m["key"], m["metric"]) for m in idx["metrics"]]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(keys, [("a/b/16", "instructions"), ("a/b/256", "instructions"), ("solo", "instructions")])
        c0 = self.chunk(self.out, idx["cycles"][0]["chunk"])
        self.assertEqual(c0["versions"], [0, 1])
        self.assertEqual(c0["values"], [[10, 11], [20, 21], [5, None]])
        c1 = self.chunk(self.out, idx["cycles"][1]["chunk"])
        self.assertEqual(c1["versions"], [2, 3, 4])
        self.assertEqual(c1["values"], [[12, 13, 14], [22, 23, 24], [6, None, 7]])

    def test_group_and_param(self):
        _, idx = self.load(self.out, "bench")
        m = {x["key"]: x for x in idx["metrics"]}
        self.assertEqual((m["a/b/16"]["group"], m["a/b/16"]["param"]), ("a/b", 16))
        self.assertEqual((m["solo"]["group"], m["solo"]["param"]), (None, None))
        self.assertEqual(m["solo"]["unit"], "instructions")
        self.assertEqual(m["solo"]["type"], "number")

    def test_bench_shard(self):
        _, idx = self.load(self.out, "bench")
        self.assertEqual(self.chunk(self.out, idx["versions"][0]["shard"]),
                         {"benches": {"a/b/16": {"instructions": 10}, "a/b/256": {"instructions": 20},
                                      "solo": {"instructions": 5}}})

    def test_missing_commit_warns(self):
        err = subprocess.run([sys.executable, str(Path(collect.__file__)), "--sources",
                              self.sources(name="w.toml"), "--out", str(self.root / "o2"),
                              "--local", f"r={self.clone}"], capture_output=True, text=True).stderr
        self.assertIn("not in r", err)
        self.assertIn("unpublished", err)

    def test_unpublished_path_missing(self):
        entry, idx = self.load(self.out, "gone")
        self.assertIsNone(idx)
        self.assertEqual(entry["status"], "unpublished")
        self.assertIn("path not found", entry["reason"])
        self.assertNotIn("index", entry)

    def test_manifest(self):
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["format"], 1)
        self.assertEqual(m["generated"], m["generated"])
        self.assertEqual([s["id"] for s in m["sources"]], ["bench", "fuzz", "wire", "gone"])
        e = m["sources"][0]
        self.assertEqual((e["kind"], e["repo"], e["matrix"], e["status"]), ("bench", "r", None, "ok"))
        self.assertRegex(e["index"], r"^sources/bench/index\.[0-9a-f]{12}\.json$")

    def test_hashed_names_stable_and_stale_removed(self):
        a, b = self.root / "ra", self.root / "rb"
        self.assertEqual(self.collect(a), 0)
        self.assertEqual(self.collect(b), 0)

        def snap(d):
            return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*") if p.is_file()}
        self.assertEqual(snap(a), snap(b))
        stale = a / "sources" / "bench" / "index.000000000000.json"
        stale.write_text("{}")
        self.assertEqual(self.collect(a), 0)
        self.assertFalse(stale.exists())
        self.assertEqual(snap(a), snap(b))

    def test_strict(self):
        self.assertEqual(self.collect(self.root / "rs", ["--strict"]), 1)

    def test_fuzz_normalisation(self):
        _, idx = self.load(self.out, "fuzz")
        rows = {(m["key"], m["metric"]): m for m in idx["metrics"]}
        self.assertEqual(set(rows), {
            ("t1", "executions"), ("t1", "corpus"), ("t1", "findings"), ("t1", "seconds"),
            ("t2", "executions"), ("t2", "corpus"), ("t2", "findings"), ("t2", "seconds"),
            ("proptest/p_ok", "verdict"), ("proptest/p_bad", "verdict"), ("proptest", "cases")})
        self.assertEqual(rows[("proptest/p_ok", "verdict")]["type"], "verdict")
        self.assertEqual(rows[("proptest/p_ok", "verdict")]["group"], "proptest")
        self.assertIsNone(rows[("proptest", "cases")]["group"])
        order = [(m["key"], m["metric"]) for m in idx["metrics"]]
        vals = dict(zip(order, self.chunk(self.out, idx["cycles"][0]["chunk"])["values"]))
        self.assertEqual(vals[("t1", "executions")], [100])
        self.assertEqual(vals[("t2", "executions")], [None])  # error: a gap, never a zero
        self.assertEqual(vals[("t2", "seconds")], [None])
        self.assertEqual(vals[("proptest/p_ok", "verdict")], ["pass"])
        self.assertEqual(vals[("proptest/p_bad", "verdict")], ["fail"])
        self.assertEqual(vals[("proptest", "cases")], [1000])
        v = idx["versions"][0]
        self.assertEqual(v["run"], "http://run/1")
        shard = self.chunk(self.out, v["shard"])
        self.assertNotIn("commit", shard)
        self.assertNotIn("run", shard)
        self.assertEqual(shard["targets"]["t2"], {"error": "build failed"})

    def test_conformance_runtime_shape(self):
        _, idx = self.load(self.out, "wire")
        self.assertEqual([v["label"] for v in idx["versions"]], ["0.1.0-dev.1", "unreleased-dev.1"])
        self.assertEqual(idx["matrix"], "wire")
        self.assertEqual(idx["features"], {"envelope": {"title": "Envelope", "description": "d1"},
                                           "handshake": {"title": "Handshake", "description": "d2"}})
        self.assertEqual([m["key"] for m in idx["metrics"]], ["rust/envelope", "rust/handshake"])
        self.assertEqual(idx["metrics"][0]["type"], "state")
        self.assertEqual(idx["metrics"][0]["metric"], "state")
        self.assertEqual(idx["metrics"][0]["group"], "rust")
        c0 = self.chunk(self.out, idx["cycles"][0]["chunk"])
        self.assertEqual(c0["values"], [["supported"], [None]])
        shard0 = self.chunk(self.out, idx["versions"][0]["shard"])
        self.assertEqual(shard0, {"subjects": {"rust": {"envelope": {
            "state": "supported", "proven_by": ["a", "b"], "note": None, "tracking": None, "failing": None}}}})
        shard1 = self.chunk(self.out, idx["versions"][1]["shard"])
        self.assertEqual(shard1["subjects"]["rust"]["handshake"],
                         {"state": "ignored", "proven_by": None, "note": None, "tracking": None,
                          "failing": ["y", "z"]})


class NormaliseTests(unittest.TestCase):
    def test_bench_format2(self):
        n = collect.normalise_bench({"benches": {"x": {"wall": {"value": 5, "runner": "ci-a", "spread": 1}}}})
        self.assertEqual(n.rows, {("x", "wall@ci-a"): (5, "wall", "number")})
        self.assertEqual(n.shard, {"benches": {"x": {"wall@ci-a": 5}}})

    def test_bench_format2_without_runner(self):
        n = collect.normalise_bench({"benches": {"x": {
            "instructions": {"value": 9, "spread": 0}, "instructions-opt": {"value": 3, "runner": None}}}})
        self.assertEqual(n.rows, {("x", "instructions"): (9, "instructions", "number"),
                                  ("x", "instructions-opt"): (3, "instructions-opt", "number")})

    def test_bench_format1(self):
        n = collect.normalise_bench({"commit": "ab", "benches": {"x": {"ir": 7}}})
        self.assertEqual(n.rows, {("x", "instructions"): (7, "instructions", "number")})
        self.assertEqual(n.commit, "ab")

    def test_fuzz_error_target_is_all_nulls(self):
        n = collect.normalise_fuzz({"targets": {"t": {"error": "x", "executions": 5}}})
        self.assertEqual({k: v[0] for k, v in n.rows.items()},
                         {("t", "executions"): None, ("t", "corpus"): None,
                          ("t", "findings"): None, ("t", "seconds"): None})

    def test_proptest_verdicts(self):
        n = collect.normalise_fuzz({"proptest": {"cases": 9, "properties": {"a": "pass", "b": "fail", "c": "weird"}}})
        self.assertEqual({k: v[0] for k, v in n.rows.items()},
                         {("proptest/a", "verdict"): "pass", ("proptest/b", "verdict"): "fail",
                          ("proptest/c", "verdict"): None, ("proptest", "cases"): 9})

    def test_conformance_generators_shape(self):
        n = collect.normalise_conformance({
            "features": [{"id": "f"}],
            "generators": [
                {"name": "rust", "support": {"f": {"state": "supported", "proven_by": ["b", "a"], "since": "1"}}},
                {"name": "ts", "support": {"f": {"state": "bogus"}}}]})
        self.assertEqual({k: v[0] for k, v in n.rows.items()},
                         {("rust/f", "state"): "supported", ("ts/f", "state"): None})
        self.assertEqual(n.shard["subjects"]["rust"]["f"]["proven_by"], ["a", "b"])
        self.assertNotIn("since", n.shard["subjects"]["rust"]["f"])
        self.assertEqual(n.shard["subjects"]["ts"]["f"]["state"], None)

    def test_conformance_rejects_other_shapes(self):
        with self.assertRaises(ValueError):
            collect.normalise_conformance({"hello": 1})

    def test_split_key(self):
        self.assertEqual(collect.split_key("ffi/abi/enc/datagram@2/message/4096"),
                         ("ffi/abi/enc/datagram@2/message", 4096))
        self.assertEqual(collect.split_key("a/b"), ("a", None))
        self.assertEqual(collect.split_key("a/007"), ("a", None))
        self.assertEqual(collect.split_key("a"), (None, None))


class CacheModeTests(Fixture):
    def test_clone_into_cache_and_reuse(self):
        cache = self.root / "cache"
        argv = ["--sources", self.sources(name="c.toml"), "--out", str(self.root / "co"),
                "--cache", str(cache)]
        self.assertEqual(collect.main(argv), 0)
        _, idx = self.load(self.root / "co", "bench")
        self.assertEqual([v["label"] for v in idx["versions"]][:2], ["0.1.0-dev.1", "0.1.0-dev.2"])
        self.assertTrue((cache / "r").exists())
        self.assertEqual(collect.main(argv), 0)  # reuse

    def test_local_checkout_is_not_written(self):
        before = subprocess.run(["git", "-C", str(self.clone), "for-each-ref"], capture_output=True, text=True).stdout
        head = (self.clone / ".git" / "HEAD").read_text()
        self.assertEqual(self.collect(self.root / "ro"), 0)
        after = subprocess.run(["git", "-C", str(self.clone), "for-each-ref"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        self.assertEqual(head, (self.clone / ".git" / "HEAD").read_text())


class ConfigTests(unittest.TestCase):
    def test_bad_config_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.toml"
            p.write_text('[[source]]\nid = "Bad Id"\nkind = "bench"\ntitle = "t"\nrepo = "x"\nbranch = "b"\npath = "p"\n')
            self.assertEqual(collect.main(["--sources", str(p), "--out", str(Path(d) / "o")]), 2)


if __name__ == "__main__":
    unittest.main()
