from dataclasses import dataclass, asdict
from typing import Optional


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
