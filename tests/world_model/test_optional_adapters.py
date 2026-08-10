from aegis.world_model.optional_adapters import probe_optional_adapter


def test_unavailable_optional_adapter_returns_a_sealed_abstention(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("aegis.world_model.optional_adapters.find_spec", lambda _: None)

    result = probe_optional_adapter("pymc")

    assert result.status == "abstained"
    assert result.reason == "dependency_unavailable"
    assert result.authority == "candidate_only"
    assert result.content_hash
