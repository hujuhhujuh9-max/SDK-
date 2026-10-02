import contextlib
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import prepare


class BuildInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.cache = self.root / "cache"
        self.lock = self.root / "sdk-lock.json"
        components = {}
        definitions = [
            ("flutter", "flutter", "bin/flutter", "tar.xz"),
            ("renpy", "renpy-sdk", "renpy.sh", "tar.bz2"),
            ("renpy-rapt", "rapt", "android.py", "zip"),
            ("flet", "flet-source", "packages/flet/pubspec.yaml", "tar.gz"),
        ]
        for name, root, required, fmt in definitions:
            filename = name + "." + fmt
            archive = self.archives / filename
            member = root + "/" + required
            data = b"# component build input\n"
            if fmt == "zip":
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr(member, data)
            else:
                with tarfile.open(archive, "w:" + fmt.split(".")[-1]) as t:
                    item = tarfile.TarInfo(member)
                    item.size, item.mode = len(data), 0o755
                    t.addfile(item, io.BytesIO(data))
            components[name] = {
                "version": "test", "branch": "sdk/" + name,
                "original_filename": filename, "archive_format": fmt,
                "unpacked_root": root, "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "required_paths": [required],
            }
        self.lock.write_text(json.dumps({"components": components}))
        self.inputs = prepare.BuildInputs(self.cache, self.archives, self.lock)

    def setup_component(self, component):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.inputs.setup(component)

    def test_all_archive_formats_and_rapt_attachment_are_reusable(self):
        for component in self.inputs.components:
            self.setup_component(component)
            self.assertTrue(self.inputs.ready(component))
        executable = self.inputs.sdk_root("flutter") / "bin/flutter"
        self.assertTrue(executable.stat().st_mode & 0o111)
        attached = self.inputs.sdk_root("renpy") / "rapt"
        self.assertTrue(attached.is_symlink())
        self.assertEqual(attached.resolve(), self.inputs.sdk_root("renpy-rapt"))
        with patch.object(self.inputs, "archive", side_effect=AssertionError("Inputs should be reused")):
            self.setup_component("renpy-rapt")
        for spec in self.inputs.components.values():
            prepare.verify_archive(self.archives / spec["original_filename"], spec)

    def test_checksum_mismatch_does_not_install(self):
        archive = self.archives / self.inputs.components["renpy"]["original_filename"]
        content = bytearray(archive.read_bytes())
        content[-1] ^= 1
        archive.write_bytes(content)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.setup_component("renpy")
        self.assertFalse(self.inputs.sdk_directory("renpy").exists())

    def test_archive_paths_cannot_escape_installation(self):
        destination = self.root / "stage"
        destination.mkdir()
        for filename, fmt in [("bad.zip", "zip"), ("bad.tar", "tar")]:
            archive = self.root / filename
            if fmt == "zip":
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("../escaped", b"bad")
            else:
                with tarfile.open(archive, "w") as t:
                    item = tarfile.TarInfo("../escaped")
                    item.size = 3
                    t.addfile(item, io.BytesIO(b"bad"))
            with self.assertRaises((ValueError, tarfile.FilterError)):
                prepare.extract_archive(archive, destination, fmt)
        self.assertFalse((self.root / "escaped").exists())

    def test_tar_symlink_cannot_escape_installation(self):
        archive = self.root / "bad.tar"
        destination = self.root / "stage"
        destination.mkdir()
        with tarfile.open(archive, "w") as t:
            item = tarfile.TarInfo("outside")
            item.type, item.linkname = tarfile.SYMTYPE, "../escaped"
            t.addfile(item)
        with self.assertRaises(tarfile.FilterError):
            prepare.extract_archive(archive, destination, "tar")
        self.assertFalse((destination / "outside").is_symlink())

    def test_missing_required_input_cleans_staging_directory(self):
        self.inputs.components["flet"]["required_paths"].append("missing-file")
        with self.assertRaisesRegex(ValueError, "Missing flet build input"):
            self.setup_component("flet")
        self.assertFalse(self.inputs.sdk_directory("flet").exists())
        self.assertEqual(list((self.cache / "sdks").iterdir()), [])

    def test_existing_rapt_directory_is_preserved(self):
        sdk = self.setup_component("renpy")
        existing = sdk / "rapt"
        existing.mkdir()
        (existing / "custom.txt").write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            self.setup_component("renpy-rapt")
        self.assertEqual((existing / "custom.txt").read_text(), "keep")

    def test_status_does_not_fetch_or_create_cache(self):
        with patch.object(prepare, "BuildInputs", return_value=self.inputs):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = prepare.main(["--cache-dir", str(self.cache), "status"])
        self.assertEqual(result, 0)
        self.assertIn("flet test: not installed", output.getvalue())
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
