"""Signal-quality and streaming regressions using synthetic audio only."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock
import wave

import numpy as np

from hdusign.audio import SAMPLE_RATE, StreamingASR, StreamingResampler, WavFileSource, resample_to_16k


class FinalizationTests(unittest.TestCase):
    def test_revision_changes_only_when_fresh_audio_is_actually_decoded(self):
        recognizer = Mock()
        recognizer.is_ready.side_effect = [True, True, False, False, True, False]
        recognizer.is_endpoint.return_value = False
        recognizer.get_result.return_value = "一二三四"
        asr = StreamingASR.__new__(StreamingASR)
        asr._rec = recognizer
        asr.restart()
        asr.accept(np.zeros(4000, dtype=np.float32))
        self.assertEqual(asr.revision, 2)
        asr.accept(np.zeros(4000, dtype=np.float32))
        self.assertEqual(asr.revision, 2)
        asr.accept(np.zeros(4000, dtype=np.float32))
        self.assertEqual(asr.revision, 3)

    def test_flush_decodes_the_tail_instead_of_committing_an_incomplete_prefix(self):
        state = SimpleNamespace(finished=False, remaining=2)
        stream = Mock()
        stream.input_finished.side_effect = lambda: setattr(state, "finished", True)
        recognizer = Mock()
        recognizer.is_ready.side_effect = lambda _: state.finished and state.remaining > 0
        recognizer.decode_stream.side_effect = lambda _: setattr(state, "remaining", state.remaining - 1)
        recognizer.get_result.side_effect = lambda _: "12345" if state.remaining == 0 else "1234"
        asr = StreamingASR.__new__(StreamingASR)
        asr._rec, asr._stream, asr._has_audio = recognizer, stream, True

        self.assertEqual(asr.flush(), ["12345"])
        self.assertIs(asr._stream, recognizer.create_stream.return_value)
        self.assertEqual(asr.flush(), [], "Flushing twice must not emit the previous code again")

    def test_restart_discards_previous_recording_and_does_not_flush_empty_audio(self):
        asr = StreamingASR.__new__(StreamingASR)
        asr._rec = Mock()
        asr.restart()
        self.assertEqual(asr.flush(), [])
        asr._rec.decode_stream.assert_not_called()


class ResamplerTests(unittest.TestCase):
    def test_speech_band_is_preserved_and_aliases_are_attenuated(self):
        for rate in (44100, 48000):
            time = np.arange(rate) / rate
            for frequency in (1000, 6000, 9000, 12000):
                with self.subTest(rate=rate, frequency=frequency):
                    signal = np.sin(2 * np.pi * frequency * time).astype(np.float32)
                    output = resample_to_16k(signal, rate)
                    self.assertEqual(len(output), SAMPLE_RATE)
                    # Exclude clip padding when measuring steady-state response.
                    rms = float(np.sqrt(np.mean(output[100:-100] ** 2)))
                    if frequency < SAMPLE_RATE / 2:
                        self.assertAlmostEqual(rms, np.sqrt(0.5), delta=0.003)
                    else:
                        self.assertLess(rms, 0.0003)  # > 67 dB below the input tone.

    def test_arbitrary_chunks_preserve_phase_samples_and_final_tail(self):
        rng = np.random.default_rng(7)
        for rate in (8000, 16000, 22050, 44100, 48000):
            with self.subTest(rate=rate):
                signal = rng.normal(0, 0.1, rate // 5 + 17).astype(np.float32)
                converter = StreamingResampler(rate)
                parts = []
                position = 0
                while position < len(signal):
                    count = int(rng.integers(1, 512))
                    parts.append(converter.accept(signal[position:position + count]))
                    parts.append(converter.accept(np.empty(0)))
                    position += count
                parts.append(converter.flush())
                output = np.concatenate(parts)
                expected_length = (len(signal) * SAMPLE_RATE + rate - 1) // rate
                self.assertEqual(len(output), expected_length)
                self.assertEqual(output.dtype, np.float32)
                np.testing.assert_allclose(output, resample_to_16k(signal, rate), atol=2e-6, rtol=0)
                self.assertEqual(len(converter.flush()), 0)

    def test_empty_and_sub_filter_length_clips(self):
        for rate in (16000, 44100, 48000):
            for length in (0, 1, 5):
                with self.subTest(rate=rate, length=length):
                    signal = np.ones(length, dtype=np.float32)
                    output = resample_to_16k(signal, rate)
                    self.assertEqual(len(output), (length * SAMPLE_RATE + rate - 1) // rate)
                    self.assertTrue(np.isfinite(output).all())

    def test_native_16k_is_unchanged(self):
        signal = np.random.default_rng(0).normal(size=107).astype(np.float32)
        np.testing.assert_array_equal(resample_to_16k(signal, SAMPLE_RATE), signal)

    def test_stereo_wav_replay_is_independent_of_chunk_size(self):
        rate = 44100
        time = np.arange(rate // 4 + 13) / rate
        pcm = np.column_stack((np.sin(2 * np.pi * 1000 * time),
                               np.sin(2 * np.pi * 2300 * time)))
        pcm = np.round(pcm * 10000).astype("<i2")
        expected = resample_to_16k(pcm.astype(np.float32).mean(axis=1) / 32768, rate)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(rate)
                output.writeframes(pcm.tobytes())
            for chunk_seconds in (0.001, 0.25):
                with self.subTest(chunk_seconds=chunk_seconds):
                    actual = np.concatenate(list(WavFileSource(str(path), chunk_seconds).chunks()))
                    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=0)


if __name__ == "__main__":
    unittest.main()
