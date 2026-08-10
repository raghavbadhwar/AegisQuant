# AegisQuant Point-in-Time Dataset Builder

## Purpose

The PIT data lake reconstructs a sealed historical information world. An artifact is eligible in a simulation at `T` only when `artifact.available_at <= T`. Period end, observation date, and present-day database values are not availability proxies.

This is real-source ingestion infrastructure, not a performance claim. Synthetic data is never acceptable as release, eligibility, or investment-performance evidence.

## Architecture

1. `aegis pit ingest-sec` acquires official SEC submission metadata and complete accession submissions under a contact-bearing SEC User-Agent.
2. `RawStore` content-addresses every response and makes capture receipts immutable.
3. `PITArtifact` records source identity, accession, filing/availability times, raw path, hash, parser version, and metadata.
4. `aegis pit import-security-master` raw-captures an explicit dated JSON envelope; current ticker mappings never fabricate historical validity.
5. `PITAvailabilityLedger` is the central time gate; callers cannot retrieve future artifacts or identifier mappings through its query methods.
6. `aegis pit normalize-nport` accepts only a matching retained raw receipt and assigns a conservative observed-publication boundary.
7. `aegis pit build-snapshot` hash-binds gated artifacts, applicable historical security records, selected N-PORT holdings, and retained source copies into a new immutable local directory.
8. Offline replay must receive only snapshot contents. A missing snapshot input is a failure, not a reason to consult current web data.

## SEC sources

* EDGAR submissions: `data.sec.gov/submissions/CIK##########.json`, including referenced historical submission files.
* Official ticker/CIK mapping: `www.sec.gov/files/company_tickers.json`.
* Complete accession submissions: `www.sec.gov/Archives/edgar/data/.../##########.txt`.
* Company Facts remains available as an engineering client method, but normalized ingestion does not use its current cumulative response.

The client requires a contact-bearing User-Agent, follows no redirects, limits itself to 5 requests/second by default (never above 10), retries only transient failures with bounded exponential backoff, and refuses unsafe historic-submission filenames.

## Fact versions and restatements

`parse_archived_xbrl_facts` extracts numeric, non-dimensional facts only from the accession's single `EX-101.INS` document. It requires the archived acceptance timestamp, matching CIK, unique contexts, simple units, and finite values. `normalize_sec_facts` retains every accession version. `fundamentals_as_of` selects the latest version public at its cutoff for each `(entity, taxonomy, concept, unit, period_start, period_end)` key, so an amendment cannot overwrite an earlier PIT value.

## Snapshot format

```
data/pit/snapshots/2021-09-15T00-00-00Z/
  manifest.json          # hash-bound cutoff, artifact IDs/hashes, warnings
  artifacts.jsonl        # only `available_at <= simulation_at`
  security_master.jsonl  # only historical mappings valid at cutoff
  security_sources/      # retained source bytes, keyed and verified by SHA-256
  fund_holdings.jsonl    # only holdings observable by the cutoff
  nport_sources/         # retained N-PORT archives, keyed and verified by SHA-256
```

The current storage is deliberately canonical JSONL to avoid introducing a second database dependency. Parquet/DuckDB export may be added as a derived representation; it must preserve the same artifact IDs, hashes, availability times, and raw provenance.

## Commands

```bash
uv run python -m apps.cli pit bootstrap --root data/pit
uv run python -m apps.cli pit ingest-sec AAPL MSFT NVDA \
  --sec-user-agent 'AegisQuant research ops@yourdomain.example' --root data/pit
uv run python -m apps.cli pit import-security-master \
  --source /path/to/dated-security-history.json --root data/pit
uv run python -m apps.cli pit normalize-nport \
  --archive /path/to/captured-nport.zip --receipt /path/to/raw-receipt.json \
  --series S000000001 --root data/pit
uv run python -m apps.cli pit build-snapshot --at 2021-09-15T16:00:00+00:00 \
  --universe AAPL --universe MSFT --root data/pit
uv run python -m apps.cli pit verify-snapshot data/pit/snapshots/2021-09-15T16-00-00Z
```

`ingest-sec` performs public-source network acquisition only when explicitly invoked. It neither uses synthetic data nor generates investment, release, or performance claims.

The security-master import is local-only. Its envelope must declare source identity/version/availability and explicit `valid_from`/`valid_to` intervals for every mapping. The exact envelope is copied into the content-addressed raw store. Imports may retain a mapping before its declared source-availability time, but snapshot creation rejects it until that time. Overlapping ticker or canonical-security intervals, duplicate/conflicting source-record IDs, missing applicable mappings, retained-source drift, and snapshot hash drift fail closed. Each snapshot retains its own verified copy of the applicable source bytes. The repository does not infer history from the current SEC ticker map.

## N-PORT and market-data boundaries

The narrow quarterly N-PORT parser binds each holding to the SEC primary key `(ACCESSION_NUMBER, HOLDING_ID)`, an exact retained archive receipt, and an independently copied snapshot source. Reporting date is never treated as visibility. Because the bulk holding table lacks a precise dissemination timestamp, availability is conservatively the later of the next UTC day after its filing date and the archive's observed retrieval time. Duplicate identities, receipt/file mismatches, conflicting immutable records, future visibility, holding/hash drift, or retained-source drift fail closed.

This observed-retrieval policy is engineering-only. It does not reconstruct historical dissemination before acquisition, and it cannot establish release-grade N-PORT timing without governed historical publication evidence and externally retained original receipts.

SEC does not supply an institutional-quality survivorship-free US price/universe layer. Historical performance validation therefore remains blocked on an approved market-data provider (e.g. CRSP/WRDS or a separately licensed, documented feed). Any temporary engineering feed must be marked non-release and must never qualify a strategy or fund.

## Release checks

The PIT test suite covers archived acceptance-time binding, malformed submission rejection, dimensional-fact quarantine, future-filing exclusion, restatement visibility, N-PORT receipt/timing/identity binding, immutable snapshot destinations, manifest/hash lineage, and raw capture. A governed real SEC corpus and multi-date externally receipt-bound snapshots must still be acquired before release qualification can be considered.
