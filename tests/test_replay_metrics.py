"""Synthetic events test recall, wrong submissions and annotation coverage."""
import unittest

from tools.replay_metrics import score_clip, summarize_scores


class ReplayMetricsTests(unittest.TestCase):
    def score(self, codes=(), prompts=(), annotation=None, window=(0, 100)):
        events = {
            "codes": [{"t": t, "code": c, "text": c} for t, c in codes],
            "alerts": [{"t": t, "level": "high", "text": "test", "reason": "test"}
                       for t in prompts],
            "finals": [], "audio_seconds": 100.0,
        }
        return score_clip({"clip_id": "synthetic", "window": list(window)}, events,
                          annotation=annotation)

    def test_correct_then_wrong_code_counts_as_recall_but_not_success(self):
        row = self.score([(10, "6609"), (15, "6660")],
                         annotation={"true_code": "6609", "invalid_codes": ["6660"]})
        self.assertTrue(row["code_recalled"])
        self.assertFalse(row["code_correct"])
        self.assertEqual(row["wrong_codes"], ["6660"])
        self.assertTrue(row["first_code_correct"])
        self.assertFalse(row["last_code_correct"])
        summary = summarize_scores([row])
        self.assertEqual(summary["code_precision"], 0.5)
        self.assertEqual(summary["code_correct_without_wrong_output_clips"], 0)

    def test_wrong_code_outside_detection_window_still_counts(self):
        row = self.score([(1, "1111"), (30, "0023")],
                         annotation={"true_code": "0023", "code_labels_complete": True},
                         window=(20, 40))
        self.assertEqual(row["codes"], ["0023"])
        self.assertTrue(row["code_recalled"])
        self.assertFalse(row["code_correct"])
        self.assertEqual(row["wrong_codes"], ["1111"])
        self.assertEqual(row["outside_window_seconds"], 80)

    def test_missing_labels_do_not_become_negative_samples(self):
        row = self.score([(10, "1234")], [20])
        self.assertIsNone(row["code_correct"])
        summary = summarize_scores([row])
        self.assertEqual(summary["unannotated_clips"], ["synthetic"])
        self.assertEqual(summary["code_labeled_clips"], 0)
        self.assertIsNone(summary["code_precision"])
        self.assertIsNone(summary["false_prompts_per_annotated_hour"])

    def test_false_prompt_inside_proximity_window_counts_in_negative_clip(self):
        row = self.score([(20, "2026")], [10], annotation={"announced": "nothing_audible"})
        self.assertEqual(row["prompts_outside_window"], 0)
        self.assertEqual(row["outside_window_seconds"], 0)
        self.assertEqual(row["false_prompts_in_annotated_negatives"], 1)
        self.assertEqual(row["annotated_negative_seconds"], 100)
        self.assertEqual(row["wrong_codes"], ["2026"])

    def test_negative_intervals_are_clipped_and_merged(self):
        row = self.score(prompts=[5, 25, 50, 99], annotation={
            "announced": "spoken_cue_only",
            "negative_windows": [[-5, 20], [10, 30], [95, 120]],
        })
        self.assertEqual(row["annotated_negative_seconds"], 35)
        self.assertEqual(row["false_prompts_in_annotated_negatives"], 3)

    def test_final_flush_at_end_of_negative_clip_is_not_excluded(self):
        row = self.score([(100, "2026")], [100], annotation={"announced": "nothing_audible"})
        self.assertEqual(row["wrong_codes"], ["2026"])
        self.assertEqual(row["false_prompts_in_annotated_negatives"], 1)

    def test_expected_code_during_annotated_ordinary_speech_is_still_wrong(self):
        row = self.score([(10, "1234"), (40, "1234")], annotation={
            "true_code": "1234", "negative_windows": [[0, 20]],
        })
        self.assertTrue(row["code_recalled"])
        self.assertFalse(row["code_correct"])
        self.assertEqual(row["wrong_codes"], ["1234"])
        self.assertFalse(row["first_code_correct"])
        self.assertTrue(row["last_code_correct"])

    def test_no_prediction_is_a_miss_for_a_known_code(self):
        row = self.score(annotation={"true_code": "0001"})
        self.assertFalse(row["code_recalled"])
        self.assertFalse(row["code_correct"])
        self.assertEqual(row["judged_code_events"], 0)

    def test_two_valid_sign_in_codes_in_one_clip_are_both_correct(self):
        row = self.score([(10, "8348"), (45, "7802")],
                         annotation={"true_codes": ["8348", "7802"]})
        self.assertTrue(row["code_correct"])
        self.assertEqual(row["wrong_codes"], [])
        summary = summarize_scores([row])
        self.assertEqual(summary["reference_codes"], 2)
        self.assertEqual(summary["recalled_reference_codes"], 2)

    def test_unlisted_code_is_unverified_when_reference_is_incomplete(self):
        row = self.score([(10, "8348"), (45, "7802")], annotation={"true_code": "7802"})
        self.assertTrue(row["code_recalled"])
        self.assertIsNone(row["code_correct"])
        self.assertEqual(row["wrong_codes"], [])
        self.assertEqual(row["unjudged_codes"], ["8348"])
        summary = summarize_scores([row])
        self.assertEqual(summary["wrong_code_events"], 0)
        self.assertEqual(summary["unjudged_code_events"], 1)
        self.assertEqual(summary["code_judgment_coverage"], 0.5)

    def test_missing_second_reference_code_is_not_full_recall(self):
        row = self.score([(10, "8348")], annotation={"true_codes": ["8348", "7802"]})
        self.assertFalse(row["code_recalled"])
        self.assertEqual(row["recalled_codes"], ["8348"])
        self.assertEqual(summarize_scores([row])["recalled_reference_codes"], 1)

    def test_verified_codes_can_belong_to_different_sign_in_windows(self):
        row = self.score([(10, "8348"), (90, "7802")], window=(0, 30),
                         annotation={"true_codes": ["8348", "7802"]})
        self.assertTrue(row["code_recalled"])
        self.assertTrue(row["code_correct"])
        self.assertEqual(row["codes_outside_window"], 1)

    def test_latency_uses_end_of_spoken_cue_and_code_not_platform_time(self):
        row = self.score([(35, "6609")], [24], annotation={"speech_events": [
            {"kind": "prompt", "start": 18, "end": 20, "match_until": 30},
            {"kind": "code", "code": "6609", "start": 31, "end": 33, "match_until": 40},
        ]})
        self.assertEqual([e["latency_seconds"] for e in row["speech_latencies"]], [4, 2])
        self.assertEqual(row["prompt_delay"], 24)
        summary = summarize_scores([row])
        self.assertEqual(summary["prompt_latency"]["median_seconds"], 4)
        self.assertEqual(summary["code_latency"]["median_seconds"], 2)

    def test_wrong_or_preexisting_code_cannot_supply_detection_latency(self):
        row = self.score([(5, "6609"), (21, "6660"), (25, "6609")], annotation={"speech_events": [
            {"kind": "code", "code": "6609", "start": 18, "end": 20, "match_until": 30},
        ]})
        self.assertEqual(row["speech_latencies"][0]["latency_seconds"], 5)

    def test_later_unrelated_alert_does_not_hide_a_missed_prompt(self):
        row = self.score(prompts=[90], annotation={"speech_events": [
            {"kind": "prompt", "start": 18, "end": 20, "match_until": 40},
        ]})
        self.assertIsNone(row["speech_latencies"][0]["latency_seconds"])
        summary = summarize_scores([row])["prompt_latency"]
        self.assertEqual(summary["missed_events"], 1)
        self.assertIsNone(summary["median_seconds"])

    def test_each_output_can_only_match_one_spoken_event(self):
        row = self.score([(25, "1234")], annotation={"speech_events": [
            {"kind": "code", "code": "1234", "start": 18, "end": 20, "match_until": 30},
            {"kind": "code", "code": "1234", "start": 22, "end": 23, "match_until": 35},
        ]})
        self.assertEqual([e["detected_at"] for e in row["speech_latencies"]], [25, None])

    def test_detection_before_segment_end_retains_signed_latency(self):
        row = self.score(prompts=[20], annotation={"speech_events": [
            {"kind": "prompt", "start": 18, "end": 22, "match_until": 30},
        ]})
        self.assertEqual(row["speech_latencies"][0]["latency_seconds"], -2)

    def test_missing_speech_timing_is_not_reported_as_zero_delay(self):
        summary = summarize_scores([self.score([(10, "1234")], [5])])
        self.assertEqual(summary["code_latency"]["annotated_events"], 0)
        self.assertIsNone(summary["code_latency"]["median_seconds"])

    def test_invalid_speech_timing_is_rejected(self):
        for reference in (
            {"kind": "prompt", "start": 20, "end": 18, "match_until": 30},
            {"kind": "prompt", "start": 18, "end": 20, "match_until": 101},
            {"kind": "prompt", "start": 18, "end": float("nan"), "match_until": 30},
            {"kind": "code", "code": "12345", "start": 18, "end": 20, "match_until": 30},
        ):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.score(annotation={"speech_events": [reference]})


if __name__ == "__main__":
    unittest.main()
