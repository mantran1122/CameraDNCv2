"""Idempotently mirror the existing local clip cache to Synology File Station."""

from __future__ import annotations

import argparse
from pathlib import Path

import config
import synology_storage


def local_clips() -> list[tuple[str, Path]]:
    root = Path(config.CLIPS_DIR).resolve()
    if not root.is_dir():
        return []
    return [
        (path.relative_to(root).as_posix(), path)
        for path in root.rglob("*.mp4")
        if path.is_file()
    ]


def remote_paths(api: synology_storage.FileStationClient) -> set[str]:
    root = synology_storage.remote_path(".").rstrip("/.")
    pending = [root]
    result: set[str] = set()
    while pending:
        folder = pending.pop()
        offset = 0
        while True:
            page = api.list_folder(folder, offset=offset)
            items = page.get("files", [])
            for item in items:
                if item.get("isdir"):
                    pending.append(item["path"])
                else:
                    result.add(str(item["path"]))
            offset += len(items)
            if not items or offset >= int(page.get("total", offset)):
                break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Upload missing files; default is a read-only inventory")
    args = parser.parse_args()

    clips = local_clips()
    total_bytes = sum(path.stat().st_size for _, path in clips)
    print(f"local_files={len(clips)} local_bytes={total_bytes} apply={args.apply}", flush=True)
    if not args.apply:
        return 0
    if not synology_storage.enabled():
        raise SystemExit("Synology storage is not configured")

    uploaded = skipped = failed = uploaded_bytes = 0
    with synology_storage.client() as api:
        existing = remote_paths(api)
        print(f"remote_existing={len(existing)}", flush=True)
        for index, (reference, path) in enumerate(clips, start=1):
            destination = synology_storage.remote_path(reference)
            if destination in existing:
                skipped += 1
                continue
            try:
                api.upload(path, destination)
                uploaded += 1
                uploaded_bytes += path.stat().st_size
                existing.add(destination)
                print(f"[{index}/{len(clips)}] uploaded={reference}", flush=True)
            except Exception as exc:
                failed += 1
                print(f"[{index}/{len(clips)}] failed={reference} error={exc}", flush=True)

    print(
        f"complete uploaded={uploaded} skipped={skipped} failed={failed} uploaded_bytes={uploaded_bytes}",
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
