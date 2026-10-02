"""Check the adapter against Pyjnius's native callback-dispatch contract.

The real JNI/class-loader boundary is tested on Android, not by these stubs.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class NativeCallback:
    def __init__(self):
        self.j_self = self

    def invoke(self, method, *args):
        # Pyjnius dispatches through this reserved entry point and swallows
        # callback exceptions. The adapter must preserve both behaviors.
        try:
            return getattr(self, method)(*args)
        except Exception:
            return None


class AndroidJniContractTests(unittest.TestCase):
    def adapter(self):
        thread = types.SimpleNamespace(loader="original")
        thread.getContextClassLoader = lambda: thread.loader
        thread.setContextClassLoader = lambda loader: setattr(thread, "loader", loader)
        classes = {
            "java.lang.Thread": types.SimpleNamespace(currentThread=lambda: thread),
            "org.renpy.android.PythonSDLActivity": types.SimpleNamespace(
                mActivity=types.SimpleNamespace(getClassLoader=lambda: "app")),
        }
        jnius = types.ModuleType("jnius")
        jnius.PythonJavaClass = NativeCallback
        jnius.autoclass = classes.__getitem__
        jnius.java_method = lambda signature: lambda handler: handler
        jnius.cast = lambda interface, proxy: types.SimpleNamespace(run=lambda: proxy.invoke("run"))
        source = Path(__file__).resolve().parents[1] / "runtime/android_jni.py"
        spec = importlib.util.spec_from_file_location("android_jni_contract", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"jnius": jnius}):
            spec.loader.exec_module(module)
        module.test_thread = thread
        return module

    def test_native_dispatch_returns_the_handler_value(self):
        module = self.adapter()

        def handler(a, b):
            self.assertEqual(module.test_thread.loader, "app")
            return a + b

        self.assertEqual(module.call_with_app_class_loader(handler, 2, b=3), 5)
        self.assertEqual(module.test_thread.loader, "original")

    def test_handler_exception_survives_native_exception_suppression(self):
        module = self.adapter()
        failure = ValueError("handler failed")

        def handler():
            raise failure

        with self.assertRaises(ValueError) as caught:
            module.app_loader_callback(handler)()
        self.assertIs(caught.exception, failure)
        self.assertEqual(module.test_thread.loader, "original")


if __name__ == "__main__":
    unittest.main()
