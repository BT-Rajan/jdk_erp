import shutil
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol

from app.core.config import settings

# Read/write in chunks so a large file is never fully loaded into
# application memory (docs/modules/file_storage.md #10).
_CHUNK_SIZE = 1024 * 1024


class StorageBackend(Protocol):
    """The one storage interface every module uses
    (docs/modules/file_storage.md #1) -- callers never touch a
    filesystem path or an object-storage SDK directly. Swapping
    LocalStorageBackend for an S3/Azure Blob implementation later
    (docs/modules/file_storage.md #12) means writing one new class here,
    not changing any caller."""

    def upload(self, key: str, stream: BinaryIO) -> int: ...
    def download(self, key: str) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def metadata(self, key: str) -> dict | None: ...


class StorageKeyError(ValueError):
    """A key that would escape the storage root -- defense in depth on
    top of generate_storage_key() only ever producing a flat, random
    name (docs/modules/file_storage.md #3/#9): nothing should ever reach
    this, but a path-joining bug must fail loudly, not silently write
    outside the storage root."""


class LocalStorageBackend:
    """Private local-disk storage (docs/modules/file_storage.md #12's
    "start simple" step) -- outside any public web root, since this app
    serves no static files at all. Every key is resolved and verified to
    stay inside `root` before any filesystem operation, so a malformed
    or malicious key can never write/read/delete outside it."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.FILE_STORAGE_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise StorageKeyError(f"'{key}' would escape the storage root.")
        return path

    def upload(self, key: str, stream: BinaryIO) -> int:
        path = self._resolve(key)
        size = 0
        with path.open("wb") as out:
            while chunk := stream.read(_CHUNK_SIZE):
                out.write(chunk)
                size += len(chunk)
        return size

    def download(self, key: str) -> Iterator[bytes]:
        path = self._resolve(key)
        with path.open("rb") as source:
            while chunk := source.read(_CHUNK_SIZE):
                yield chunk

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def metadata(self, key: str) -> dict | None:
        path = self._resolve(key)
        if not path.is_file():
            return None
        return {"size_bytes": path.stat().st_size}

    def _wipe_for_tests(self) -> None:
        """Test-only: not part of the StorageBackend protocol."""
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


default_storage = LocalStorageBackend()
