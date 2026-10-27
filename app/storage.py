"""Swappable file storage (DEVELOPMENT_PLAN 1: local dir in dev, private S3-compatible later).
Keys are opaque relative paths; nothing here is publicly served."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("invalid storage key")
        return p

    def put_bytes(self, key: str, data: bytes) -> str:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def put_file(self, key: str, src: Path) -> str:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)
        return key

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()


def get_storage() -> LocalStorage:
    if settings.storage_backend != "local":
        raise RuntimeError(f"storage backend {settings.storage_backend} not implemented yet")
    return LocalStorage(settings.storage_root)
