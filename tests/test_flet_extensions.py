"""Keep paired extension packages and their licenses in the fixed build."""

import json
import tempfile
import unittest
from pathlib import Path

from build_android import ROOT, copy_flet_extensions, extension_projects


class ExtensionPackagingTests(unittest.TestCase):
    def fixture(self, root):
        names = json.loads((ROOT / "runtime/flet_extensions.json").read_text())
        (root / "client/lib").mkdir(parents=True)
        (root / "client/lib/main.dart").write_text("\n".join(
            "import 'package:" + name.replace("-", "_") + "/extension.dart';" for name in names))
        for name in names:
            module = name.replace("-", "_")
            project = root / "sdk/python/packages" / name
            (project / "src" / module).mkdir(parents=True)
            (project / "src" / module / "__init__.py").write_text("value = 1\n")
            (project / "src/flutter" / module).mkdir(parents=True)
            (project / "src/flutter" / module / "pubspec.yaml").write_text("name: " + module + "\n")
            (project / "LICENSE").write_text("component license " + name)
            (project / "pyproject.toml").write_text('[project]\nname = "' + name + '"\nversion = "0.1.0"\n')
        return names

    def test_paired_packages_and_notices_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = self.fixture(root)
            site, notices = root / "site", root / "notices"
            site.mkdir()
            notices.mkdir()
            copy_flet_extensions(root, site, notices)
            for name in names:
                module = name.replace("-", "_")
                self.assertTrue((site / module / "__init__.py").is_file())
                self.assertEqual((notices / (name + "-LICENSE.txt")).read_text(), "component license " + name)
                self.assertIn("Name: " + name, (site / (module + "-0.1.0.dist-info/METADATA")).read_text())

    def test_catalog_cannot_silently_drop_a_client_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with (root / "client/lib/main.dart").open("a") as source:
                source.write("\nimport 'package:flet_extra/extension.dart';")
            with self.assertRaisesRegex(RuntimeError, "catalog differs"):
                extension_projects(root)

    def test_missing_python_half_fails_the_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = self.fixture(root)
            (root / "sdk/python/packages" / names[0] / "src" /
             names[0].replace("-", "_") / "__init__.py").unlink()
            with self.assertRaisesRegex(RuntimeError, "Missing Flet Python"):
                extension_projects(root)


if __name__ == "__main__":
    unittest.main()
