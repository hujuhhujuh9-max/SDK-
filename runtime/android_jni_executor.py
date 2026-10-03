"""Run executor work inside the Android app's native JNI callback."""

from concurrent.futures import ThreadPoolExecutor


class AppClassLoaderExecutor(ThreadPoolExecutor):
    """Prepare each callback on its submitting owner and execute it on a worker."""

    def submit(self, fn, /, *args, **kwargs):
        from android_jni import app_loader_callback

        def invoke():
            return fn(*args, **kwargs)

        # The bound execute retains the native proxy while the work is queued.
        execute = app_loader_callback(invoke)
        return super().submit(execute)
