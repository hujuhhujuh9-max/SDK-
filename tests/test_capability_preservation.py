"""Catch omitted upstream declarations and corrupt or incomplete APK packages."""

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_android import ROOT, check_android_capabilities, package_fingerprints
from scripts.device_smoke import check_packaged_components


class CapabilityPreservationTests(unittest.TestCase):
    def manifest_fixture(self, root):
        original = ROOT / "android/app/src/main/AndroidManifest.xml"
        upstream = root / "client/android/app/src/main/AndroidManifest.xml"
        upstream.parent.mkdir(parents=True)
        upstream.write_bytes(original.read_bytes())
        target = root / "host.xml"
        target.write_bytes(original.read_bytes())
        return target

    def test_missing_permission_or_provider_stops_assembly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.manifest_fixture(root)
            check_android_capabilities(root, target)
            original = target.read_text()
            for declaration in ('    <uses-permission android:name="android.permission.WAKE_LOCK" />\n',
                                'android:name="androidx.core.content.FileProvider"'):
                target.write_text(original.replace(declaration, ""))
                with self.subTest(declaration=declaration), self.assertRaisesRegex(RuntimeError, "Missing upstream"):
                    check_android_capabilities(root, target)

    def test_optional_feature_cannot_exclude_upstream_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.manifest_fixture(root)
            target.write_text(target.read_text().replace(
                'android.hardware.touchscreen" android:required="false"',
                'android.hardware.touchscreen" android:required="true"'))
            with self.assertRaisesRegex(RuntimeError, "became required"):
                check_android_capabilities(root, target)

    def test_renderer_and_back_cannot_be_silently_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.manifest_fixture(root)
            target.write_text(target.read_text().replace(
                'enableOnBackInvokedCallback="true"', 'enableOnBackInvokedCallback="false"'))
            with self.assertRaisesRegex(RuntimeError, "back-gesture"):
                check_android_capabilities(root, target)

    def apk_fixture(self, files, expected):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as private:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                private.addfile(info, io.BytesIO(data))
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as apk:
            apk.writestr("assets/private.mp3", archive.getvalue())
            apk.writestr("assets/runner-capabilities.json", json.dumps({"python_files": expected}))
        result.seek(0)
        return zipfile.ZipFile(result)

    def test_final_apk_rejects_missing_or_changed_component_files(self):
        source = {"renpy/__init__.py": b"RenPy", "lib/python3.12/site-packages/flet/icons.json": b"icons"}
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in source.items()}
        with self.apk_fixture(source, expected) as apk:
            check_packaged_components(apk)
        for files in ({"renpy/__init__.py": b"RenPy"}, dict(source, **{"renpy/__init__.py": b"changed"})):
            with self.subTest(files=files), self.apk_fixture(files, expected) as apk:
                with self.assertRaises(AssertionError):
                    check_packaged_components(apk)

    def test_inventory_keeps_resources_and_stubs_without_bytecode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("__init__.py", "icons.json", "icons.pyi", "__pycache__/cached.pyc", "common/screen.rpy"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            self.assertEqual(set(package_fingerprints(root, "flet", exclude=("common",))),
                             {"flet/__init__.py", "flet/icons.json", "flet/icons.pyi"})


if __name__ == "__main__":
    unittest.main()
