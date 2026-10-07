"""Reject silent output and unrelated sounds in emulator audio captures."""

import math
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.media_output import capture_wave_audio, tone_levels


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
