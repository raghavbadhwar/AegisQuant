# AegisQuant Point-in-Time Dataset Builder

## Purpose

The PIT data lake reconstructs a sealed historical information world. An artifact is eligible in a simulation at `T` only when `artifact.available_at <= T`. Period end, observation date, and present-day database values are not availability proxies.

This is real-source ingestion infrastructure, not a performance claim. Synthetic data is never acceptable as release, eligibility, or investment-performance evidence.

## Architecture

1. `aegis pit ingest-sec` acquires official SEC submission metadata and original filing bytes under a contact-bearing SEC User-Agent.
2. `RawStore` content-addresses every response and makes capture receipts immutable.
3. `PITArtifact` records source identity, accession, filing/availability times, raw path, hash, parser version, and metadata.
4. `PITAvailabilityLedger` is the central time gate; callers cannot retrieve future artifacts through its query methods.
5. `aegis pit build-snapshot` writes a new immutable local directory containing the manifest, gated artifacts, and applicable historical security records.
6. Offline replay must receive only snapshot contents. A missing snapshot input is a failure, not a reason to consult current web data.

## SEC sources

* EDGAR submissions: `data.sec.gov/submissions/CIK##########.json`, including referenced historical submission files.
* Official ticker/CIK mapping: `www.sec.gov/files/company_tickers.json`.
* Filing documents: `www.sec.gov/Archives/edgar/data/...`.
* Company Facts: `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.

The client requires a contact-bearing User-Agent, follows no redirects, limits itself to 5 requests/second by default (never above 10), retries only transient failures with bounded exponential backoff, and refuses unsafe historic-submission filenames.

## Fact versions and restatements

`normalize_sec_facts` retains every fact version and binds it to its accession. `fundamentals_as_of` selects the latest version public at its cutoff for each `(entity, taxonomy, concept, unit, period_end)` key. A later amended filing cannot overwrite the value visible before its own availability timestamp.

## Snapshot format

```
data/pit/snapshots/2021-09-15T00-00-00Z/
  manifest.json          # hash-bound cutoff, artifact IDs/hashes, warnings
  artifacts.jsonl        # only `available_at <= simulation_at`
  security_master.jsonl  # only historical mappings valid at cutoff
```

The current storage is deliberately canonical JSONL to avoid introducing a second database dependency. Parquet/DuckDB export may be added as a derived representation; it must preserve the same artifact IDs, hashes, availability times, and raw provenance.

## Commands

```bash
uv run python -m apps.cli pit bootstrap --root data/pit
uv run python -m apps.cli pit ingest-sec AAPL MSFT NVDA \
  --sec-user-agent 'AegisQuant research ops@yourdomain.example' --root data/pit
uv run python -m apps.cli pit build-snapshot --at 2021-09-15T16:00:00+00:00 \
  --universe AAPL --universe MSFT --root data/pit
uv run python -m apps.cli pit verify-snapshot data/pit/snapshots/2021-09-15T16-00-00Z
```

`ingest-sec` performs public-source network acquisition only when explicitly invoked. It neither uses synthetic data nor generates investment, release, or performance claims.

## N-PORT and market-data boundaries

N-PORT holdings must store both the portfolio reporting date and separately verified public availability date. Reporting date is never sufficient for PIT visibility. N-PORT archive parsing is intentionally not yet enabled: a source-versioned parser plus archive-specific public-dissemination policy is required before holdings can enter a release-grade snapshot.

SEC does not supply an institutional-quality survivorship-free US price/universe layer. Historical performance validation therefore remains blocked on an approved market-data provider (e.g. CRSP/WRDS or a separately licensed, documented feed). Any temporary engineering feed must be marked non-release and must never qualify a strategy or fund.

## Release checks

The PIT test suite covers future-filing exclusion, causal availability, restatement visibility, immutable snapshot destinations, manifest/hash lineage, and raw capture. Real SEC artifacts and multi-date snapshots must still be acquired before any v3 release qualification can be considered.
