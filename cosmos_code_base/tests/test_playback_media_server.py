from pathlib import Path
from urllib.request import Request, urlopen

from app.playback_media_server import register_playback_video


def test_playback_media_server_supports_byte_ranges(tmp_path: Path) -> None:
    video = tmp_path / "playback.mp4"
    video.write_bytes(b"0123456789")
    url = register_playback_video(video, "range-test")

    request = Request(url, headers={"Range": "bytes=2-5"})
    with urlopen(request, timeout=3) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/10"
        assert response.headers["Accept-Ranges"] == "bytes"
        assert response.read() == b"2345"


def test_playback_media_server_serves_full_file(tmp_path: Path) -> None:
    video = tmp_path / "playback.mp4"
    video.write_bytes(b"video-data")
    url = register_playback_video(video, "full-test")

    with urlopen(url, timeout=3) as response:
        assert response.status == 200
        assert response.read() == b"video-data"
