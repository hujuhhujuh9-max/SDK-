"""Reject stale CI candidates and publish repairs without duplicating warm hits."""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_android as build
from scripts import ci_flutter_cache as ci


class FlutterCICacheTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.cache = self.root / "flutter-aar"
        self.repo = self.root / "built-repo"
        self.fingerprint = build.flutter_cache_fingerprint({"source": "original"})
        for path, contents in ((build.FLUTTER_ARTIFACT + ".aar", b"current Flutter AAR"),
                               (build.FLUTTER_ARTIFACT + ".pom", b"current dependencies"),
                               ("plugin/audio.aar", b"current plugin")):
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)

    def publish(self, fingerprint=None):
        if self.cache.exists():
            shutil.rmtree(self.cache)
        build.cache_flutter_repo(self.repo, self.cache, fingerprint or self.fingerprint)

    def command(self, phase):
        output = io.StringIO()
        with patch("sys.argv", ["ci_flutter_cache.py", phase, "--cache-dir", str(self.root)]), \
                contextlib.redirect_stdout(output):
            ci.main()
        return output.getvalue().strip()

    def test_cold_candidate_then_verified_output_requires_publication(self):
        self.assertEqual(self.command("candidate"), "receipt=")
        self.publish()
        self.assertRegex(self.command("publish"), r"^receipt=[0-9a-f]{64}$")

    def test_unchanged_valid_candidate_does_not_require_another_cache(self):
        self.publish()
        before = self.command("candidate")
        marker = self.cache / "manifest.json"
        # JSON formatting is not a change to the verified output or inputs.
        marker.write_text(json.dumps(json.loads(marker.read_text()), indent=4))
        self.assertEqual(before, self.command("publish"))

    def test_corrupt_exact_hit_is_republished_even_when_its_manifest_stays_identical(self):
        for filename in (build.FLUTTER_ARTIFACT + ".aar", "plugin/audio.aar"):
            with self.subTest(filename=filename):
                self.publish()
                marker = (self.cache / "manifest.json").read_bytes()
                original = self.command("candidate")
                (self.cache / "repo" / filename).write_bytes(b"damaged restored bytes")
                self.assertEqual((self.cache / "manifest.json").read_bytes(), marker)
                before = self.command("candidate")
                self.assertEqual(before, "receipt=")
                self.publish()
                self.assertEqual((self.cache / "manifest.json").read_bytes(), marker)
                after = self.command("publish")
                self.assertEqual(after, original)
                self.assertNotEqual(before, after)

    def test_changed_build_identity_requires_a_new_cache(self):
        self.publish()
        before = self.command("candidate")
        self.publish(build.flutter_cache_fingerprint({"source": "changed"}))
        self.assertNotEqual(before, self.command("publish"))

    def test_new_output_with_the_same_inputs_is_not_mistaken_for_an_unchanged_hit(self):
        self.publish()
        before = self.command("candidate")
        (self.repo / "plugin/audio.aar").write_bytes(b"rebuilt plugin bytes")
        self.publish()
        self.assertNotEqual(before, self.command("publish"))

    def test_missing_malformed_or_incomplete_output_cannot_be_published(self):
        cases = ("missing", "malformed", "wrong type", "old schema", "wrong fingerprint", "missing POM")
        for damage in cases:
            with self.subTest(damage=damage):
                self.publish()
                marker = self.cache / "manifest.json"
                if damage == "missing":
                    marker.unlink()
                elif damage == "malformed":
                    marker.write_text("{unfinished")
                elif damage == "wrong type":
                    marker.write_text("[]")
                elif damage == "missing POM":
                    (self.cache / "repo" / (build.FLUTTER_ARTIFACT + ".pom")).unlink()
                else:
                    receipt = json.loads(marker.read_text())
                    receipt["schema_version" if damage == "old schema" else "fingerprint"] = 0
                    marker.write_text(json.dumps(receipt))
                self.assertEqual(self.command("candidate"), "receipt=")
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                    self.command("publish")
                self.assertEqual(failure.exception.code, 2)

    def test_symlinked_cache_or_receipt_is_rejected_before_reading_outside_files(self):
        for linked in ("cache", "receipt"):
            with self.subTest(linked=linked):
                self.publish()
                marker = self.cache / "manifest.json"
                if linked == "receipt":
                    outside = self.root / "outside-manifest.json"
                    marker.rename(outside)
                    marker.symlink_to(outside)
                else:
                    outside = self.root / "outside-cache"
                    self.cache.rename(outside)
                    self.cache.symlink_to(outside, target_is_directory=True)
                with patch.object(Path, "read_text", side_effect=AssertionError("followed a symlink")):
                    self.assertEqual(ci.verified_receipt(self.cache), "")
                if self.cache.is_symlink():
                    self.cache.unlink()

    def test_installed_java_and_android_identity_changes_cache_selection(self):
        identity = {"os": "linux", "arch": "x86_64", "java": "JDK 21.0.12",
                    "android_packages": {"platforms/android-36/android.jar": "current"}}
        with patch.object(build, "flutter_toolchain", return_value=identity):
            original = self.command("toolchain")
            self.assertRegex(original, r"^fingerprint=[0-9a-f]{64}$")
            identity["java"] = "JDK 21.0.13"
            self.assertNotEqual(original, self.command("toolchain"))
            identity["java"] = "JDK 21.0.12"
            identity["android_packages"]["platforms/android-36/android.jar"] = "changed"
            self.assertNotEqual(original, self.command("toolchain"))


class FlutterCIWorkflowTests(unittest.TestCase):
    def setUp(self):
        workflow = (ci.ROOT / ".github/workflows/build-android.yml").read_text()
        self.steps = dict(re.findall(r"(?ms)^      - name: (.*?)\n(.*?)(?=^      - |\Z)", workflow))
        self.restore = self.steps["Restore Flutter AAR candidate"]
        self.save = self.steps["Cache verified Flutter AAR"]

    def render(self, expression, run_id, attempt, source="source", toolchain="toolchain"):
        values = {"runner.os": "Linux", "runner.arch": "X64", "github.run_id": str(run_id),
                  "github.run_attempt": str(attempt), "steps.flutter-toolchain.outputs.fingerprint": toolchain}
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}",
                      lambda match: source if match[1].startswith("hashFiles(") else values[match[1]], expression)

    def test_runs_and_attempts_can_publish_replacements_without_overwriting_old_keys(self):
        key = re.search(r"(?m)^          key: (.+)$", self.restore)[1]
        keys = [self.render(key, run, attempt) for run, attempt in ((10, 1), (11, 1), (11, 2))]
        self.assertEqual(len(set(keys)), 3)
        self.assertIn("key: ${{ steps.flutter-cache.outputs.cache-primary-key }}", self.save)
        self.assertNotIn("cache-matched-key", self.save)

    def test_fallback_retains_compatible_source_changes_but_isolates_toolchains(self):
        prefixes = re.search(r"(?ms)^          restore-keys: \|\n(.*)", self.restore)[1].splitlines()
        prefixes = [line.strip() for line in prefixes if line.strip()]
        self.assertEqual(len(prefixes), 2)
        key = re.search(r"(?m)^          key: (.+)$", self.restore)[1]
        previous = self.render(key, 10, 1, source="original")
        current = [self.render(prefix, 11, 1, source="changed") for prefix in prefixes]
        self.assertFalse(previous.startswith(current[0]))
        self.assertTrue(previous.startswith(current[1]))
        other_toolchain = [self.render(prefix, 11, 1, source="changed", toolchain="different")
                           for prefix in prefixes]
        self.assertFalse(any(previous.startswith(prefix) for prefix in other_toolchain))

    def test_publication_uses_verified_before_after_state_instead_of_github_hit_status(self):
        condition = re.search(r"(?m)^        if: (.+)$", self.save)[1]
        left, operator, right = re.fullmatch(r"(\S+) (==|!=) (.+)", condition).groups()
        for before, after, expected in (("", "repaired", True), ("old", "new", True),
                                        ("unchanged", "unchanged", False)):
            with self.subTest(before=before, after=after):
                values = {"steps.flutter-before.outputs.receipt": before,
                          "steps.flutter-after.outputs.receipt": after,
                          "steps.flutter-cache.outputs.cache-hit": "true"}
                actual_left = values[left]
                actual_right = right.strip("'") if right.startswith("'") else values[right]
                actual = actual_left == actual_right if operator == "==" else actual_left != actual_right
                self.assertEqual(actual, expected)
        names = list(self.steps)
        self.assertLess(names.index("Identify installed Flutter build toolchain"),
                        names.index("Restore Flutter AAR candidate"))
        self.assertLess(names.index("Restore Flutter AAR candidate"),
                        names.index("Record verified Flutter AAR candidate"))
        self.assertLess(names.index("Record verified Flutter AAR candidate"),
                        names.index("Test preparation and build the fixed runner"))
        self.assertLess(names.index("Verify warm Flutter output reuse"),
                        names.index("Verify Flutter AAR before publication"))
        self.assertLess(names.index("Verify Flutter AAR before publication"),
                        names.index("Cache verified Flutter AAR"))
        self.assertLess(names.index("Cache verified Flutter AAR"),
                        names.index("Prepare Flutter cache restoration check"))
        self.assertLess(names.index("Prepare Flutter cache restoration check"),
                        names.index("Restore published Flutter AAR"))
        self.assertLess(names.index("Restore published Flutter AAR"),
                        names.index("Verify published Flutter AAR restoration"))
        self.assertIn("test \"$RESTORED_EXACT_KEY\" = true", self.steps["Verify published Flutter AAR restoration"])
        self.assertIn('test "$restored_receipt" = "receipt=$EXPECTED_RECEIPT"',
                      self.steps["Verify published Flutter AAR restoration"])
        self.assertNotIn("always()", self.steps["Verify Flutter AAR before publication"])


if __name__ == "__main__":
    unittest.main()
