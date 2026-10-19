from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import aegisquant.case_cli as case_cli
from aegisquant.case_cli import main
from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.recovery import ObjectStoreRecoveryCommand, ObjectStoreRecoveryReceipt
from aegisquant.object_store import LocalImmutableObjectStore
from aegisquant.object_store.recovery import (
    ObjectStoreRecoveryError,
    object_store_content_manifest_digest,
    run_local_object_store_recovery_drill,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def command(*references: BlobRef) -> ObjectStoreRecoveryCommand:
    return ObjectStoreRecoveryCommand(
        tenant_id="tenant-a",
        drill_id="recovery-drill-a",
        source_content_manifest_digest=object_store_content_manifest_digest(references),
        source_references=references,
        max_total_bytes=1_000,
        initiated_by="human-operator",
        started_at=NOW,
    )


def test_recovery_drill_restores_and_verifies_immutable_objects(tmp_path: Path) -> None:
    source = LocalImmutableObjectStore(tmp_path / "source")
    first = source.put_if_absent(
        tenant_id="tenant-a", data=b"first", media_type="text/plain", retention_class="ops"
    )
    second = source.put_if_absent(
        tenant_id="tenant-a", data=b"second", media_type="text/plain", retention_class="ops"
    )
    target = LocalImmutableObjectStore(tmp_path / "recovered")

    receipt = run_local_object_store_recovery_drill(
        command(first, second), source=source, target=target, completed_at=NOW
    )

    assert receipt.object_count == 2
    assert receipt.source_content_manifest_digest == receipt.recovered_content_manifest_digest
    assert (
        target.get(receipt.recovered_references[0], authenticated_tenant_id="tenant-a") == b"first"
    )


def test_recovery_drill_rejects_same_or_nonempty_target(tmp_path: Path) -> None:
    source = LocalImmutableObjectStore(tmp_path / "source")
    reference = source.put_if_absent(
        tenant_id="tenant-a", data=b"evidence", media_type="text/plain", retention_class="ops"
    )
    request = command(reference)

    with pytest.raises(ObjectStoreRecoveryError, match="different"):
        run_local_object_store_recovery_drill(
            request, source=source, target=source, completed_at=NOW
        )

    target = LocalImmutableObjectStore(tmp_path / "target")
    target.put_if_absent(
        tenant_id="tenant-a", data=b"existing", media_type="text/plain", retention_class="ops"
    )
    with pytest.raises(ObjectStoreRecoveryError, match="empty"):
        run_local_object_store_recovery_drill(
            request, source=source, target=target, completed_at=NOW
        )


def test_recovery_drill_rejects_partial_tenant_inventory(tmp_path: Path) -> None:
    source = LocalImmutableObjectStore(tmp_path / "source")
    first = source.put_if_absent(
        tenant_id="tenant-a", data=b"first", media_type="text/plain", retention_class="ops"
    )
    source.put_if_absent(
        tenant_id="tenant-a", data=b"second", media_type="text/plain", retention_class="ops"
    )

    with pytest.raises(ObjectStoreRecoveryError, match="complete tenant inventory"):
        run_local_object_store_recovery_drill(
            command(first),
            source=source,
            target=LocalImmutableObjectStore(tmp_path / "target"),
            completed_at=NOW,
        )


def test_recovery_drill_rejects_nested_roots(tmp_path: Path) -> None:
    source = LocalImmutableObjectStore(tmp_path / "source")
    reference = source.put_if_absent(
        tenant_id="tenant-a", data=b"evidence", media_type="text/plain", retention_class="ops"
    )

    with pytest.raises(ObjectStoreRecoveryError, match="must not be nested"):
        run_local_object_store_recovery_drill(
            command(reference),
            source=source,
            target=LocalImmutableObjectStore(source.root / "recovered"),
            completed_at=NOW,
        )


def test_recovery_drill_rejects_byte_limit_and_tampered_receipt(tmp_path: Path) -> None:
    source = LocalImmutableObjectStore(tmp_path / "source")
    reference = source.put_if_absent(
        tenant_id="tenant-a", data=b"evidence", media_type="text/plain", retention_class="ops"
    )
    with pytest.raises(ObjectStoreRecoveryError, match="byte limit"):
        run_local_object_store_recovery_drill(
            command(reference).model_copy(update={"max_total_bytes": 1}),
            source=source,
            target=LocalImmutableObjectStore(tmp_path / "target-limit"),
            completed_at=NOW,
        )

    receipt = run_local_object_store_recovery_drill(
        command(reference),
        source=source,
        target=LocalImmutableObjectStore(tmp_path / "target-valid"),
        completed_at=NOW,
    )
    with pytest.raises(ValueError, match="internally inconsistent"):
        ObjectStoreRecoveryReceipt.model_validate(
            receipt.model_dump(mode="python") | {"recovery_digest": "sha256:" + "f" * 64}
        )


def test_recovery_cli_writes_a_receipt_for_a_fresh_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "source"
    source = LocalImmutableObjectStore(source_root)
    reference = source.put_if_absent(
        tenant_id="tenant-a", data=b"evidence", media_type="text/plain", retention_class="ops"
    )
    input_path = tmp_path / "drill.json"
    target_root = tmp_path / "target"
    input_path.write_text(command(reference).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(case_cli, "_now", lambda: NOW)

    assert (
        main(
            [
                "recovery",
                "drill",
                str(input_path),
                "--source-root",
                str(source_root),
                "--target-root",
                str(target_root),
            ]
        )
        == 0
    )
    assert '"object_count": 1' in capsys.readouterr().out
