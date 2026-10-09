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
    AndroidRecipes, EDITED_ROWS, REQUIRED_CHECKS, apk_identity, auto_paired_suffix, bounds,
    check_app_recipes, cursor_at_text_end, green_swatch, selection_covers_text, semantic,
    validate_recipe_receipt,
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
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": '[{"name":"Old","count":1}]'})
        empty = ET.Element("node", {**field.attrib, "text": ""})
        prefixes = [ET.Element("node", {**field.attrib, "text": source[:index]})
                    for index in range(1, len(source) + 1)]
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true "
                       f"mCursorSelStart=0 mCursorSelEnd={len(field.get('text'))}")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(side_effect=[field, field, field, empty,
                                                *prefixes, prefixes[-1]])
            ui.button = Mock(return_value=ET.Element("node", bounds="[10,20][90,60]"))
            ui.edit(source)
            commands = [call.args for call in adb.call_args_list if call.args[:3] ==
                        ("shell", "input", "text")]
            self.assertEqual([shlex.split(command[3]) for command in commands],
                             [[character] for character in source])
            self.assertIn(('shell', 'input', 'swipe', 50, 21, 50, 21, '1000'),
                          [call.args for call in adb.call_args_list])
            ui.button.assert_called_once_with("Select all")
            self.assertFalse(any(call.args[:3] == ("shell", "input", "keycombination")
                                 for call in adb.call_args_list))

    def test_delayed_partial_prefix_blocks_the_next_native_character(self):
        source = json.dumps(EDITED_ROWS, separators=(",", ":"))
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": ""})
        # Main's failed burst stopped at 55 with these exact closures, omitting
        # :2}]. A delayed observation of that prefix must not release character 57.
        partial = ET.Element("node", {**field.attrib,
                                      "text": source[:55] + '""""""}""""""}]'})
        before = [ET.Element("node", {**field.attrib, "text": source[:index]})
                  for index in range(1, 55)]
        after = [ET.Element("node", {**field.attrib, "text": source[:index]})
                 for index in range(56, len(source) + 1)]
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(side_effect=[field, field, field, field, *before,
                                                partial, partial, partial, *after, after[-1]])
            pending_counts = []
            def observe_delay(_):
                pending_counts.append(sum(call.args[:3] == ("shell", "input", "text")
                                          for call in adb.call_args_list))
            with patch("scripts.app_recipes_device_checks.time.sleep", side_effect=observe_delay):
                ui.edit(source)
            self.assertEqual(pending_counts, [56, 56])
            commands = [call.args for call in adb.call_args_list
                        if call.args[:3] == ("shell", "input", "text")]
            self.assertEqual("".join(shlex.split(command[3])[0] for command in commands), source)

    def test_wrong_or_unfocused_prefix_prevents_the_next_native_input(self):
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": ""})
        for text, focused in (("corrupt", "true"), ("[]", "false")):
            with self.subTest(text=text, focused=focused), tempfile.TemporaryDirectory() as folder:
                adb = Mock(return_value="mIsInputViewShown=true mInputShown=true")
                ui = AndroidRecipes(adb, Path(folder))
                invalid = ET.Element("node", {**field.attrib, "text": text, "focused": focused})
                ui.editor_field = Mock(side_effect=[field, field, field, field, invalid])
                def immediate(check, description):
                    result = check()
                    if isinstance(result, ET.Element) or result:
                        return result
                    raise RuntimeError(description)
                ui.wait = immediate
                with self.assertRaisesRegex(RuntimeError, "native keyboard JSON character 1/2"):
                    ui.edit("[]")
                commands = [call.args for call in adb.call_args_list]
                self.assertEqual([shlex.split(command[3]) for command in commands
                                  if command[:3] == ("shell", "input", "text")], [["["]])
                self.assertFalse(any(command[:3] == ("shell", "input", "keyevent")
                                     for command in commands))

    def test_observed_auto_pairs_require_exact_prefix_and_live_caret_boundary(self):
        source = json.dumps(EDITED_ROWS, separators=(",", ":"))
        suffix = '""""""}""""""}]'
        self.assertEqual((len(source), len(source + suffix)), (59, 74))
        self.assertEqual(auto_paired_suffix(source, source + suffix), suffix)
        self.assertEqual(auto_paired_suffix(source, source), "")
        for actual in (source + 'garbage', source + '"', source[:-1] + suffix, "other" + suffix):
            with self.subTest(actual=actual):
                self.assertIsNone(auto_paired_suffix(source, actual))
        self.assertTrue(cursor_at_text_end("mCursorSelStart=59 mCursorSelEnd=59", source))
        for report in ("mCursorSelStart=0 mCursorSelEnd=149",
                       "mCursorSelStart=74 mCursorSelEnd=74",
                       "mCursorSelStart=58 mCursorSelEnd=59",
                       "initialSelStart=59 initialSelEnd=59"):
            with self.subTest(report=report):
                self.assertFalse(cursor_at_text_end(report, source))

    def test_auto_pair_cleanup_uses_only_bounded_native_forward_delete(self):
        source = json.dumps(EDITED_ROWS, separators=(",", ":"))
        suffix = '""""""}""""""}]'
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": ""})
        prefixes = [ET.Element("node", {**field.attrib, "text": source[:index]})
                    for index in range(1, len(source))]
        paired = ET.Element("node", {**field.attrib, "text": source + suffix})
        exact = ET.Element("node", {**field.attrib, "text": source})
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true "
                       "mCursorSelStart=59 mCursorSelEnd=59")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(side_effect=[field, field, field, field,
                                                *prefixes, paired, exact])
            ui.edit(source)
            self.assertIn(("shell", "input", "keyevent", *(["112"] * 15)),
                          [call.args for call in adb.call_args_list])
            self.assertIn("mCursorSelStart=59", (Path(folder) / "app-recipes-typed-cursor.txt").read_text())

    def test_unconfirmed_native_caret_never_trims_the_document(self):
        source = json.dumps(EDITED_ROWS, separators=(",", ":"))
        suffix = '""""""}""""""}]'
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": ""})
        prefixes = [ET.Element("node", {**field.attrib, "text": source[:index]})
                    for index in range(1, len(source))]
        paired = ET.Element("node", {**field.attrib, "text": source + suffix})
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true "
                       "mCursorSelStart=74 mCursorSelEnd=74")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(side_effect=[field, field, field, field, *prefixes, paired])
            def immediate(check, description):
                result = check()
                if isinstance(result, ET.Element) or result:
                    return result
                raise RuntimeError(description)
            ui.wait = immediate
            with self.assertRaisesRegex(RuntimeError, "native cursor before auto-paired suffix"):
                ui.edit(source)
            self.assertFalse(any(call.args[:3] == ("shell", "input", "keyevent")
                                 for call in adb.call_args_list))

    def test_native_selection_must_cover_the_document_before_deleting(self):
        # The failed Android run had caret47 and deleted only comma46.
        self.assertFalse(selection_covers_text("mCursorSelStart=47 mCursorSelEnd=47", "x" * 149))
        self.assertFalse(selection_covers_text("mCursorSelStart=0 mCursorSelEnd=148", "x" * 149))
        self.assertFalse(selection_covers_text("initialSelStart=0 initialSelEnd=149", "x" * 149))
        self.assertTrue(selection_covers_text("mCursorSelStart=0 mCursorSelEnd=149", "x" * 149))
        self.assertTrue(selection_covers_text("mCursorSelStart=149 mCursorSelEnd=0", "x" * 149))
        self.assertTrue(selection_covers_text("mCursorSelStart=0 mCursorSelEnd=2", "🌟"))

    def test_partial_native_selection_never_deletes_or_types(self):
        field = ET.Element("node", {"class": "android.widget.EditText", "focused": "true",
                                    "bounds": "[1,2][100,40]", "text": "x" * 149})
        with tempfile.TemporaryDirectory() as folder:
            adb = Mock(return_value="mIsInputViewShown=true mInputShown=true "
                       "mCursorSelStart=47 mCursorSelEnd=47")
            ui = AndroidRecipes(adb, Path(folder))
            ui.editor_field = Mock(return_value=field)
            ui.button = Mock(return_value=ET.Element("node", bounds="[10,20][90,60]"))
            def immediate(check, description):
                result = check()
                if isinstance(result, ET.Element) or result:
                    return result
                raise RuntimeError(description)
            ui.wait = immediate
            with self.assertRaisesRegex(RuntimeError, "complete native CodeEditor selection"):
                ui.edit("[]")
            commands = [call.args for call in adb.call_args_list]
            self.assertNotIn(("shell", "input", "keyevent", "67"), commands)
            self.assertFalse(any(command[:3] == ("shell", "input", "text") for command in commands))
            self.assertIn("mCursorSelStart=47", (Path(folder) / "app-recipes-selection.txt").read_text())

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
