"""Release cache publication must validate release artifacts, never debug output."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_android as build
from scripts import ci_flutter_cache as ci


class ReleaseCICacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.cache = self.root / "flutter-aar-release"
        self.fingerprint = build.flutter_cache_fingerprint({"build_type": "release"})
        self.artifact = build.FLUTTER_ARTIFACT.replace("flutter_debug", "flutter_release")
        for suffix in (".aar", ".pom"):
            path = self.repo / (self.artifact + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"release artifact")

    def command(self, phase, build_type="release"):
        output = io.StringIO()
        with patch("sys.argv", ["ci_flutter_cache.py", phase, "--cache-dir", str(self.root),
                                "--build-type", build_type]), contextlib.redirect_stdout(output):
            ci.main()
        return output.getvalue().strip()

    def publish(self):
        build.cache_flutter_repo(self.repo, self.cache, self.fingerprint, build_type="release")

    def test_release_publication_and_warm_receipts_are_separate_from_debug(self):
        self.assertEqual(self.command("candidate"), "receipt=")
        self.publish()
        receipt = self.command("publish")
        self.assertRegex(receipt, r"^receipt=[0-9a-f]{64}$")
        self.assertEqual(self.command("candidate"), receipt)
        self.assertEqual(self.command("candidate", "debug"), "receipt=")
        self.assertEqual(ci.verified_receipt(self.cache, "debug"), "")

    def test_corrupt_release_output_requires_repair_before_publication(self):
        self.publish()
        old = self.command("publish")
        (self.cache / "repo" / (self.artifact + ".aar")).write_bytes(b"corruption")
        self.assertEqual(self.command("candidate"), "receipt=")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            self.command("publish")
        self.assertEqual(failure.exception.code, 2)
        shutil.rmtree(self.cache)
        self.publish()
        self.assertEqual(self.command("publish"), old)

    def test_debug_artifacts_cannot_be_published_as_release(self):
        debug_repo = self.root / "debug-repo"
        for suffix in (".aar", ".pom"):
            path = debug_repo / (build.FLUTTER_ARTIFACT + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"debug artifact")
        build.cache_flutter_repo(debug_repo, self.cache, self.fingerprint)
        self.assertEqual(self.command("candidate"), "receipt=")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.command("publish")


if __name__ == "__main__":
    unittest.main()
