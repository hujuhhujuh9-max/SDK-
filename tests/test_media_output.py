"""Reject silent output and unrelated sounds in emulator audio captures."""

import json
import math
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.media_output import capture_wave_audio, check_native_animation, tone_levels


class ToneOutputTests(unittest.TestCase):
    def pcm(self, frequency, amplitude=0.06):
        return b"".join(struct.pack("<h", round(32767 * amplitude * math.sin(
            2 * math.pi * frequency * i / 16000))) for i in range(16000))

    def test_fixture_tone_is_measured_at_its_actual_volume(self):
        report = tone_levels(self.pcm(440))
        self.assertAlmostEqual(report["rms"], 0.06 / math.sqrt(2), places=4)
        self.assertAlmostEqual(report["tone_440hz_rms"], report["rms"], places=4)

    def test_silence_and_unrelated_audio_do_not_pass_as_the_fixture(self):
        self.assertEqual(tone_levels(bytes(32000))["tone_440hz_rms"], 0)
        self.assertLess(tone_levels(self.pcm(1000))["tone_440hz_rms"], 0.001)

    def test_empty_capture_does_not_pass_as_paused_audio(self):
        with self.assertRaisesRegex(AssertionError, "too short"):
            tone_levels(b"")

    def test_live_wave_capture_uses_fresh_output_for_both_play_and_pause(self):
        # QEMU leaves RIFF/data sizes zero until shutdown. A previous tone
        # must not make paused output pass, nor hide a newly started tone.
        header = (b"RIFF" + bytes(4) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2,
                  48000, 192000, 4, 16) + b"data" + bytes(4))
        tone = b"".join(struct.pack("<hh", value, value) for i in range(57600)
                        for value in [round(32767 * 0.06 * math.sin(2 * math.pi * 440 * i / 48000))])
        for playing in (False, True):
            with self.subTest(playing=playing), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "output.wav"
                target = Path(folder) / "captured.s16le"
                source.write_bytes(header + (bytes(len(tone)) if playing else tone))

                def append_output(delay):
                    with source.open("ab") as stream:
                        stream.write(tone if playing else bytes(len(tone)))

                with patch("scripts.media_output.time.sleep", side_effect=append_output):
                    report = capture_wave_audio(source, target)
                self.assertAlmostEqual(report["seconds"], 1.2)
                self.assertAlmostEqual(report["tone_440hz_rms"], 0.06 / math.sqrt(2) if playing else 0, places=4)

    def test_an_unexpected_wave_encoding_fails_output_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "output.wav"
            source.write_bytes(bytes(44))
            with self.assertRaisesRegex(AssertionError, "Expected QEMU"):
                capture_wave_audio(source, Path(folder) / "unused.s16le")


class NativeAnimationOutputTests(unittest.TestCase):
    def frame(self, center):
        pixels = bytearray((0, 0, 0, 255) * 720)
        for x in range(center - 7, center + 7):
            pixels[x * 4:x * 4 + 4] = bytes((0, 212, 200, 255))
        return bytes(pixels)

    def device(self):
        return SimpleNamespace(runner_pid=lambda: "321",
                               framebuffer_shape=lambda raw: (720, 1, 0),
                               story_screenshot=Mock(), background_and_resume=Mock())

    def test_periodic_capture_observes_motion_before_and_after_background(self):
        # The real light takes 0.8 seconds in each direction. A 1.35-second
        # capture plus the old 0.25-second pause samples the same phase forever.
        for initial_elapsed in (0.0, 0.975):
            with self.subTest(initial_elapsed=initial_elapsed), tempfile.TemporaryDirectory() as folder:
                elapsed = initial_elapsed
                def capture(*args, **kwargs):
                    nonlocal elapsed
                    elapsed += 1.35
                    phase = elapsed % 1.6
                    fraction = phase / 0.8 if phase < 0.8 else (1.6 - phase) / 0.8
                    return self.frame(round(300 + 160 * fraction))
                def advance(seconds):
                    nonlocal elapsed
                    elapsed += seconds
                device = self.device()
                output = Path(folder)
                with patch("scripts.media_output.subprocess.check_output", side_effect=capture), \
                        patch("scripts.media_output.time.sleep", side_effect=advance):
                    check_native_animation(output, device)
                receipt = json.loads((output / "native-animation.json").read_text())
                self.assertEqual(receipt["pid"], 321)
                self.assertEqual(len(receipt["positions"]), 2)
                for positions in receipt["positions"]:
                    self.assertEqual(len(positions), 3)
                    self.assertGreater(max(positions) - min(positions), 10)
                device.background_and_resume.assert_called_once()

    def test_still_or_insufficient_movement_never_writes_success(self):
        for centers in ((330, 330, 330), (330, 331, 325)):
            with self.subTest(centers=centers), tempfile.TemporaryDirectory() as folder:
                output = Path(folder)
                frames = [self.frame(center) for center in centers]
                with patch("scripts.media_output.subprocess.check_output", side_effect=frames), \
                        patch("scripts.media_output.time.sleep"):
                    with self.assertRaisesRegex(AssertionError, "Native ATL animation stayed still"):
                        check_native_animation(output, self.device())
                self.assertFalse((output / "native-animation.json").exists())
