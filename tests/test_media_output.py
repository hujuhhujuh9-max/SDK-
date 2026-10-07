"""Reject silent output and unrelated sounds in emulator audio captures."""

import math
import struct
import unittest

from scripts.media_output import tone_levels


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
