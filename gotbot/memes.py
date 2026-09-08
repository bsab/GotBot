"""Bounded image downloads and a refreshable S3 catalogue."""

from dataclasses import dataclass
from pathlib import PurePosixPath
import random
from threading import Lock
import time
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError


MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class EmptyMemeLibrary(Exception):
    """The configured S3 prefix contains no supported photos."""


class MemeStorageError(Exception):
    """The meme library is temporarily unavailable."""


@dataclass(frozen=True)
class Meme:
    filename: str
    content: bytes


class S3MemeRepository:
    def __init__(self, client: Any, bucket: str, prefix: str = "", cache_ttl: int = 300):
        self._client = client
        self._bucket = bucket
        self._prefix = prefix
        self._cache_ttl = cache_ttl
        self._keys: tuple[str, ...] = ()
        self._expires_at = 0.0
        self._lock = Lock()

    def _choose_key(self) -> str:
        with self._lock:
            if time.monotonic() >= self._expires_at:
                paginator = self._client.get_paginator("list_objects_v2")
                keys = []
                for page in paginator.paginate(Bucket=self._bucket, Prefix=self._prefix):
                    for item in page.get("Contents", []):
                        key = item["Key"]
                        if (
                            PurePosixPath(key).suffix.lower() in PHOTO_EXTENSIONS
                            and 0 < item.get("Size", 0) <= MAX_PHOTO_BYTES
                        ):
                            keys.append(key)
                self._keys = tuple(keys)
                self._expires_at = time.monotonic() + self._cache_ttl
            if not self._keys:
                raise EmptyMemeLibrary("No supported photos in the meme library.")
            return random.choice(self._keys)

    def random_meme(self) -> Meme:
        try:
            key = self._choose_key()
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                content = body.read(MAX_PHOTO_BYTES + 1)
            finally:
                body.close()
            if not content or len(content) > MAX_PHOTO_BYTES:
                self.invalidate()
                raise MemeStorageError("The selected photo has an unsupported size.")
            return Meme(filename=PurePosixPath(key).name, content=content)
        except (BotoCoreError, ClientError, OSError) as exc:
            self.invalidate()
            raise MemeStorageError("Unable to retrieve a meme from S3.") from exc

    def invalidate(self) -> None:
        with self._lock:
            self._expires_at = 0.0
