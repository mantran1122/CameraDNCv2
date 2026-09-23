import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import config
import clip_storage
import synology_storage


class SynologyStorageTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "STORAGE_BACKEND": config.STORAGE_BACKEND,
            "SYNOLOGY_URL": config.SYNOLOGY_URL,
            "SYNOLOGY_USERNAME": config.SYNOLOGY_USERNAME,
            "SYNOLOGY_PASSWORD": config.SYNOLOGY_PASSWORD,
            "SYNOLOGY_SHARE": config.SYNOLOGY_SHARE,
            "SYNOLOGY_ROOT": config.SYNOLOGY_ROOT,
            "CLIPS_DIR": config.CLIPS_DIR,
        }
        config.STORAGE_BACKEND = "synology"
        config.SYNOLOGY_URL = "https://nas.example.test:5001"
        config.SYNOLOGY_USERNAME = "camera-service"
        config.SYNOLOGY_PASSWORD = "test-secret"
        config.SYNOLOGY_SHARE = "/Ai-Camera"
        config.SYNOLOGY_ROOT = "CameraAI/clips"

    def tearDown(self):
        for name, value in self.original.items():
            setattr(config, name, value)

    def test_remote_path_is_canonical_and_rejects_traversal(self):
        self.assertEqual(
            synology_storage.remote_path("cameras/cam-001/a.mp4"),
            "/Ai-Camera/CameraAI/clips/cameras/cam-001/a.mp4",
        )
        with self.assertRaises(ValueError):
            synology_storage.remote_path("../secret.txt")

    def test_upload_passes_sid_outside_multipart_body(self):
        client = synology_storage.FileStationClient.__new__(synology_storage.FileStationClient)
        client.sid = "session-id"
        client.timeout = 5
        client.verify = True
        client.base_url = "https://nas.example.test:5001"
        response = Mock()
        response.json.return_value = {"success": True}
        client.session = Mock()
        client.session.post.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"video")
            client.upload(source, "/Ai-Camera/CameraAI/clips/clip.mp4")

        _, kwargs = client.session.post.call_args
        self.assertEqual(kwargs["params"], {"_sid": "session-id"})
        self.assertNotIn("_sid", kwargs["data"])
        self.assertEqual(kwargs["data"]["path"], "/Ai-Camera/CameraAI/clips")
        response.raise_for_status.assert_called_once()

    def test_resolve_clip_downloads_to_local_cache_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            config.CLIPS_DIR = Path(directory)

            def download(_reference, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"remote-video")
                return True

            with patch("synology_storage.enabled", return_value=True), patch(
                "synology_storage.download_clip", side_effect=download
            ) as downloader:
                resolved = clip_storage.resolve_clip_path("cameras/cam-001/clip.mp4")

            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.read_bytes(), b"remote-video")
            downloader.assert_called_once()


if __name__ == "__main__":
    unittest.main()
