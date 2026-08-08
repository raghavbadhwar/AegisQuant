"""Immutable content-addressed raw capture."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from aegis.contracts import FetchedDocument, RawDocumentReceipt, canonical_json


class RawStoreError(RuntimeError):
    pass


_EXTENSIONS = {
    "text/html": "html",
    "application/json": "json",
    "application/rss+xml": "xml",
    "application/atom+xml": "xml",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/csv": "csv",
    "text/markdown": "md",
    "text/plain": "txt",
    "application/pdf": "pdf",
}


class RawStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def commit(self, fetched: FetchedDocument) -> RawDocumentReceipt:
        digest = hashlib.sha256(fetched.body).hexdigest()
        extension = _EXTENSIONS.get(fetched.media_type.split(";", 1)[0].lower(), "bin")
        body_path = self.root / digest[:2] / f"{digest}.{extension}"
        if body_path.exists():
            if hashlib.sha256(body_path.read_bytes()).hexdigest() != digest:
                raise RawStoreError("content-address collision or raw-store corruption")
        else:
            self._atomic_write(body_path, fetched.body)
        receipt = RawDocumentReceipt(
            source_id=fetched.source_id,
            request_id=fetched.request_id,
            url=fetched.url,
            connector=fetched.connector,
            connector_version=fetched.connector_version,
            status_code=fetched.status_code,
            headers=fetched.headers,
            fetched_at=fetched.fetched_at,
            media_type=fetched.media_type,
            content_hash=digest,
            raw_uri=body_path.as_posix(),
            byte_length=len(fetched.body),
        )
        metadata_path = body_path.with_name(f"{digest}.{fetched.request_id}.json")
        metadata = (canonical_json(receipt) + "\n").encode()
        if metadata_path.exists() and metadata_path.read_bytes() != metadata:
            raise RawStoreError("retrieval metadata is immutable")
        if not metadata_path.exists():
            self._atomic_write(metadata_path, metadata)
        return receipt
