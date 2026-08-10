import pytest

from aegis.world_model import domain_pack


def manifest(**updates: object) -> domain_pack.DomainPackManifest:
    values: dict[str, object] = {
        "domain_pack_id": "ai-infrastructure",
        "version": "1.0.0",
        "description": "Candidate AI compute and data-centre infrastructure pack.",
        "supported_entities": ("hyperscaler", "accelerator_designer"),
        "supported_variables": ("hyperscaler.ai_capex_growth", "supplier.revenue"),
        "supported_interventions": ("relative_change",),
        "supported_horizons": ("monthly",),
        "twin_ids": ("hyperscaler-twin",),
        "mechanism_model_ids": ("capex-to-demand-v1",),
        "validation_report_id": "validation-ai-infrastructure-v1",
        "coverage_limits": ("US-listed public-company coverage only",),
        "known_failure_modes": ("No release-grade market-data source",),
        "licence_metadata": ("Internal candidate-only implementation",),
        "status": "candidate",
    }
    values.update(updates)
    return domain_pack.DomainPackManifest(**values)


def test_domain_pack_manifest_seals_deterministically() -> None:
    sealed = manifest().sealed()

    assert sealed.content_hash
    assert sealed.sealed().content_hash == sealed.content_hash
    assert domain_pack.DomainPackManifest(**sealed.model_dump()).content_hash == sealed.content_hash


def test_domain_pack_manifest_rejects_missing_known_failure_modes() -> None:
    with pytest.raises(ValueError, match="known_failure_modes"):
        manifest(known_failure_modes=())


def test_domain_pack_manifest_rejects_duplicate_supported_variables() -> None:
    with pytest.raises(ValueError, match="unique"):
        manifest(supported_variables=("hyperscaler.ai_capex_growth", "hyperscaler.ai_capex_growth"))


def test_domain_pack_manifest_rejects_a_mismatched_content_hash() -> None:
    payload = manifest().sealed().model_dump()
    payload["content_hash"] = "d" * 64

    with pytest.raises(ValueError, match="content hash mismatch"):
        domain_pack.DomainPackManifest(**payload)
