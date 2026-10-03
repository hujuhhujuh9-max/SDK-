"""Exercise retained Android services and Python modules in the sample runner."""

import asyncio
import bz2
import hashlib
import pickle
import ssl
import zlib
from pathlib import Path


async def check_core_services(passed, page):
    import certifi
    import flet as ft

    payload = pickle.dumps({"runner": [1, 2, 3]})
    assert bz2.decompress(bz2.compress(payload)) == payload
    assert zlib.decompress(zlib.compress(payload)) == payload
    assert pickle.loads(payload) == {"runner": [1, 2, 3]}
    assert len(hashlib.sha256(payload).digest()) == 32
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(certifi.where())
    assert context.cert_store_stats()["x509_ca"] > 0
    passed("python_native_modules")
    from jnius import autoclass
    activity = autoclass("org.renpy.android.PythonSDLActivity").mActivity
    assert activity.getClass().getName() == "org.sdk.runner.RunnerActivity"
    provider = autoclass("androidx.core.content.FileProvider")
    java_file = autoclass("java.io.File")
    for suffix, directory in ((".provider", activity.getFilesDir()),
                              (".fileprovider", activity.getExternalFilesDir(None))):
        probe = Path(directory.getAbsolutePath()) / "runner-provider.txt"
        probe.write_text("runner provider")
        try:
            uri = provider.getUriForFile(activity, activity.getPackageName() + suffix, java_file(str(probe)))
            assert uri.getScheme() == "content"
            stream = activity.getContentResolver().openInputStream(uri)
            try:
                assert stream.read() == ord("r")
            finally:
                stream.close()
        finally:
            probe.unlink()
    passed("python_android_jni_providers")
    from android_jni import call_with_app_class_loader

    def worker_jni():
        # First lookup must happen on the additional thread, not in a warm cache.
        objects = autoclass("androidx.core.util.ObjectsCompat")
        assert objects.equals("runner", "runner")
        from jnius import PythonJavaClass, cast, java_method
        thread = autoclass("java.lang.Thread").currentThread()
        assert thread.getContextClassLoader().equals(activity.getClassLoader())
        values = []

        class Consumer(PythonJavaClass):
            __javainterfaces__ = ["androidx/core/util/Consumer"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/Object;)V")
            def accept(self, value):
                values.append(value)

        consumer = Consumer()
        cast("androidx.core.util.Consumer", consumer.j_self).accept("runner")
        assert values == ["runner"]

    await asyncio.to_thread(call_with_app_class_loader, worker_jni)
    passed("python_android_jni_thread")

    def native_worker(class_name, message):
        # Distinct first-lookups on each path avoid Pyjnius's Java class cache.
        autoclass(class_name)
        from jnius import PythonJavaClass, cast, java_method
        thread = autoclass("java.lang.Thread").currentThread()
        assert thread.getContextClassLoader().equals(activity.getClassLoader())
        assert message == "runner"
        values = []

        class Consumer(PythonJavaClass):
            __javainterfaces__ = ["androidx/core/util/Consumer"]
            __javacontext__ = "app"

            @java_method("(Ljava/lang/Object;)V")
            def accept(self, value):
                values.append(value)

        consumer = Consumer()
        cast("androidx.core.util.Consumer", consumer.j_self).accept(message)
        assert values == ["runner"]
        return True

    async def check_callback(schedule, class_name):
        loop = asyncio.get_running_loop()
        result = loop.create_future()

        def settle(value, error):
            if result.done():
                return
            if error is not None:
                result.set_exception(error)
            else:
                result.set_result(value)

        def handler(message):
            try:
                value = native_worker(class_name, message)
            except BaseException as error:
                loop.call_soon_threadsafe(settle, None, error)
            else:
                loop.call_soon_threadsafe(settle, value, None)

        schedule(handler)
        assert await asyncio.wait_for(result, 10)

    await check_callback(lambda handler: page.run_thread(handler, "runner"),
                         "androidx.core.util.Pair")
    passed("python_android_jni_page_thread")
    topic = "sdk.runner.jni"

    def publish(handler):
        page.pubsub.subscribe_topic(topic, lambda received_topic, message: handler(message))
        page.pubsub.send_all_on_topic(topic, "runner")

    try:
        await check_callback(publish, "androidx.core.text.TextUtilsCompat")
    finally:
        page.pubsub.unsubscribe_topic(topic)
    passed("python_android_jni_pubsub")
    assert await asyncio.to_thread(native_worker, "androidx.core.math.MathUtils", "runner")
    passed("python_android_jni_asyncio_thread")

    battery = ft.Battery()
    level = await battery.get_battery_level()
    assert isinstance(level, int) and 0 <= level <= 100
    assert await battery.get_battery_state() is not None
    passed("battery")
    connectivity = ft.Connectivity()
    assert await connectivity.get_connectivity()
    passed("connectivity")
    wakelock = ft.Wakelock()
    original = await wakelock.is_enabled()
    try:
        await wakelock.enable()
        assert await wakelock.is_enabled()
        await wakelock.disable()
        assert not await wakelock.is_enabled()
    finally:
        if original:
            await wakelock.enable()
    passed("wakelock")
    brightness = ft.ScreenBrightness()
    animate = await brightness.is_animate()
    try:
        await brightness.set_animate(False)
        await brightness.set_application_screen_brightness(0.6)
        assert abs(await brightness.get_application_screen_brightness() - 0.6) < 0.05
    finally:
        await brightness.reset_application_screen_brightness()
        await brightness.set_animate(animate)
    passed("brightness")
    semantics = ft.SemanticsService()
    assert await semantics.get_accessibility_features() is not None
    passed("accessibility")
    haptics = ft.HapticFeedback()
    await haptics.selection_click()
    passed("haptic_channel")
    launcher = ft.UrlLauncher()
    assert isinstance(await launcher.can_launch_url("tel:12345"), bool)
    passed("url_launcher_query")
