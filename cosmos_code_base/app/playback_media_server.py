"""Serve local Playback MP4 files with HTTP byte-range support.

Streamlit's normal local-file media storage may copy a large video into memory.
This loopback-only server lets the browser request just the ranges it needs.
"""

from __future__ import annotations

import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


class _PlaybackServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _PlaybackHandler)
        self.files: Dict[str, Path] = {}
        self.files_lock = threading.Lock()


class _PlaybackHandler(BaseHTTPRequestHandler):
    server: _PlaybackServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_HEAD(self) -> None:
        self._serve(send_body=False)

    def do_GET(self) -> None:
        self._serve(send_body=True)

    def _video_path(self) -> Optional[Path]:
        request_path = urlsplit(self.path).path
        prefix = "/media/"
        if not request_path.startswith(prefix):
            return None
        key = unquote(request_path[len(prefix):])
        with self.server.files_lock:
            path = self.server.files.get(key)
        if path is None:
            return None
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            pass
        return None

    @staticmethod
    def _requested_range(header: str, size: int) -> Optional[Tuple[int, int]]:
        if not header:
            return None
        match = _RANGE_RE.fullmatch(header.strip())
        if not match:
            raise ValueError("invalid range")
        start_text, end_text = match.groups()
        if not start_text and not end_text:
            raise ValueError("empty range")
        if not start_text:
            suffix_size = int(end_text)
            if suffix_size <= 0:
                raise ValueError("invalid suffix range")
            return max(0, size - suffix_size), size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
        if start >= size or end < start:
            raise ValueError("range outside file")
        return start, min(end, size - 1)

    def _serve(self, *, send_body: bool) -> None:
        path = self._video_path()
        if path is None:
            self.send_error(404)
            return

        size = path.stat().st_size
        try:
            requested = self._requested_range(self.headers.get("Range", ""), size)
        except (TypeError, ValueError):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        start, end = requested if requested is not None else (0, size - 1)
        length = end - start + 1
        self.send_response(206 if requested is not None else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if requested is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if not send_body:
            return
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


_server: Optional[_PlaybackServer] = None
_server_lock = threading.Lock()


def register_playback_video(video_path: Path, token: str) -> str:
    """Register a video and return its loopback streaming URL."""
    path = video_path.resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(path)

    global _server
    with _server_lock:
        if _server is None:
            _server = _PlaybackServer()
            threading.Thread(
                target=_server.serve_forever,
                daemon=True,
                name="playback-media-server",
            ).start()
        safe_key = f"{token}.mp4"
        with _server.files_lock:
            _server.files[safe_key] = path
        port = _server.server_address[1]
    return f"http://127.0.0.1:{port}/media/{quote(safe_key)}"
