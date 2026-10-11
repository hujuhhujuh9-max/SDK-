"""Evidence roots must follow the installed app and its fresh process."""

import unittest
import xml.etree.ElementTree as ET

from scripts.named_save_device_checks import named_save_input, native_save_directory


class NamedSaveDeviceEvidenceTests(unittest.TestCase):
    package = "org.renfletpy.example"

    def trace(self, path, pid="4515"):
        return "I/python: SDK_RUNNER_NATIVE_SAVE_DIR path=" + path + " pid=" + pid

    def test_real_scoped_external_path_and_internal_paths_are_accepted(self):
        for root in ("/storage/emulated/0/Android/data/", "/data/data/", "/data/user/0/"):
            path = root + self.package + "/files/saves/app-starter"
            with self.subTest(root=root):
                self.assertEqual(native_save_directory(self.trace(path), "4515", self.package), path)

    def test_old_process_and_ambiguous_directories_cannot_supply_evidence(self):
        path = "/storage/emulated/0/Android/data/" + self.package + "/files/saves/app-starter"
        self.assertEqual(native_save_directory(self.trace(path) + "\n" + self.trace(path),
                                               "4515", self.package), path)
        for trace in (self.trace(path, "3344"),
                      self.trace(path) + "\n" + self.trace("/data/data/" + self.package + "/files/saves/app-starter")):
            with self.subTest(trace=trace), self.assertRaises(RuntimeError):
                native_save_directory(trace, "4515", self.package)

    def test_other_package_shared_directory_and_traversal_are_rejected(self):
        paths = ("/storage/emulated/0/Android/data/org.other.app/files/saves/app-starter",
                 "/storage/emulated/0/Download/saves/app-starter",
                 "/storage/emulated/0/Android/data/" + self.package + "/files/../saves/app-starter",
                 "/data/data/" + self.package + "/files/saves/other-template")
        for path in paths:
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                native_save_directory(self.trace(path), "4515", self.package)

    def test_captured_unlabeled_editor_is_selected_only_on_the_browser(self):
        heading = ET.Element("node", {"package": self.package, "content-desc": "Saved games"})
        field = ET.Element("node", {"package": self.package, "class": "android.widget.EditText",
                                   "content-desc": "", "text": "", "enabled": "true",
                                   "bounds": "[63,378][851,578]"})
        self.assertIs(named_save_input([heading, field], self.package), field)
        field.set("text", "Choice checkpoint")
        self.assertIs(named_save_input([heading, field], self.package), field)
        self.assertIsNone(named_save_input([field], self.package))
        field.set("enabled", "false")
        self.assertIsNone(named_save_input([heading, field], self.package))

    def test_ambiguous_editors_are_rejected_instead_of_typing_into_the_wrong_field(self):
        nodes = [ET.Element("node", {"package": self.package, "content-desc": "Saved games"})]
        nodes.extend(ET.Element("node", {"package": self.package, "class": "android.widget.EditText",
                                        "bounds": "[63,378][851,578]"}) for _ in range(2))
        with self.assertRaises(RuntimeError):
            named_save_input(nodes, self.package)


if __name__ == "__main__":
    unittest.main()
