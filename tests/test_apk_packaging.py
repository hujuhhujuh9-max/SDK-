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


class ApkPackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.extensions = json.loads((Path(__file__).resolve().parents[1] /
                                      "runtime/flet_extensions.json").read_text())
        private = io.BytesIO()
        config = (Path(__file__).resolve().parents[1] / "runtime/project_config.py").read_bytes()
        with tarfile.open(fileobj=private, mode="w:gz") as archive:
            data = b"retained Python package"
            member = tarfile.TarInfo("renpy/__init__.py")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
            member = tarfile.TarInfo("project_config.py")
            member.size = len(config)
            archive.addfile(member, io.BytesIO(config))
        common = "assets/x-renpy/x-common/x-screen.rpy"
        self.files = {
            "assets/private.mp3": private.getvalue(),
            common: b"retained RenPy common resource",
            "assets/runner-capabilities.json": json.dumps({
                "startup_template": "story", "source_sha": "a" * 40,
                "project_config_sha256": hashlib.sha256(config).hexdigest(),
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
        self.assertEqual(selected["extensions"], self.extensions)
        self.assertEqual(selected["startup_template"], "story")
        self.assertEqual(selected["source_sha"], "a" * 40)
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

    def startup_files(self, template, config, include=True, duplicate=False):
        files = dict(self.files)
        inventory = json.loads(files["assets/runner-capabilities.json"])
        inventory.update(startup_template=template, project_config_sha256=hashlib.sha256(config).hexdigest())
        files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
        private = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(files["assets/private.mp3"]), mode="r:gz") as original:
            with tarfile.open(fileobj=private, mode="w:gz") as archive:
                for member in original:
                    if member.name != "project_config.py":
                        archive.addfile(member, original.extractfile(member))
                if include:
                    for _ in range(2 if duplicate else 1):
                        member = tarfile.TarInfo("project_config.py")
                        member.size = len(config)
                        archive.addfile(member, io.BytesIO(config))
        files["assets/private.mp3"] = private.getvalue()
        return files

    def test_app_artifact_requires_explicit_matching_startup_mode(self):
        files = self.startup_files("app", b'STARTUP_TEMPLATE = "app"\n')
        apk = self.write_apk("app.apk", files)
        with self.assertRaisesRegex(RuntimeError, "startup template does not match"):
            inspect_apk(apk)
        self.assertEqual(inspect_apk(apk, startup_template="app")["startup_template"], "app")
        with self.assertRaisesRegex(ValueError, "Unsupported startup template"):
            inspect_apk(apk, startup_template="unexpected")

    def test_missing_or_incorrect_identity_rejects_artifact_reuse(self):
        for field, value in (("startup_template", None), ("startup_template", "app"),
                             ("source_sha", "unknown"), ("source_sha", None)):
            with self.subTest(field=field, value=value):
                files = dict(self.files)
                inventory = json.loads(files["assets/runner-capabilities.json"])
                if value is None:
                    del inventory[field]
                else:
                    inventory[field] = value
                files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
                with self.assertRaisesRegex(RuntimeError, "startup template|source revision"):
                    inspect_apk(self.write_apk("identity.apk", files))

    def test_inventory_cannot_claim_a_different_packaged_startup_configuration(self):
        for config in (b'STARTUP_TEMPLATE = "story"\n', b'STARTUP_TEMPLATE = mode\n',
                       b'STARTUP_TEMPLATE = "app"\nSTARTUP_TEMPLATE = "story"\n', b'invalid Python!'):
            with self.subTest(config=config):
                files = self.startup_files("app", config)
                with self.assertRaisesRegex(RuntimeError, "Invalid packaged startup template"):
                    inspect_apk(self.write_apk("configuration.apk", files), startup_template="app")
        files = self.startup_files("app", b'STARTUP_TEMPLATE = "app"\n')
        inventory = json.loads(files["assets/runner-capabilities.json"])
        inventory["project_config_sha256"] = "b" * 64
        files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
        with self.assertRaisesRegex(RuntimeError, "Changed packaged startup configuration"):
            inspect_apk(self.write_apk("changed-configuration.apk", files), startup_template="app")

    def test_missing_or_duplicate_startup_configuration_is_rejected(self):
        for include, duplicate in ((False, False), (True, True)):
            with self.subTest(include=include, duplicate=duplicate):
                files = self.startup_files("app", b'STARTUP_TEMPLATE = "app"\n', include, duplicate)
                with self.assertRaisesRegex(RuntimeError, "packaged startup configuration"):
                    inspect_apk(self.write_apk("missing-configuration.apk", files), startup_template="app")

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
