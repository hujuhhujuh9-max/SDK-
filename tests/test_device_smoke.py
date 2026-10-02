import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from scripts.device_smoke import find_control, wait_for


class DeviceWaitTests(unittest.TestCase):
    def test_leaf_ui_control_is_a_successful_result(self):
        button = ET.fromstring('<node class="android.widget.Button" content-desc="Increment" />')
        self.assertIs(wait_for(lambda: button, seconds=0.1), button)

    def test_android_text_field_can_be_selected_without_serialized_hint(self):
        field = ET.fromstring('<node class="android.widget.EditText" text="" content-desc="" />')
        label = ET.fromstring('<node class="android.widget.TextView" text="Capabilities" />')
        with patch("scripts.device_smoke.controls", return_value=[label, field]):
            self.assertIs(find_control("Input probe", Path("unused.xml"),
                                      control_class="android.widget.EditText"), field)


if __name__ == "__main__":
    unittest.main()
