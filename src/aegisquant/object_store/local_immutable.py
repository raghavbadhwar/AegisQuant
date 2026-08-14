"""Credential-free immutable local object backend for M0 tests."""

from __future__ import annotations

import os
from pathlib import Path

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import Identifier
from aegisquant.security.digests import sha256_bytes


class ObjectIntegrityError(IOError):
    pass


class LocalImmutableObjectStore:
    """Content-addressed local backend; not a regulatory WORM claim."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, tenant_id: Identifier, digest: str) -> Path:
        hex_digest = digest.removeprefix("sha256:")
        return self._root / tenant_id / "sha256" / hex_digest[:2] / hex_digest

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(path, 0o400)

    def put_if_absent(
        self,
        *,
        tenant_id: Identifier,
        data: bytes,
        media_type: str,
        retention_class: Identifier,
    ) -> BlobRef:
        digest = sha256_bytes(data)
        path = self._path(tenant_id, digest)
        metadata_path = path.with_name(f"{path.name}.metadata.json")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidate = BlobRef(
            tenant_id=tenant_id,
            uri=path.as_uri(),
            content_digest=digest,
            size_bytes=len(data),
            media_type=media_type,
            retention_class=retention_class,
        )
        try:
            self._write_exclusive(path, data)
        except FileExistsError:
            if not metadata_path.exists():
                raise ObjectIntegrityError("existing object has no immutable metadata") from None
            existing_data = path.read_bytes()
            existing_metadata = BlobRef.model_validate_json(metadata_path.read_bytes())
            if (
                sha256_bytes(existing_data) != digest
                or existing_data != data
                or existing_metadata != candidate
            ):
                raise ObjectIntegrityError(
                    "existing content-addressed object or metadata failed verification"
                ) from None
            return existing_metadata
        try:
            self._write_exclusive(metadata_path, candidate.model_dump_json().encode())
        except BaseException:
            path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            raise
        return candidate

    def get(self, reference: BlobRef, *, authenticated_tenant_id: Identifier) -> bytes:
        if reference.tenant_id != authenticated_tenant_id:
            raise ObjectIntegrityError("authenticated tenant does not own the object reference")
        path = self._path(reference.tenant_id, reference.content_digest)
        metadata_path = path.with_name(f"{path.name}.metadata.json")
        if path.as_uri() != reference.uri:
            raise ObjectIntegrityError("object URI is not the canonical content address")
        if not metadata_path.exists():
            raise ObjectIntegrityError("object metadata is missing")
        stored_reference = BlobRef.model_validate_json(metadata_path.read_bytes())
        if stored_reference != reference:
            raise ObjectIntegrityError("object metadata does not match the authoritative reference")
        data = path.read_bytes()
        if len(data) != reference.size_bytes or sha256_bytes(data) != reference.content_digest:
            raise ObjectIntegrityError("object content or size failed verification")
        return data
