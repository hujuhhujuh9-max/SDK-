"""Enter APK Java callbacks without changing Ren'Py's interpreter ownership.

JNI FindClass on a Python-created thread otherwise uses Android's system loader.
The packaged NativeInvocationHandler supplies the app loader during its callback.
Use call_with_app_class_loader for Android JNI work on additional Python threads.
"""

from jnius import PythonJavaClass, java_method


class _JavaCall(PythonJavaClass):
    __javainterfaces__ = ["java/lang/Runnable"]
    # Runnable is a system interface; the native callback belongs to the APK.
    __javacontext__ = "system"

    def __init__(self, handler):
        self.handler = handler
        self.result = None
        self.error = None
        super().__init__()

    @java_method("()V")
    def run(self):
        try:
            self.result = self.handler()
        except BaseException as error:
            self.error = error

    def invoke(self):
        self.j_self.run()
        if self.error is not None:
            raise self.error
        return self.result


def app_loader_callback(handler):
    """Prepare on the Android owner thread; retain the proxy until it returns."""
    return _JavaCall(handler).invoke


def call_with_app_class_loader(handler, *args, **kwargs):
    """Run JNI work from a Python worker after the owner prepared its callback."""
    return app_loader_callback(lambda: handler(*args, **kwargs))()
