"""Point-in-time, source-provenanced historical dataset acquisition."""

from .fundamentals import PITFundamentalFact, fundamentals_as_of, normalize_sec_facts
from .ledger import PITAvailabilityLedger, PITLedgerError, load_snapshot
from .models import PITArtifact, PITSnapshotManifest, SecurityMasterRecord
from .nport import (
    NPortHolding,
    acquire_nport_archive,
    normalize_nport_holdings,
    nport_archive_url,
)
from .sec import (
    SecFactObservation,
    SecFiling,
    SecPITClient,
    SecPITError,
    archived_acceptance_time,
    parse_archived_xbrl_facts,
    select_available_filings,
)

__all__ = [
    "NPortHolding",
    "PITArtifact",
    "PITAvailabilityLedger",
    "PITFundamentalFact",
    "PITLedgerError",
    "PITSnapshotManifest",
    "SecFactObservation",
    "SecFiling",
    "SecPITClient",
    "SecPITError",
    "SecurityMasterRecord",
    "acquire_nport_archive",
    "archived_acceptance_time",
    "fundamentals_as_of",
    "load_snapshot",
    "normalize_nport_holdings",
    "normalize_sec_facts",
    "nport_archive_url",
    "parse_archived_xbrl_facts",
    "select_available_filings",
]
