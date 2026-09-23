"""Synology File Station storage backend for CameraAI evidence clips.

Files are always staged in the local clip cache first. Successful captures are
then mirrored to File Station over HTTPS. A missing local clip is downloaded
on demand, so video/audio workers and the web player can keep using normal
filesystem paths without exposing NAS credentials to browsers.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import time
from typing import Iterator

import requests
from urllib3.exceptions import InsecureRequestWarning

import config


class SynologyStorageError(RuntimeError):
    pass


def enabled() -> bool:
    return (
        config.STORAGE_BACKEND == "synology"
        and bool(config.SYNOLOGY_URL)
        and bool(config.SYNOLOGY_USERNAME)
        and bool(config.SYNOLOGY_PASSWORD)
    )


def _safe_reference(reference: str) -> PurePosixPath:
    normalized = str(reference or "").replace("\\", "/")
    relative = PurePosixPath(normalized)
    if not normalized or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid clip reference")
    return relative


def remote_path(reference: str) -> str:
    relative = _safe_reference(reference)
    parts = [config.SYNOLOGY_SHARE.rstrip("/")]
    if config.SYNOLOGY_ROOT:
        parts.append(config.SYNOLOGY_ROOT)
    parts.append(relative.as_posix())
    return "/" + "/".join(part.strip("/") for part in parts if part)


class FileStationClient:
    def __init__(self) -> None:
        if not enabled():
            raise SynologyStorageError("Synology storage is not configured")
        self.base_url = config.SYNOLOGY_URL
        self.timeout = config.SYNOLOGY_TIMEOUT_SECONDS
        self.verify = config.SYNOLOGY_VERIFY_TLS
        if not self.verify:
            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
        self.session = requests.Session()
        self.sid: str | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/webapi/entry.cgi"

    def login(self) -> None:
        response = self.session.post(
            self.endpoint,
            data={
                "api": "SYNO.API.Auth",
                "version": "7",
                "method": "login",
                "account": config.SYNOLOGY_USERNAME,
                "passwd": config.SYNOLOGY_PASSWORD,
                "session": "FileStation",
                # Cookie sessions are required by File Station's multipart
                # upload endpoint on current DSM releases.
                "format": "cookie",
            },
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success") or not payload.get("data", {}).get("sid"):
            code = payload.get("error", {}).get("code", "unknown")
            raise SynologyStorageError(f"Synology login failed (code={code})")
        self.sid = payload["data"]["sid"]

    def logout(self) -> None:
        if not self.sid:
            return
        try:
            self.session.post(
                self.endpoint,
                data={
                    "api": "SYNO.API.Auth",
                    "version": "7",
                    "method": "logout",
                    "session": "FileStation",
                    "_sid": self.sid,
                },
                timeout=min(self.timeout, 10),
                verify=self.verify,
            )
        finally:
            self.sid = None
            self.session.close()

    def _json_post(self, data: dict) -> dict:
        if not self.sid:
            raise SynologyStorageError("Synology session is not authenticated")
        response = self.session.post(
            self.endpoint,
            data={**data, "_sid": self.sid},
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            code = payload.get("error", {}).get("code", "unknown")
            raise SynologyStorageError(f"File Station request failed (code={code})")
        return payload.get("data", {})

    def upload(self, local_path: Path, destination: str) -> None:
        if not self.sid:
            raise SynologyStorageError("Synology session is not authenticated")
        with local_path.open("rb") as stream:
            response = self.session.post(
                self.endpoint,
                params={"_sid": self.sid},
                data={
                    "api": "SYNO.FileStation.Upload",
                    "version": "2",
                    "method": "upload",
                    "path": str(PurePosixPath(destination).parent),
                    "create_parents": "true",
                    "overwrite": "true",
                },
                files={"file": (PurePosixPath(destination).name, stream, "application/octet-stream")},
                timeout=max(self.timeout, 300),
                verify=self.verify,
            )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            code = payload.get("error", {}).get("code", "unknown")
            raise SynologyStorageError(f"File Station upload failed (code={code})")

    def download(self, source: str, target: Path) -> None:
        if not self.sid:
            raise SynologyStorageError("Synology session is not authenticated")
        target.parent.mkdir(parents=True, exist_ok=True)
        response = self.session.get(
            self.endpoint,
            params={
                "api": "SYNO.FileStation.Download",
                "version": "2",
                "method": "download",
                "path": json.dumps([source]),
                "mode": "download",
                "_sid": self.sid,
            },
            stream=True,
            timeout=max(self.timeout, 300),
            verify=self.verify,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            payload = response.json()
            code = payload.get("error", {}).get("code", "unknown")
            raise FileNotFoundError(f"Remote clip is unavailable (code={code})")
        fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
            if temporary.stat().st_size == 0:
                raise FileNotFoundError("Remote clip is empty")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def list_folder(self, folder: str, offset: int = 0, limit: int = 1000) -> dict:
        return self._json_post({
            "api": "SYNO.FileStation.List",
            "version": "2",
            "method": "list",
            "folder_path": folder,
            "offset": offset,
            "limit": limit,
            "additional": json.dumps(["size"]),
        })

    def delete(self, source: str) -> None:
        data = self._json_post({
            "api": "SYNO.FileStation.Delete",
            "version": "2",
            "method": "start",
            "path": json.dumps([source]),
        })
        task_id = data.get("taskid")
        if not task_id:
            return
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            status = self._json_post({
                "api": "SYNO.FileStation.Delete",
                "version": "2",
                "method": "status",
                "taskid": task_id,
            })
            if status.get("finished"):
                return
            time.sleep(0.2)
        raise SynologyStorageError("Timed out while deleting remote clip")


@contextmanager
def client() -> Iterator[FileStationClient]:
    instance = FileStationClient()
    instance.login()
    try:
        yield instance
    finally:
        instance.logout()


def upload_clip(reference: str, local_path: Path) -> bool:
    if not enabled():
        return False
    with client() as api:
        api.upload(local_path, remote_path(reference))
    return True


def download_clip(reference: str, local_path: Path) -> bool:
    if not enabled():
        return False
    with client() as api:
        api.download(remote_path(reference), local_path)
    return local_path.is_file()


def delete_clip(reference: str) -> bool:
    if not enabled():
        return False
    with client() as api:
        api.delete(remote_path(reference))
    return True


def inventory() -> dict:
    """Return a recursive, read-only inventory of the configured remote root."""
    if not enabled():
        return {"state": "disabled", "files": 0, "videos": 0, "size_bytes": 0}
    root = remote_path(".").rstrip("/.")
    folders = [root]
    file_count = video_count = size_bytes = 0
    with client() as api:
        while folders:
            folder = folders.pop()
            offset = 0
            while True:
                page = api.list_folder(folder, offset=offset)
                files = page.get("files", [])
                for item in files:
                    if item.get("isdir"):
                        folders.append(item["path"])
                    else:
                        file_count += 1
                        if str(item.get("name", "")).lower().endswith(".mp4"):
                            video_count += 1
                        size_bytes += int(item.get("additional", {}).get("size", 0) or 0)
                offset += len(files)
                if not files or offset >= int(page.get("total", offset)):
                    break
    return {"state": "available", "root": root, "files": file_count, "videos": video_count, "size_bytes": size_bytes}


def health() -> dict:
    result = {
        "backend": config.STORAGE_BACKEND,
        "enabled": enabled(),
        "url": config.SYNOLOGY_URL,
        "share": config.SYNOLOGY_SHARE,
        "root": config.SYNOLOGY_ROOT,
    }
    if not enabled():
        result["state"] = "disabled"
        return result
    try:
        with client():
            pass
        result["state"] = "available"
    except Exception as exc:
        result["state"] = "unavailable"
        result["error"] = str(exc)
    return result
