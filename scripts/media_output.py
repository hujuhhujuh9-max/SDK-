"""Verify emulator audio output and moving Flutter/native framebuffer pixels."""

import array
import hashlib
import json
import math
import os
import re
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path


def tone_levels(pcm, rate=16000):
    """Measure RMS and the fixture's 440 Hz component in short PCM windows."""
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    window = rate // 10
    assert len(samples) >= window * 3, "Audio output capture is too short"
    rms, tone = [], []
    cosine = [math.cos(2 * math.pi * 440 * i / rate) for i in range(window)]
    sine = [math.sin(2 * math.pi * 440 * i / rate) for i in range(window)]
    for start in range(0, len(samples) - window + 1, window):
        values = [value / 32768 for value in samples[start:start + window]]
        rms.append(math.sqrt(sum(value * value for value in values) / window))
        real = sum(value * weight for value, weight in zip(values, cosine))
        imaginary = sum(value * weight for value, weight in zip(values, sine))
        tone.append(math.sqrt(2) * math.hypot(real, imaginary) / window)
    return {"seconds": len(samples) / rate, "sample_rate_hz": rate, "rms": statistics.median(rms),
            "tone_440hz_rms": statistics.median(tone)}


def capture_audio(path):
    """Read at least 1.2 seconds of actual low-latency monitor samples."""
    if wave_output := os.environ.get("RUNNER_AUDIO_WAVE"):
        return capture_wave_audio(Path(wave_output), path)
    with path.open("wb") as audio, path.with_suffix(".log").open("w") as log:
        capture = subprocess.Popen([
            "parec", "--device=" + os.environ.get("RUNNER_AUDIO_MONITOR", "runner_output.monitor"),
            "--rate=16000", "--channels=1", "--format=s16le", "--latency-msec=50"],
            stdout=audio, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while path.stat().st_size < 38400:
                assert capture.poll() is None, "Audio output monitor failed; see " + str(log.name)
                assert time.monotonic() < deadline, "Audio output monitor produced no complete capture"
                time.sleep(0.05)
        finally:
            capture.terminate()
            capture.wait(timeout=10)
    return tone_levels(path.read_bytes())


def capture_wave_audio(source, path):
    """Capture new samples from QEMU's growing PCM WAV output, not its history."""
    with source.open("rb") as stream:
        header = stream.read(44)
        assert len(header) == 44 and header[:4] == b"RIFF" and header[8:20] == b"WAVEfmt \x10\x00\x00\x00", (
            "Expected QEMU's PCM WAV output", source)
        encoding, channels, rate, byte_rate, frame_size, bits = struct.unpack_from("<HHIIHH", header, 20)
        assert (encoding, channels, rate, byte_rate, frame_size, bits) == (1, 2, 48000, 192000, 4, 16), (
            "Unexpected emulator audio format", source)
        assert header[36:40] == b"data"
        # QEMU finalizes RIFF lengths only on shutdown. Read fresh complete
        # frames from EOF, retaining play/pause boundaries while it runs.
        start = 44 + (source.stat().st_size - 44) // frame_size * frame_size
        stream.seek(start)
        required = byte_rate * 12 // 10
        deadline = time.monotonic() + 30
        while (size := source.stat().st_size) - start < required:
            assert size >= start, "Emulator audio output restarted during capture"
            assert time.monotonic() < deadline, (
                "Emulator produced no complete audio capture", {"start": start, "size": size, "required": required})
            time.sleep(0.05)
        stereo = array.array("h", stream.read(required))
        if sys.byteorder != "little":
            stereo.byteswap()
        mono = array.array("h", ((stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo), 2)))
        if sys.byteorder != "little":
            mono.byteswap()
        pcm = mono.tobytes()
    path.write_bytes(pcm)
    return tone_levels(pcm, rate)


def check_media_output(output, device):
    """Use the device harness's ADB/UI helpers without owning device state."""
    pid = int(device.runner_pid())
    initial_errors = device.markers().count("SDK_RUNNER_MEDIA_ERROR")
    density = json.loads((output / "device-environment.json").read_text())["density_dpi"]
    receipt = {"pid": pid, "audio": {}, "video": {}, "animation": {}}

    def control(label, height=0, upward=False):
        return device.wait_for(lambda: device.find_control(
            label, output / "media-ui.xml", scroll_up=upward, scroll_down=not upward,
            minimum_height=int(height * density / 160) - 1 if height else 0), 30)

    def action(label, kind, action_name, upward=False):
        before = device.markers()
        device.tap(control(label, upward=upward))
        marker = "SDK_RUNNER_MEDIA " if kind != "animation" else "SDK_RUNNER_ANIMATION "

        def completed():
            logs = device.markers()
            assert logs.count("SDK_RUNNER_MEDIA_ERROR") == before.count("SDK_RUNNER_MEDIA_ERROR"), (
                "Media playback failed; see logcat")
            return logs.count(marker) > before.count(marker)

        device.wait_for(completed, 30)
        if kind != "animation":
            result = device.json_markers(device.markers(), marker)[-1]
            assert result["kind"] == kind and result["action"] == action_name and result["pid"] == pid
            return result

    def audio_capture(name):
        if not os.environ.get("RUNNER_AUDIO_WAVE"):
            (output / ("audio-" + name + "-host.txt")).write_text(subprocess.check_output(
                ["pactl", "list", "sink-inputs"], text=True, timeout=15))
        return capture_audio(output / ("audio-" + name + ".s16le"))

    action("Play audio", "audio", "play")
    # Hardware volume keys select the active music stream, avoiding shell
    # volume commands whose calling-package checks vary between images.
    device.adb("shell", "input", "keyevent", *(["24"] * 10))
    (output / "audio-volume.txt").write_text(device.adb("shell", "dumpsys", "audio"))
    receipt["audio"]["playing"] = audio_capture("playing")
    action("Pause audio", "audio", "pause")
    receipt["audio"]["paused"] = audio_capture("paused")
    action("Resume audio", "audio", "resume")
    receipt["audio"]["resumed"] = audio_capture("resumed")
    action("Pause audio", "audio", "pause")
    for name in ("playing", "resumed"):
        assert receipt["audio"][name]["tone_440hz_rms"] > 0.005, (
            "The emulator did not output the audible fixture tone", receipt["audio"])
    assert receipt["audio"]["paused"]["tone_440hz_rms"] < max(
        0.001, receipt["audio"]["playing"]["tone_440hz_rms"] * 0.1), (
            "Audio continued after pause", receipt["audio"])
    (output / "audio-output.json").write_text(json.dumps(
        {"pid": pid, "audio": receipt["audio"]}, indent=2) + "\n")
    print("Passed: captured tone during play/resume and silence during pause", flush=True)

    def frames(label, height, name, moving):
        node = control(label, height)
        bounds = list(map(int, re.findall(r"\d+", node.get("bounds"))))
        signatures, colors = [], []
        deadline = time.monotonic() + 30
        while len(signatures) < 3:
            raw = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
            width, screen_height, header = device.framebuffer_shape(raw)
            left, top, right, bottom = bounds
            assert 0 <= left < right <= width and 0 <= top < bottom <= screen_height, bounds
            pixels = bytearray()
            for row in range(12):
                y = top + (bottom - top) * (row + 2) // 16
                for column in range(24):
                    x = left + (right - left) * (column + 2) // 28
                    offset = header + (y * width + x) * 4
                    pixels.extend(raw[offset:offset + 3])
            colored = sum(max(pixels[i:i + 3]) - min(pixels[i:i + 3]) > 80
                          for i in range(0, len(pixels), 3))
            if not signatures and colored < 4:
                assert time.monotonic() < deadline, ("Media output never painted its first frame", name)
                time.sleep(0.25)
                continue
            signatures.append(hashlib.sha256(pixels).hexdigest())
            colors.append(colored)
            if len(signatures) < 3:
                time.sleep(0.45)
        assert min(colors) >= 4, ("Media control painted no expected colored content", name, colors)
        assert (len(set(signatures)) > 1 if moving else len(set(signatures)) == 1), (
            "Media pixels did not match the requested playback state", name, signatures)
        device.story_screenshot(output, name)
        return {"bounds": bounds, "frame_sha256": signatures, "colored_samples": colors}

    # Reveal the output before starting playback, so frame capture does not
    # begin while scrolling or attaching the video surface.
    control("Local video output", 180)
    action("Play video", "video", "play")
    receipt["video"]["playing"] = frames("Local video output", 180, "video-playing", True)
    paused = action("Pause video", "video", "pause", upward=True)
    assert paused["position_ms"] > 0, ("Video playback position never advanced", paused)
    time.sleep(0.3)
    receipt["video"]["paused"] = frames("Local video output", 180, "video-paused", False)
    device.adb("shell", "input", "keyevent", "3")
    device.adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    action("Play video", "video", "play", upward=True)
    receipt["video"]["resumed"] = frames("Local video output", 180, "video-resumed", True)
    action("Pause video", "video", "pause", upward=True)

    control("Local animation output", 80)
    action("Play animation", "animation", "play")
    receipt["animation"]["playing"] = frames("Local animation output", 80, "animation-playing", True)
    action("Pause animation", "animation", "pause", upward=True)
    time.sleep(0.3)
    receipt["animation"]["paused"] = frames("Local animation output", 80, "animation-paused", False)
    action("Play animation", "animation", "play", upward=True)
    device.adb("shell", "input", "keyevent", "3")
    device.adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    receipt["animation"]["resumed"] = frames("Local animation output", 80, "animation-resumed", True)
    action("Pause animation", "animation", "pause", upward=True)
    assert int(device.runner_pid()) == pid, "Output verification restarted the game"
    assert device.markers().count("SDK_RUNNER_MEDIA_ERROR") == initial_errors, (
        "Native media playback reported an asynchronous error; see logcat")
    (output / "media-output.json").write_text(json.dumps(receipt, indent=2) + "\n")
    control("Run checks", upward=True)
    print("Passed: audible output, video frames and animation pixels play, pause and resume", flush=True)


def check_native_animation(output, device):
    """Probe the actual native ATL light before and after Android backgrounding."""
    pid = device.runner_pid()
    positions = []
    for name in ("native-animation-playing", "native-animation-resumed"):
        pair = []
        for index in range(3):
            raw = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
            width, height, header = device.framebuffer_shape(raw)
            y = round(150 * height / 1280)
            points = []
            for x in range(round(270 * width / 720), round(470 * width / 720)):
                offset = header + (y * width + x) * 4
                if all(abs(actual - target) < 8 for actual, target in
                       zip(raw[offset:offset + 3], (0, 212, 200))):
                    points.append(x)
            assert len(points) >= 10, ("Native ATL light did not paint", name, index)
            pair.append(statistics.mean(points))
            if index < 2:
                time.sleep(0.25)
        assert max(pair) - min(pair) > 10, ("Native ATL animation stayed still", pair)
        positions.append(pair)
        device.story_screenshot(output, name)
        if name.endswith("playing"):
            device.adb("shell", "input", "keyevent", "3")
            device.adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
            time.sleep(0.5)
    assert device.runner_pid() == pid
    (output / "native-animation.json").write_text(json.dumps({"pid": int(pid), "positions": positions}, indent=2))
    print("Passed: native ATL pixels move before and after background/resume", flush=True)
