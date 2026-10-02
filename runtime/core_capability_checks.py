"""Exercise retained Android services and Python modules in the sample runner."""

import bz2
import hashlib
import pickle
import ssl
import zlib


async def check_core_services(passed):
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
    try:
        await brightness.set_animate(False)
        await brightness.set_application_screen_brightness(0.6)
        assert abs(await brightness.get_application_screen_brightness() - 0.6) < 0.05
    finally:
        await brightness.reset_application_screen_brightness()
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
