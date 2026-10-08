"""Reject incomplete ABI packages and changes to shared APK payloads."""

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.check_apk import SUPPORTED_ABIS, compare_apk_payloads, inspect_apk
from scripts.startup_config import STARTUP_ASSET, startup_config
from scripts.check_apk_artifact import verify_apk_receipt


class ApkPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.extensions = json.loads((Path(__file__).resolve().parents[1] /
                                      "runtime/flet_extensions.json").read_text())
        private = io.BytesIO()
        with tarfile.open(fileobj=private, mode="w:gz") as archive:
            data = b"retained Python package"
            member = tarfile.TarInfo("renpy/__init__.py")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        common = "assets/x-renpy/x-common/x-screen.rpy"
        startup = json.dumps(startup_config()).encode()
        self.files = {
            STARTUP_ASSET: startup,
            "assets/private.mp3": private.getvalue(),
            common: b"retained RenPy common resource",
            "assets/runner-capabilities.json": json.dumps({
                "startup_mode": "story",
                "startup_config_sha256": hashlib.sha256(startup).hexdigest(),
                "extensions": self.extensions,
                "python_files": {"renpy/__init__.py": hashlib.sha256(data).hexdigest()},
                "android_assets": {common: hashlib.sha256(b"retained RenPy common resource").hexdigest()},
            }).encode(),
            "classes.dex": b"shared Android integration",
            "AndroidManifest.xml": b"shared manifest",
            "META-INF/LICENSE.notice": b"retained third-party notice",
            "META-INF/MANIFEST.MF": b"first signature manifest",
            "META-INF/CERT.SF": b"first signature",
            "META-INF/CERT.RSA": b"first certificate",
        }
        for abi in SUPPORTED_ABIS:
            for library in ("librenpython.so", "libflutter.so"):
                self.files["lib/" + abi + "/" + library] = (abi + "/" + library).encode()

    def write_apk(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as apk:
            for filename, data in files.items():
                apk.writestr(filename, data)
        return path

    def variant_files(self):
        return {name: data for name, data in self.files.items()
                if not name.startswith(("lib/arm64-v8a/", "lib/armeabi-v7a/"))}

    def test_universal_and_x86_packages_retain_the_same_shared_payload(self):
        universal = self.write_apk("universal.apk", self.files)
        variant = self.write_apk("x86.apk", self.variant_files())
        full = inspect_apk(universal)
        selected = inspect_apk(variant, ("x86_64",))
        self.assertEqual(full["abis"], list(SUPPORTED_ABIS))
        self.assertEqual(selected["abis"], ["x86_64"])
        self.assertEqual(selected["startup_mode"], "story")
        self.assertEqual(selected["extensions"], self.extensions)
        self.assertEqual(selected["python_files_verified"], 1)
        self.assertEqual(selected["android_assets_verified"], 1)
        self.assertLess(selected["size_bytes"], full["size_bytes"])
        self.assertEqual(selected["sha256"], hashlib.sha256(variant.read_bytes()).hexdigest())
        self.assertGreater(compare_apk_payloads(universal, variant, ("x86_64",)), 0)

    def test_missing_inventory_cannot_skip_the_capability_suite(self):
        files = dict(self.files)
        del files["assets/runner-capabilities.json"]
        with self.assertRaisesRegex(RuntimeError, "Missing runner capability inventory"):
            inspect_apk(self.write_apk("missing.apk", files))

    def test_app_mode_is_verified_against_configuration_inventory_and_requested_mode(self):
        files = self.variant_files()
        files[STARTUP_ASSET] = json.dumps(startup_config("app")).encode()
        inventory = json.loads(files["assets/runner-capabilities.json"])
        inventory.update(startup_mode="app", startup_config_sha256=hashlib.sha256(
            files[STARTUP_ASSET]).hexdigest())
        files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
        path = self.write_apk("app.apk", files)
        self.assertEqual(inspect_apk(path, ("x86_64",), "app")["startup_mode"], "app")
        with self.assertRaisesRegex(RuntimeError, "Unexpected APK startup mode"):
            inspect_apk(path, ("x86_64",), "story")

    def test_missing_invalid_or_misreported_startup_cannot_pass_inventory(self):
        for data in (None, b"{}", b"[]", b'{"mode":"unknown"}',
                     json.dumps(dict(startup_config(), initial_route="/records")).encode(),
                     json.dumps(startup_config("app")).encode()):
            with self.subTest(config=data):
                files = dict(self.files)
                if data is None:
                    del files[STARTUP_ASSET]
                else:
                    files[STARTUP_ASSET] = data
                with self.assertRaisesRegex(RuntimeError, "startup configuration"):
                    inspect_apk(self.write_apk("bad-mode.apk", files))

    def test_inventory_mode_and_config_checksum_are_both_required(self):
        for key, value in (("startup_mode", "app"), ("startup_mode", None),
                           ("startup_config_sha256", "old-checksum")):
            with self.subTest(field=key):
                files = dict(self.files)
                inventory = json.loads(files["assets/runner-capabilities.json"])
                inventory[key] = value
                files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
                with self.assertRaisesRegex(RuntimeError, "differs from its inventory"):
                    inspect_apk(self.write_apk("bad-inventory.apk", files))

    def test_artifact_receipt_requires_actual_checksum_mode_source_and_abi(self):
        apk = self.write_apk("runner-debug-x86_64.apk", self.variant_files())
        report = inspect_apk(apk, ("x86_64",))
        receipt = {"source_sha": "a" * 40, "source_dirty": False, "startup_mode": "story",
                   "identical_shared_entries": 9, "apks": [report]}
        self.assertEqual(verify_apk_receipt(apk, receipt, "a" * 40, "story", ("x86_64",)), report)
        for key, value in (("source_sha", "b" * 40), ("source_dirty", True),
                           ("startup_mode", "app"), ("identical_shared_entries", 0),
                           ("apks", []), ("apks", [report, report]),
                           ("apks", [dict(report, sha256="b" * 64)]),
                           ("apks", [dict(report, size_bytes=1)])):
            with self.subTest(field=key), self.assertRaises(RuntimeError):
                verify_apk_receipt(apk, dict(receipt, **{key: value}), "a" * 40, "story", ("x86_64",))
        with self.assertRaisesRegex(RuntimeError, "Unexpected APK ABIs"):
            verify_apk_receipt(apk, receipt, "a" * 40, "story", SUPPORTED_ABIS)

    def test_missing_duplicate_or_substituted_extensions_are_rejected(self):
        for extensions in ([], self.extensions[:-1], [self.extensions[0]] * 19,
                           ["unexpected_extension", *self.extensions[1:]]):
            with self.subTest(extensions=extensions):
                files = dict(self.files)
                inventory = json.loads(files["assets/runner-capabilities.json"])
                inventory["extensions"] = extensions
                files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
                with self.assertRaisesRegex(RuntimeError, "all 19"):
                    inspect_apk(self.write_apk("extensions.apk", files))

    def test_missing_selected_native_runtime_is_rejected(self):
        files = self.variant_files()
        del files["lib/x86_64/libflutter.so"]
        with self.assertRaisesRegex(RuntimeError, "Missing runner native library"):
            inspect_apk(self.write_apk("missing-runtime.apk", files), ("x86_64",))

    def test_unexpected_native_architecture_is_rejected(self):
        files = dict(self.files, **{"lib/x86/libflutter.so": b"unsupported runtime"})
        with self.assertRaisesRegex(RuntimeError, "Unexpected APK ABIs"):
            inspect_apk(self.write_apk("unexpected-abi.apk", files))

    def test_device_abi_flag_must_match_the_apk_contents(self):
        universal = self.write_apk("universal.apk", self.files)
        with self.assertRaisesRegex(RuntimeError, "Unexpected APK ABIs"):
            inspect_apk(universal, ("x86_64",))
        with self.assertRaisesRegex(ValueError, "ABI selection"):
            inspect_apk(universal, ("x86",))

    def test_changed_shared_code_asset_native_library_or_notice_is_rejected(self):
        universal = self.write_apk("universal.apk", self.files)
        for name in ("classes.dex", "assets/x-renpy/x-common/x-screen.rpy",
                     "lib/x86_64/libflutter.so", "META-INF/LICENSE.notice"):
            with self.subTest(name=name):
                files = self.variant_files()
                files[name] = b"changed"
                with self.assertRaisesRegex(RuntimeError, "changed shared payload"):
                    compare_apk_payloads(universal, self.write_apk("changed.apk", files), ("x86_64",))

    def test_missing_or_extra_shared_payload_entry_is_rejected(self):
        universal = self.write_apk("universal.apk", self.files)
        missing = self.variant_files()
        del missing["META-INF/LICENSE.notice"]
        extra = dict(self.variant_files(), **{"assets/unexpected.txt": b"unexpected"})
        for files in (missing, extra):
            with self.subTest(entries=list(files)):
                with self.assertRaisesRegex(RuntimeError, "changed payload entries"):
                    compare_apk_payloads(universal, self.write_apk("entries.apk", files), ("x86_64",))

    def test_regenerated_signature_entries_are_allowed(self):
        universal = self.write_apk("universal.apk", self.files)
        files = self.variant_files()
        for name in ("META-INF/MANIFEST.MF", "META-INF/CERT.SF", "META-INF/CERT.RSA"):
            files[name] = b"new signature for the selected ABI package"
        compare_apk_payloads(universal, self.write_apk("signed-variant.apk", files), ("x86_64",))


if __name__ == "__main__":
    unittest.main()
