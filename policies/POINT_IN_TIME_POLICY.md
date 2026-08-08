# Point-in-Time Policy

`available_at` is the sole historical eligibility cutoff. Every normalized provider response is revalidated locally; report period, event time, publication date, retrieval time, and current cache state are not substitutes. Replay and historical snapshots reject future evidence, future memory, current-universe leakage, missing held marks, stale held marks, ambiguous timestamps, and cache manifests that do not bind mode/as-of/schema/content hashes.
