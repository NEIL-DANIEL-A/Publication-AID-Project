from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class JournalRow:
    id: str
    title: str
    print_issn: str
    e_issn: str
    normalized_print: str
    normalized_e: str
    publisher: str
    country: str
    data_hash: str
    created_at: str = ""
    updated_at: str = ""
    first_seen_at: str = ""
    last_checked_at: str = ""
    last_changed_at: Optional[str] = None
    last_seen_pipeline_run_id: Optional[str] = None

    def to_dict(self):
        return asdict(self)
