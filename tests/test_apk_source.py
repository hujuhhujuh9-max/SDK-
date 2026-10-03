import unittest
from scripts.check_apk_source import apk_inputs_changed


class ApkSourceTests(unittest.TestCase):
    def compare(self, *paths):
        return {"status": "ahead", "files": [{"filename": path} for path in paths]}

    def test_harness_and_documentation_changes_can_reuse_apk(self):
        self.assertFalse(apk_inputs_changed(self.compare(
            "scripts/device_smoke.py", "docs/validation.md",
            ".github/workflows/check-android.yml", "tests/test_device_smoke.py")))

    def test_runtime_native_assets_and_component_pins_require_new_apk(self):
        for path in ("runtime/core_capability_checks.py", "android/app/src/main/AndroidManifest.xml",
                     "flutter/lib/main.dart", "game/script.rpy", "assets/webview.html", "sdk-lock.json"):
            with self.subTest(path=path):
                self.assertTrue(apk_inputs_changed(self.compare(path)))

    def test_truncated_comparison_cannot_silently_approve_old_apk(self):
        comparison = self.compare(*["docs/file" + str(index) for index in range(300)])
        self.assertTrue(apk_inputs_changed(comparison))

    def test_unknown_diverged_or_reverse_source_is_not_approved(self):
        for value in ({}, {"status": "diverged", "files": []},
                      {"status": "behind", "files": []}):
            self.assertTrue(apk_inputs_changed(value))
