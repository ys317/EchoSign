"""Rule and code extraction checks, independent of user settings or models."""
from pathlib import Path
import tempfile
import unittest

import yaml

from echosign.matcher import RuleMatcher
from echosign.watcher import SignInWatcher


class MatcherTests(unittest.TestCase):
    def test_attendance_phrases_do_not_match_time_ranges(self):
        template = Path(__file__).resolve().parents[1] / "config.example.yaml"
        rules = yaml.safe_load(template.read_text(encoding="utf-8"))["rules"]
        matcher = RuleMatcher(rules["strong"], rules["weak_groups"])
        cases = (
            ("那我们先点个到，然后开始做作业", "high"),
            ("现在开始点名了", "high"),
            ("二三三零", None),
            ("我们三点到五点再开始写作业", None),
            ("从两点到四点都是自习课", None),
            ("今天我们讲第二章第三节", None),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                result = matcher.match(text)
                self.assertEqual(result[0] if result else None, expected)

    def test_standalone_codes_and_attendance_window(self):
        with tempfile.TemporaryDirectory() as directory:
            watcher = SignInWatcher(standalone_code=True,
                                    log_file=str(Path(directory) / "codes.jsonl"))
            self.assertEqual(watcher.feed("二三三零", final=True)[0][0], "2330")
            self.assertEqual(watcher.feed("今天讲第二章第三节，然后做二十分钟作业", final=True), [])
            watcher.trigger("现在开始签到", "签到提示")
            self.assertEqual(watcher.feed("签到码四五六七", final=True)[0][0], "4567")
            self.assertEqual(watcher.feed("五六七八", final=True)[0][0], "5678")


if __name__ == "__main__":
    unittest.main()
