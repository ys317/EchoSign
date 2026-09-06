"""Release retries must preserve an existing draft and confirmed uploaded bytes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from release import find_release, sha256, upload_asset


def response(payload):
    return MagicMock(ok=True, json=lambda: payload)


class ReleaseTests(unittest.TestCase):
    def test_retry_finds_draft_without_a_published_tag_lookup(self):
        draft = {"id": 1, "tag_name": "v1.4", "draft": True}
        client = MagicMock()
        client.get.return_value = response([draft])
        self.assertEqual(find_release(client, "https://api.example/repo", "v1.4"), draft)
        self.assertEqual(client.get.call_args.args[0], "https://api.example/repo/releases")
        client.post.assert_not_called()

    def test_release_search_includes_later_pages(self):
        draft = {"id": 1, "tag_name": "v1.4", "draft": True}
        client = MagicMock()
        client.get.side_effect = [response([{"tag_name": f"v{i + 2}"} for i in range(100)]),
                                  response([draft])]
        self.assertEqual(find_release(client, "https://api.example/repo", "v1.4"), draft)

    def test_duplicate_drafts_are_not_modified(self):
        client = MagicMock()
        client.get.return_value = response([{"tag_name": "v1.4"}, {"tag_name": "v1.4"}])
        with self.assertRaisesRegex(RuntimeError, "Multiple releases"):
            find_release(client, "https://api.example/repo", "v1.4")
        client.post.assert_not_called()

    def test_lost_upload_response_recovers_only_matching_remote_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.zip"
            path.write_bytes(b"release fixture")
            asset = {"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                     "digest": "sha256:" + sha256(path)}
            client = MagicMock()
            client.post.side_effect = requests.ConnectionError("Response lost")
            client.get.return_value = response({"assets": [asset]})
            release = {"id": 1, "upload_url": "https://upload.example/assets{?name,label}"}
            self.assertEqual(upload_asset(client, "https://api.example/repo", release, path), asset)
            self.assertEqual(client.post.call_count, 1)
            client.delete.assert_not_called()
            asset["digest"] = "sha256:wrong"
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                upload_asset(client, "https://api.example/repo", release, path)

    def test_unconfirmed_upload_leaves_draft_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release.zip"
            path.write_bytes(b"release fixture")
            client = MagicMock()
            client.post.side_effect = requests.ConnectionError("Upload interrupted")
            client.get.return_value = response({"assets": []})
            with patch("release.time.sleep"), self.assertRaisesRegex(RuntimeError, "remains a draft"):
                upload_asset(client, "https://api.example/repo", {"id": 1, "upload_url": "https://upload.example"}, path)
            self.assertEqual(client.post.call_count, 1)
            client.patch.assert_not_called()
            client.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
