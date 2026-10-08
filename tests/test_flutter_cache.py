"""Exercise AAR reuse, invalidation, and failed publication without an Android SDK."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_android as build


class FlutterCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.work = self.root / "cache/integration"
        self.cache = self.root / "cache/flutter-aar"
        self.rapt = self.root / "rapt"
        self.write(self.source / "build_android.py", "builder version 1")
        self.write(self.source / "flutter/pubspec.yaml", "name: fixed_flet")
        self.write(self.source / "flutter/pubspec.lock", "locked packages")
        self.write(self.source / "flutter/lib/main.dart", "current host")
        self.write(self.source / "flutter/test/lifecycle_test.dart", "lifecycle checks")
        self.write(self.source / "runtime/flet_extensions.json", '["flet-audio"]')
        self.write(self.work / "flet/packages/flet/lib/flet.dart", "patched Flet")
        self.extension = self.work / "flet/sdk/python/packages/flet-audio/src/flutter/flet_audio"
        self.write(self.extension / "android/src/main/Audio.java", "audio plugin")
        self.write(self.rapt / "prototype/build.gradle", 'id "com.android.library" version "8.13.0"')
        self.write(self.rapt / "prototype/gradle/wrapper/gradle-wrapper.properties", "Gradle 8.14.3")
        self.inputs = SimpleNamespace(
            cache=self.cache.parent,
            components={name: {"sha256": name + "-archive", "patches": []}
                        for name in ("flutter", "flet", "renpy-rapt", "renpy")},
            sdk_root=lambda name: self.rapt if name == "renpy-rapt" else self.root / name,
        )
        self.calls = []
        self.fail = None
        self.toolchain = {"os": "linux", "arch": "x86_64", "java": "JDK 21", "android_packages": {}}
        self.addCleanup(patch.stopall)
        patch.object(build, "ROOT", self.source).start()
        patch.object(build, "flutter_toolchain", side_effect=lambda: self.toolchain).start()
        patch.object(build, "run", side_effect=self.run_flutter).start()
        # stage_flutter adds SDK paths; avoid leaking them into other tests.
        patch.dict(os.environ).start()

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def run_flutter(self, *command, cwd=None):
        args = tuple(str(part) for part in command[1:])
        self.calls.append(args)
        if args[0] == "create":
            module = Path(args[-1])
            self.write(module / ".android/settings.gradle",
                       'id "com.android.library" version "9.0.0" apply false')
            self.write(module / "lib/generated.dart", "template code")
        if args[:2] == ("build", "aar"):
            repo = cwd / "build/host/outputs/repo"
            self.write(repo / (build.FLUTTER_ARTIFACT + ".aar"), "Flutter debug AAR")
            self.write(repo / (build.FLUTTER_ARTIFACT + ".pom"), "Flutter debug dependencies")
            self.write(repo / "plugins/audio/audio_debug/1.0/audio_debug-1.0.aar", "audio AAR")
            self.write(repo / "plugins/audio/audio_debug/1.0/audio_debug-1.0.pom", "audio dependencies")
            self.write(repo / "plugins/audio/audio_debug/maven-metadata.xml", "audio metadata")
        if args[0] == self.fail:
            raise subprocess.CalledProcessError(1, command)

    def stage(self, force=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return build.stage_flutter(self.inputs, self.work, force_build=force)

    def aar_builds(self):
        return [command for command in self.calls if command[:2] == ("build", "aar")]

    def fingerprint(self):
        return build.flutter_cache_fingerprint(build.flutter_cache_inputs(self.inputs, self.work))

    def test_reuse_skips_only_aar_compilation_and_preserves_debug_options(self):
        first = self.stage()
        files = build.flutter_repo_fingerprints(first)
        second = self.stage()
        self.assertEqual(first, second)
        self.assertEqual(files, build.flutter_repo_fingerprints(second))
        self.assertEqual(self.aar_builds(), [("build", "aar", "--no-pub", "--no-profile", "--no-release")])
        for command in (("pub", "get"), ("analyze", "--no-pub", "lib", "test"), ("test", "--no-pub")):
            self.assertEqual(self.calls.count(command), 2)
        module = self.work / "flutter"
        self.assertFalse((module / "lib/generated.dart").exists())
        self.assertIn('version "8.13.0"', (module / ".android/settings.gradle").read_text())

    def test_deleted_sources_and_generated_paths_cannot_survive_rebuild(self):
        obsolete = self.source / "flutter/lib/obsolete.dart"
        self.write(obsolete, "old Dart source")
        self.stage()
        self.write(self.work / "flutter/.android/local.properties", "paths from another machine")
        obsolete.unlink()
        self.stage()
        self.assertEqual(len(self.aar_builds()), 2)
        self.assertFalse((self.work / "flutter/lib/obsolete.dart").exists())
        self.assertFalse((self.work / "flutter/.android/local.properties").exists())

    def test_every_compilation_input_invalidates_reuse(self):
        self.stage()
        original = self.fingerprint()
        paths = (
            self.source / "build_android.py",
            self.source / "flutter/pubspec.yaml",
            self.source / "flutter/pubspec.lock",
            self.source / "flutter/lib/main.dart",
            self.source / "flutter/test/lifecycle_test.dart",
            self.source / "runtime/flet_extensions.json",
            self.work / "flutter/pubspec.lock",
            self.work / "flet/packages/flet/lib/flet.dart",
            self.extension / "android/src/main/Audio.java",
            self.rapt / "prototype/build.gradle",
            self.rapt / "prototype/gradle/wrapper/gradle-wrapper.properties",
        )
        for path in paths:
            with self.subTest(path=path):
                data = path.read_bytes()
                path.write_bytes(data + b"\nchanged")
                self.assertNotEqual(original, self.fingerprint())
                path.write_bytes(data)
        added = self.source / "flutter/lib/added.dart"
        self.write(added, "new source")
        self.assertNotEqual(original, self.fingerprint())
        added.unlink()
        for name in ("flutter", "flet", "renpy-rapt"):
            with self.subTest(component=name):
                spec = self.inputs.components[name]
                archive = spec["sha256"]
                spec["sha256"] = "different archive"
                self.assertNotEqual(original, self.fingerprint())
                spec["sha256"] = archive
                spec["patches"] = [{"path": "new patch", "sha256": "new checksum"}]
                self.assertNotEqual(original, self.fingerprint())
                spec["patches"] = []
        for name, value in (("java", "JDK 22"), ("arch", "aarch64"), ("os", "different host"),
                            ("android_packages", {"ndk/source.properties": "new NDK"})):
            with self.subTest(toolchain=name):
                previous = self.toolchain[name]
                self.toolchain[name] = value
                self.assertNotEqual(original, self.fingerprint())
                self.toolchain[name] = previous

    def test_host_story_and_python_changes_reuse_the_aar(self):
        self.stage()
        self.write(self.source / "game/script.rpy", "new story")
        self.write(self.source / "runtime/story_ui.py", "new Python bridge")
        self.write(self.source / "android/app/build.gradle", "new host dependency")
        self.write(self.source / "android/app/src/main/assets/runner-startup.json",
                   '{"schema_version": 1, "mode": "app", "initial_route": "/records"}')
        self.write(self.work / "flet/sdk/python/packages/flet/src/flet/__init__.py", "new Python Flet")
        self.inputs.components["renpy"]["sha256"] = "new RenPy archive"
        self.stage()
        self.assertEqual(len(self.aar_builds()), 1)

    def test_plugin_build_outputs_do_not_replace_the_input_snapshot(self):
        pristine = self.root / "pristine-flet"
        shutil.copytree(self.work / "flet", pristine)
        original = self.run_flutter

        def generate_plugin_outputs(*command, cwd=None):
            original(*command, cwd=cwd)
            if command[1:3] == ("build", "aar"):
                self.write(self.extension / "android/build/generated.bin", "native build output")
                self.write(self.extension / "android/.gradle/build.lock", "Gradle bookkeeping")

        with patch.object(build, "run", side_effect=generate_plugin_outputs):
            self.stage()
        # main stages Flet from the verified SDK again on every invocation.
        shutil.rmtree(self.work / "flet")
        shutil.copytree(pristine, self.work / "flet")
        self.assertTrue(build.reusable_flutter_repo(self.cache, self.fingerprint()))
        self.stage()
        self.assertEqual(len(self.aar_builds()), 1)

    def test_android_packages_installed_during_build_are_part_of_the_receipt(self):
        original = self.run_flutter

        def install_toolchain(*command, cwd=None):
            original(*command, cwd=cwd)
            if command[1:3] == ("build", "aar"):
                self.toolchain["android_packages"] = {"cmake/source.properties": "installed CMake"}

        with patch.object(build, "run", side_effect=install_toolchain):
            self.stage()
        self.assertTrue(build.reusable_flutter_repo(self.cache, self.fingerprint()))
        self.stage()
        self.assertEqual(len(self.aar_builds()), 1)

    def test_bad_receipts_and_damaged_repositories_trigger_a_rebuild(self):
        artifact = self.cache / "repo" / (build.FLUTTER_ARTIFACT + ".aar")
        plugin = self.cache / "repo/plugins/audio/audio_debug/1.0/audio_debug-1.0.aar"
        marker = self.cache / "manifest.json"

        def edit_receipt(field, value):
            receipt = json.loads(marker.read_text())
            receipt[field] = value
            marker.write_text(json.dumps(receipt))

        def replace_directory(path):
            shutil.rmtree(path)
            path.write_text("interrupted restore")

        cases = {
            "missing receipt": lambda: marker.unlink(),
            "malformed receipt": lambda: marker.write_text("{unfinished"),
            "wrong receipt type": lambda: marker.write_text("[]"),
            "old schema": lambda: edit_receipt("schema_version", 0),
            "wrong inputs": lambda: edit_receipt("fingerprint", "old inputs"),
            "empty inventory": lambda: edit_receipt("files", {}),
            "missing AAR": lambda: artifact.unlink(),
            "missing POM": lambda: (self.cache / "repo" / (build.FLUTTER_ARTIFACT + ".pom")).unlink(),
            "changed AAR": lambda: artifact.write_text("corrupted bytes"),
            "empty AAR": lambda: artifact.write_bytes(b""),
            "missing plugin": lambda: plugin.unlink(),
            "changed plugin": lambda: plugin.write_text("corrupted plugin"),
            "extra file": lambda: self.write(self.cache / "repo/unrecorded.aar", "unexpected artifact"),
            "repo replaced by a file": lambda: replace_directory(self.cache / "repo"),
            "cache replaced by a file": lambda: replace_directory(self.cache),
        }
        self.stage()
        for name, damage in cases.items():
            with self.subTest(damage=name):
                count = len(self.aar_builds())
                damage()
                self.stage()
                self.assertEqual(len(self.aar_builds()), count + 1)
                self.assertTrue(build.reusable_flutter_repo(self.cache, self.fingerprint()))

    def test_symlinked_cache_files_or_directories_are_not_reused(self):
        self.stage()
        outside = self.root / "outside.aar"
        artifact = self.cache / "repo" / (build.FLUTTER_ARTIFACT + ".aar")
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        artifact.symlink_to(outside)
        self.stage()
        self.assertEqual(len(self.aar_builds()), 2)
        self.assertEqual(outside.read_text(), "Flutter debug AAR")
        saved = self.root / "saved-cache"
        self.cache.rename(saved)
        self.cache.symlink_to(saved, target_is_directory=True)
        self.stage()
        self.assertEqual(len(self.aar_builds()), 3)
        self.assertTrue((saved / "manifest.json").is_file())

    def test_force_rebuild_and_failure_cannot_leave_a_reusable_receipt(self):
        self.stage()
        self.stage(force=True)
        self.assertEqual(len(self.aar_builds()), 2)
        self.fail = "build"
        with self.assertRaises(subprocess.CalledProcessError):
            self.stage(force=True)
        self.assertFalse((self.cache / "manifest.json").exists())
        self.fail = None
        self.stage()
        self.assertEqual(len(self.aar_builds()), 4)
        self.assertTrue((self.cache / "manifest.json").is_file())

    def test_analysis_or_test_failure_blocks_reuse(self):
        self.stage()
        for command in ("analyze", "test"):
            with self.subTest(command=command):
                self.fail = command
                with self.assertRaises(subprocess.CalledProcessError):
                    self.stage()
                self.assertEqual(len(self.aar_builds()), 1)

    def test_incomplete_build_or_failed_copy_is_not_published(self):
        original = self.run_flutter

        def missing_artifact(*command, cwd=None):
            original(*command, cwd=cwd)
            if command[1:3] == ("build", "aar"):
                (cwd / "build/host/outputs/repo" / (build.FLUTTER_ARTIFACT + ".pom")).unlink()

        with patch.object(build, "run", side_effect=missing_artifact):
            with self.assertRaisesRegex(RuntimeError, "Missing Flutter debug Maven artifact"):
                self.stage()
        self.assertFalse(self.cache.exists())
        copy = shutil.copytree

        def failed_copy(source, target, *args, **options):
            if source.name == "repo":
                raise OSError("copy interrupted")
            return copy(source, target, *args, **options)

        with patch.object(build.shutil, "copytree", side_effect=failed_copy):
            with self.assertRaisesRegex(OSError, "copy interrupted"):
                self.stage()
        self.assertFalse(self.cache.exists())
        self.assertEqual(list(self.cache.parent.glob("flutter-aar-*")), [])

    def test_copy_corruption_is_detected_before_publication(self):
        copy = shutil.copytree

        def corrupt_copy(source, target, *args, **options):
            result = copy(source, target, *args, **options)
            if source.name == "repo":
                (target / (build.FLUTTER_ARTIFACT + ".aar")).write_bytes(b"bad copy")
            return result

        with patch.object(build.shutil, "copytree", side_effect=corrupt_copy):
            with self.assertRaisesRegex(RuntimeError, "changed while caching"):
                self.stage()
        self.assertFalse(self.cache.exists())


class FlutterToolchainTests(unittest.TestCase):
    def test_toolchain_uses_java_home_and_android_package_identities_without_absolute_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sdk = root / "android"
            jar = sdk / "platforms/android-36/android.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"Android API 36")
            for family, name in (("platforms", "android-36"), ("build-tools", "36.0.0"),
                                 ("ndk", "28.2.13676358"), ("cmake", "3.22.1")):
                properties = sdk / family / name / "source.properties"
                properties.parent.mkdir(parents=True, exist_ok=True)
                properties.write_text("Pkg.Revision=" + name)
            with patch.dict(os.environ, {"ANDROID_HOME": str(sdk), "JAVA_HOME": str(root / "jdk")}):
                with patch.object(build.subprocess, "check_output", return_value="JDK 21") as java:
                    identity = build.flutter_toolchain()
                    java.assert_called_once_with([str(root / "jdk/bin/java"), "-version"],
                                                 stderr=subprocess.STDOUT, text=True)
                    self.assertEqual(len(identity["android_packages"]), 5)
                    self.assertNotIn(str(root), json.dumps(identity))
                    jar.write_bytes(b"changed Android API")
                    self.assertNotEqual(identity, build.flutter_toolchain())


if __name__ == "__main__":
    unittest.main()
