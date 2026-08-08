import os
from pathlib import Path

import pytest

from aegisquant.object_store import LocalImmutableObjectStore, ObjectIntegrityError


def test_local_object_store_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    first = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"immutable evidence",
        media_type="text/plain",
        retention_class="research-7y",
    )
    repeated = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"immutable evidence",
        media_type="text/plain",
        retention_class="research-7y",
    )
    assert first == repeated
    assert store.get(first, authenticated_tenant_id="tenant-a") == b"immutable evidence"


def test_tampering_is_detected(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    reference = store.put_if_absent(
        tenant_id="tenant-a",
        data=b"original",
        media_type="application/octet-stream",
        retention_class="test",
    )
    path = Path(reference.uri.removeprefix("file://"))
    os.chmod(path, 0o600)
    path.write_bytes(b"tampered")
    with pytest.raises(ObjectIntegrityError, match="failed verification"):
        store.get(reference, authenticated_tenant_id="tenant-a")


def test_tenant_scopes_change_content_address(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    a = store.put_if_absent(
        tenant_id="tenant-a", data=b"same", media_type="text/plain", retention_class="test"
    )
    b = store.put_if_absent(
        tenant_id="tenant-b", data=b"same", media_type="text/plain", retention_class="test"
    )
    assert a.uri != b.uri


def test_metadata_cannot_be_downgraded_for_existing_content(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    store.put_if_absent(
        tenant_id="tenant-a",
        data=b"same content",
        media_type="text/plain",
        retention_class="research-7y",
    )
    with pytest.raises(ObjectIntegrityError, match="metadata failed verification"):
        store.put_if_absent(
            tenant_id="tenant-a",
            data=b"same content",
            media_type="application/octet-stream",
            retention_class="ephemeral",
        )


def test_authenticated_tenant_is_required_to_read(tmp_path: Path) -> None:
    store = LocalImmutableObjectStore(tmp_path)
    reference = store.put_if_absent(
        tenant_id="tenant-a", data=b"private", media_type="text/plain", retention_class="test"
    )
    with pytest.raises(ObjectIntegrityError, match="does not own"):
        store.get(reference, authenticated_tenant_id="tenant-b")
