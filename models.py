from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class CFRJournal:
    sl_no: str
    journal_title: str
    print_issn: str
    e_issn: str
    publisher: str
    country: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScopusVerificationResult:
    scopus_status: str              # Active / Indexed, Inactive, Discontinued, Not Indexed, Unable to Verify
    match_type: str                 # Print ISSN, E-ISSN, No Match
    sourcerecord_id: str = "no data"
    source_title: str = "no data"
    scopus_issn: str = "no data"
    scopus_eissn: str = "no data"
    scopus_publisher: str = "no data"
    scopus_coverage: str = "no data"
    raw_active_status: str = "no data"
    raw_discontinued_flag: str = "no data"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MJLVerificationResult:
    """Result of a Clarivate Master Journal List (MJL) lookup for a single journal."""
    mjl_status: str                     # "Found", "Not Found", "Unable to Verify"
    mjl_index: str = "no data"          # e.g. "SCIE", "SSCI", "ESCI", "AHCI", or "no data"
    mjl_issn_used: str = "no data"      # Which ISSN was searched
    mjl_match_type: str = "No Match"    # "Print ISSN", "E-ISSN", "No Match"
    mjl_source_title: str = "no data"   # Journal title from MJL response

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class JournalResult:
    issn: str
    journal_id: str
    sjr: str
    quartile: str
    h_index: str
    coverage: str
    search_url: str
    journal_url: str
    status: str
    error: Optional[str] = None
    execution_time: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
