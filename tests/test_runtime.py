"""Portable dependencies must resolve without another installation or download."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from echosign import runtime


class RuntimeTests(unittest.TestCase):
    def test_frozen_browser_ignores_external_cache(self):
        with tempfile.TemporaryDirectory(prefix="中文 路径 ") as folder:
            root = Path(folder)
            (root / "browsers").mkdir()
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", str(root), create=True), \
                    patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "missing-external-cache"}):
                runtime.configure_browser_runtime()
                self.assertEqual(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]), root / "browsers")

    def test_missing_browser_gives_extraction_guidance(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", folder, create=True):
            with self.assertRaisesRegex(RuntimeError, "完整解压"):
                runtime.configure_browser_runtime()

    def test_source_respects_developer_browser_cache(self):
        with patch.object(sys, "frozen", False, create=True), \
                patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "custom-cache"}):
            runtime.configure_browser_runtime()
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "custom-cache")

    def test_bundled_semantic_model_never_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "models" / runtime.SEMANTIC_FOLDER
            model.mkdir(parents=True)
            for name in runtime.SEMANTIC_FILES:
                (model / name).write_bytes(b"fixture")
            with patch.object(runtime, "application_root", return_value=root):
                options = runtime.semantic_model_options(runtime.SEMANTIC_MODEL)
                self.assertTrue(options["local_files_only"])
                self.assertEqual(Path(options["specific_model_path"]), model)

    def test_incomplete_frozen_model_does_not_start_download(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(runtime, "application_root", return_value=Path(folder)), \
                patch.object(sys, "frozen", True, create=True):
            with self.assertRaisesRegex(RuntimeError, "完整解压"):
                runtime.semantic_model_options(runtime.SEMANTIC_MODEL)


if __name__ == "__main__":
    unittest.main()
