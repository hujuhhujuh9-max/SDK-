import unittest
import xml.etree.ElementTree as ET

from scripts.device_smoke import wait_for


class DeviceWaitTests(unittest.TestCase):
    def test_leaf_ui_control_is_a_successful_result(self):
        button = ET.fromstring('<node class="android.widget.Button" content-desc="Increment" />')
        self.assertIs(wait_for(lambda: button, seconds=0.1), button)


if __name__ == "__main__":
    unittest.main()
