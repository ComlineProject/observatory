import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("publish_report", Path(__file__).parent / "publish-report.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **m.IDENTITY})


class T(unittest.TestCase):
    """The publish commit names the branch the report was measured on, which
    is `master` in core, generation and language-server: never a fixed
    `main` (core's reports were labelled `main@…` before this)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        sh("git", "init", "-q", "-b", "master", cwd=self.repo)
        sh("git", "commit", "-q", "--allow-empty", "-m", "c", cwd=self.repo)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True,
                                text=True, check=True).stdout.strip()
        self.report = self.repo / "core.fuzz.json"
        self.report.write_text(json.dumps({"commit": commit}))
        self.commit = commit
        self.old = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def message(self, env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            commit, published = m.build(None, [self.report], None)
        self.assertEqual(published, ["core.fuzz.json"])
        return m.git("log", "-1", "--format=%s", commit).stdout.strip()

    def test_the_workflow_branch_names_the_commit(self):
        subject = self.message({"GITHUB_REF": "refs/heads/master", "GITHUB_REF_NAME": "master"})
        self.assertEqual(subject, f"Publish core.fuzz.json for master@{self.commit[:12]}")

    def test_a_local_run_names_the_checkout_branch(self):
        subject = self.message({})
        self.assertEqual(subject, f"Publish core.fuzz.json for master@{self.commit[:12]}")

    def test_a_pull_request_ref_falls_back_to_the_checkout(self):
        sh("git", "checkout", "-q", "--detach", cwd=self.repo)
        subject = self.message({"GITHUB_REF": "refs/pull/7/merge", "GITHUB_REF_NAME": "7/merge"})
        self.assertEqual(subject, f"Publish core.fuzz.json for HEAD@{self.commit[:12]}")


if __name__ == "__main__":
    unittest.main()
