"""Where Library files are kept for download.

`LocalStorage` writes under a folder on the server (development, single server).
`S3Storage` uses any S3-compatible store (production). Files are never served straight
from the user's computer: a copy is stored when the item is added.
"""

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any, Protocol

from crew.config import Settings


class StorageError(Exception):
    """The file could not be stored or read. The message is safe to show."""


class Storage(Protocol):
    name: str

    async def put(self, key: str, data: bytes, mime: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def make_key(user_id: uuid.UUID, item_id: uuid.UUID, filename: str) -> str:
    """One folder per user; the name is cleaned so it can never climb out of it."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")[:80] or "file"
    return f"{user_id}/{item_id}/{safe}"


class LocalStorage:
    name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise StorageError("That file is not in the Library.")
        return path

    async def put(self, key: str, data: bytes, mime: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError("That file is no longer in storage.")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))


class S3Storage:
    """S3 or anything that speaks its API. Needs the `aws` extra (boto3)."""

    name = "s3"

    def __init__(self, settings: Settings, client: Any = None) -> None:
        self._bucket = settings.s3_bucket
        if client is None:
            try:
                import boto3  # type: ignore[import-not-found]
            except ImportError as error:
                raise StorageError(
                    "LIBRARY_STORAGE=s3 needs boto3 (install the `aws` extra)."
                ) from error
            client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint or None,
                aws_access_key_id=settings.s3_access_key or None,
                aws_secret_access_key=settings.s3_secret_key or None,
            )
        self._client = client

    async def put(self, key: str, data: bytes, mime: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=mime
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
            return body

        try:
            return await asyncio.to_thread(read)
        except Exception as error:
            raise StorageError("That file is no longer in storage.") from error

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)


def create_storage(settings: Settings) -> Storage:
    if settings.library_storage == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.library_dir)
