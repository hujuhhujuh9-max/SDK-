"""Check page ownership of core native service instances."""

import sys
import types
import unittest
from unittest.mock import Mock, patch

from runtime.core_capability_checks import CORE_SERVICE_TYPES, get_core_services


class CoreServiceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.flet = types.ModuleType("flet")
        self.factories = {}
        for factory in CORE_SERVICE_TYPES.values():
            constructor = Mock(side_effect=object)
            setattr(self.flet, factory, constructor)
            self.factories[factory] = constructor
        self.enterContext(patch.dict(sys.modules, {"flet": self.flet}))

    def test_twenty_checks_keep_the_same_service_instances(self):
        page = types.SimpleNamespace()
        initial = get_core_services(page)
        for _ in range(20):
            self.assertIs(get_core_services(page), initial)
        self.assertEqual(len({id(service) for service in initial.values()}), 7)
        for constructor in self.factories.values():
            constructor.assert_called_once_with()

    def test_different_pages_have_independent_native_service_sets(self):
        first = get_core_services(types.SimpleNamespace())
        second = get_core_services(types.SimpleNamespace())
        self.assertTrue(all(first[name] is not second[name] for name in CORE_SERVICE_TYPES))
        for constructor in self.factories.values():
            self.assertEqual(constructor.call_count, 2)


if __name__ == "__main__":
    unittest.main()
