import copy
import json
import shlex
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.app_recipes_device_checks import (
    AndroidRecipes, EDITED_ROWS, REQUIRED_CHECKS, apk_identity, bounds,
    check_app_recipes, green_swatch, semantic, validate_recipe_receipt,
)


class RecipeAndroidSelectorTests(unittest.TestCase):
    def test_failed_dump_never_reads_previous_successful_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            path = output / "app-recipes-ui.xml"
            path.write_text('<hierarchy><node resource-id="recipe-editor" /></hierarchy>')
            adb = Mock(return_value="ERROR: could not get idle state.")
            self.assertEqual(AndroidRecipes(adb, output).nodes(), [])
            adb.assert_called_once_with("shell", "uiautomator", "dump",
                                        "/sdcard/runner-recipes-ui.xml")

    def test_exact_identifier_rejects_a_similar_or_unrelated_editable_field(self):
        nodes = list(ET.fromstring('<hierarchy><node resource-id="other-editor" '
                                  'class="android.widget.EditText" />'
                                  '<node resource-id="recipe-editor-result" /></hierarchy>').iter("node"))
        self.assertIsNone(semantic(nodes, "recipe-editor"))
        with tempfile.TemporaryDirectory() as folder:
            ui = AndroidRecipes(Mock(), Path(folder))
            ui.nodes = Mock(return_value=nodes)
            self.assertIsNone(ui.editor_field())

    def test_editor_uses_its_real_descendant_field_and_native_focus(self):
        nodes = list(ET.fromstring('<hierarchy><node class="android.widget.EditText" />'
                                  '<node resource-id="recipe-editor" bounds="[1,2][200,220]">'
                                  '<node class="android.widget.EditText" focused="true" '
                                  'bounds="[5,6][190,210]" /></node></hierarchy>').iter("node"))
        with tempfile.TemporaryDirectory() as folder:
            ui = AndroidRecipes(Mock(), Path(folder))
            ui.nodes = Mock(return_value=nodes)
            self.assertIs(ui.editor_field(), nodes[-1])

    def test_duplicate_or_clipped_semantic_selectors_fail(self):
        duplicate = ET.fromstring('<node resource-id="recipe-loading" bounds="[1,2][3,4]" />')
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            semantic([duplicate, duplicate], "recipe-loading")
        for value in ("", "[0,0][0,30]", "[-1,0][30,30]", "[1,1][3,3]ignored"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                bounds(ET.fromstring('<node />') if not value else ET.Element("node", bounds=value))

    def test_result_selector_requires_its_actual_child_text(self):
        node = ET.fromstring('<node resource-id="recipe-table-result" bounds="[1,2][30,40]">'
                             '<node text="Order: Harbor2, Beacon7; Selected: none" /></node>')
        self.assertIsNone(semantic([node], "recipe-table-result", "Selected: Beacon7"))
        self.assertIs(semantic([node], "recipe-table-result", "Order: Harbor2, Beacon7"), node)

    def test_keyboard_json_is_shell_quoted_and_confirmed_exactly(self):
        source = json.dumps(EDITED_ROWS, separators=(",", ":"))
        field = ET.fromstring('<node class="android.widget.EditText" focused="true" '
                              'bounds="[1,2][100,40]" text="" />')
        typed = ET.Element("node", {**field.attrib, "text": source})
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(side_effect=[field, field, field, typed])
            ui.edit(source)
            command = next(call.args for call in adb.call_args_list if call.args[:3] ==
                           ("shell", "input", "text"))
            self.assertEqual(shlex.split(command[3]), [source])
            self.assertIn(('shell', 'input', 'keycombination', '113', '29'),
                          [call.args for call in adb.call_args_list])

    def test_missing_software_keyboard_prevents_typing_or_success(self):
        field = ET.fromstring('<node class="android.widget.EditText" focused="true" '
                              'bounds="[1,2][100,40]" text="" />')
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=false mInputShown=false")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(return_value=field)
            def immediate(check, description):
                result = check()
                if isinstance(result, ET.Element) or result:
                    return result
                raise RuntimeError(description)
            ui.wait = immediate
            with self.assertRaisesRegex(RuntimeError, "software keyboard"):
                ui.edit("[]")
            self.assertFalse(any(call.args[:3] in (("shell", "input", "text"),
                                                   ("shell", "input", "keycombination"))
                                 for call in adb.call_args_list))
            self.assertIn("mInputShown=false", (Path(folder) / "app-recipes-keyboard.txt").read_text())

    def test_green_picker_probe_ignores_green_pixels_outside_its_bounds(self):
        frame = struct.pack("<III", 30, 30, 1) + bytes((76, 175, 80, 255)) * 900
        with self.assertRaisesRegex(AssertionError, "outside"):
            green_swatch(frame, [0, 0, 31, 30])
        dark_picker = bytearray(frame)
        for y in range(10, 20):
            for x in range(10, 20):
                offset = 12 + (y * 30 + x) * 4
                dark_picker[offset:offset + 4] = bytes((0, 0, 0, 255))
        with self.assertRaisesRegex(RuntimeError, "did not paint"):
            green_swatch(dark_picker, [10, 10, 20, 20])
        point, report = green_swatch(frame, [0, 0, 30, 30])
        self.assertEqual(point, (13, 13))
        self.assertEqual(report["colors"]["green"], 100)


class RecipeDeviceReceiptTests(unittest.TestCase):
    def inspection(self):
        return {"source_sha": "a" * 40, "sha256": "b" * 64,
                "startup_template": "app", "abis": ["x86_64"]}

    def receipt(self):
        def pixels(color):
            return {"bounds": [1, 2, 30, 40], "sampled_pixels": 100, "colors": {color: 80}}
        return {**self.inspection(), "source_pid": "123", "success": True, "skips": 0,
                "checks": {
                    "keyboard_json_apply": {"rows": EDITED_ROWS, "native_text": json.dumps(EDITED_ROWS),
                                              "software_keyboard_shown": True},
                    "invalid_json_keeps_table": {"order": ["Beacon7", "Harbor2"],
                                                  "error": "Row 1 count must be an integer from 0 to 999."},
                    "table_sort": {"column": "Count", "order": ["Harbor2", "Beacon7"]},
                    "table_select": {"selected": "Beacon7"},
                    "color_change_and_preview": {"color": "#4caf50", "palette": pixels("green"),
                                                   "preview": pixels("green")},
                    "loading_pending_and_complete": {"rows": 3, "spinner_pixels": pixels("blue")},
                    "loading_cancel_and_retry": {"cancelled_result_retained": True, "retry_rows": 3},
                    "detached_load_keeps_new_page": {"result": "Ready to load sample."},
                }}

    def test_gate_binds_source_hash_mode_and_abi(self):
        receipt = self.receipt()
        self.assertIs(validate_recipe_receipt(receipt, self.inspection()), receipt)
        for name, value in (("source_sha", "c" * 40), ("sha256", "c" * 64),
                            ("startup_template", "story"), ("abis", ["arm64-v8a"])):
            invalid = copy.deepcopy(receipt)
            invalid[name] = value
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, name):
                validate_recipe_receipt(invalid, self.inspection())

    def test_every_required_operation_must_have_real_result_fields(self):
        for name in REQUIRED_CHECKS:
            for replacement in (None, {}, {"deferred": True}):
                receipt = self.receipt()
                if replacement is None:
                    del receipt["checks"][name]
                else:
                    receipt["checks"][name] = replacement
                with self.subTest(name=name, replacement=replacement), self.assertRaises(RuntimeError):
                    validate_recipe_receipt(receipt, self.inspection())
        for name, value in (("success", False), ("success", 1), ("skips", 1),
                            ("skips", False), ("deferred", True), ("source_pid", "")):
            receipt = self.receipt()
            receipt[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                validate_recipe_receipt(receipt, self.inspection())

    def test_screenshot_only_color_or_unpainted_loading_is_not_success(self):
        for name, field in (("color_change_and_preview", "palette"),
                            ("color_change_and_preview", "preview"),
                            ("loading_pending_and_complete", "spinner_pixels")):
            for invalid in ({"screenshot": "looks-good.png"},
                            {"bounds": [1, 2, 30, 40], "sampled_pixels": 100,
                             "colors": {"green" if name.startswith("color") else "blue": 0}}):
                receipt = self.receipt()
                receipt["checks"][name][field] = invalid
                with self.subTest(name=name, field=field), self.assertRaises(RuntimeError):
                    validate_recipe_receipt(receipt, self.inspection())

    def test_unchanged_table_or_initial_picker_color_is_not_native_event_evidence(self):
        for name, field, value in (("table_sort", "order", ["Beacon7", "Harbor2"]),
                                   ("table_select", "selected", "none"),
                                   ("color_change_and_preview", "color", "#1565c0"),
                                   ("keyboard_json_apply", "software_keyboard_shown", False),
                                   ("loading_cancel_and_retry", "cancelled_result_retained", False),
                                   ("detached_load_keeps_new_page", "result", "Loaded 3 rows")):
            receipt = self.receipt()
            receipt["checks"][name][field] = value
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_recipe_receipt(receipt, self.inspection())

    def test_wrong_mode_receipt_is_rejected_and_old_success_file_is_removed_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "apk-inspection.json").write_text(json.dumps(self.inspection()))
            receipt = output / "app-recipes.json"
            receipt.write_text(json.dumps(self.receipt()))
            adb = Mock()
            with self.assertRaisesRegex(RuntimeError, "matching inspected APK"):
                check_app_recipes(adb, output, startup_template="story")
            self.assertFalse(receipt.exists())
            adb.assert_not_called()
            self.assertEqual(apk_identity(output, "app"), self.inspection())


if __name__ == "__main__":
    unittest.main()
