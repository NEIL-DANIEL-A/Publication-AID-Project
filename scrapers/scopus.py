import logging
import os
import sys
import time
from typing import Dict, List, Tuple

import pandas as pd

from models import CFRJournal, ScopusVerificationResult
from processors.issn import normalize_issn

logger = logging.getLogger(__name__)

# Expected column names in Scopus Source Title List Excel
COL_SOURCERECORD_ID = "Sourcerecord ID"
COL_SOURCE_TITLE = "Source Title"
COL_ISSN = "ISSN"
COL_EISSN = "EISSN"
COL_ACTIVE_STATUS = "Active or Inactive"
COL_COVERAGE = "Coverage"
COL_DISCONTINUED = "Titles Discontinued by Scopus"
COL_PUBLISHER = "Publisher"

REQUIRED_COLUMNS = [
    COL_SOURCERECORD_ID,
    COL_SOURCE_TITLE,
    COL_ISSN,
    COL_EISSN,
    COL_ACTIVE_STATUS,
    COL_COVERAGE,
    COL_DISCONTINUED,
    COL_PUBLISHER,
]


class ScopusVerifier:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
        self.issn_map: Dict[str, dict] = {}
        self.load_time: float = 0.0
        self.construction_time: float = 0.0
        self.sheet_name: str = ""
        self._load_and_build_index()

    def _validate_source_file(self, xl: pd.ExcelFile):
        """Validate file existence, sheet presence, and required column headers."""
        if not os.path.exists(self.excel_path):
            raise FileNotFoundError(f"[ERROR] Scopus Source Title List file not found: {self.excel_path}")

        # Find the primary Scopus Sources sheet
        target_sheet = None
        for sheet in xl.sheet_names:
            if sheet.startswith("Scopus Sources"):
                target_sheet = sheet
                break

        if not target_sheet:
            raise ValueError(
                f"[ERROR] No sheet starting with 'Scopus Sources' found in {self.excel_path}. "
                f"Available sheets: {xl.sheet_names}"
            )

        self.sheet_name = target_sheet

    def _load_and_build_index(self):
        """Loads Scopus Excel sheet ONCE and builds in-memory lookup map."""
        if not os.path.exists(self.excel_path):
            raise FileNotFoundError(f"[ERROR] Scopus Source Title List file not found: {self.excel_path}")

        t0 = time.perf_counter()
        xl = pd.ExcelFile(self.excel_path)
        self._validate_source_file(xl)

        df = pd.read_excel(xl, sheet_name=self.sheet_name, header=0, dtype=str)
        t1 = time.perf_counter()
        self.load_time = t1 - t0

        # Validate required column headers
        missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing_cols:
            raise KeyError(
                f"[ERROR] Required columns missing from sheet '{self.sheet_name}': {missing_cols}. "
                f"Available columns: {list(df.columns)}"
            )

        # Build ISSN lookup map with duplicate tracking
        t_const_start = time.perf_counter()
        seen_p_issns: Dict[str, dict] = {}
        seen_e_issns: Dict[str, dict] = {}

        for idx, row in df.iterrows():
            raw_p = str(row[COL_ISSN]) if pd.notna(row[COL_ISSN]) else ""
            raw_e = str(row[COL_EISSN]) if pd.notna(row[COL_EISSN]) else ""

            norm_p = normalize_issn(raw_p)
            norm_e = normalize_issn(raw_e)

            raw_active = str(row[COL_ACTIVE_STATUS]).strip() if pd.notna(row[COL_ACTIVE_STATUS]) else ""
            raw_disc = str(row[COL_DISCONTINUED]).strip() if pd.notna(row[COL_DISCONTINUED]) else ""

            # Classify Scopus Indexing Status
            if raw_disc == "Discontinued by Scopus":
                scopus_status = "Discontinued"
            elif raw_active == "Active":
                scopus_status = "Active / Indexed"
            elif raw_active == "Inactive":
                scopus_status = "Inactive"
            elif raw_active or raw_disc:
                scopus_status = "Unable to Verify"
            else:
                scopus_status = "Not Indexed"

            record = {
                "sourcerecord_id": str(row[COL_SOURCERECORD_ID]) if pd.notna(row[COL_SOURCERECORD_ID]) else "no data",
                "source_title": str(row[COL_SOURCE_TITLE]) if pd.notna(row[COL_SOURCE_TITLE]) else "no data",
                "scopus_issn": raw_p or "no data",
                "scopus_eissn": raw_e or "no data",
                "scopus_publisher": str(row[COL_PUBLISHER]) if pd.notna(row[COL_PUBLISHER]) else "no data",
                "scopus_coverage": str(row[COL_COVERAGE]) if pd.notna(row[COL_COVERAGE]) else "no data",
                "raw_active_status": raw_active or "no data",
                "raw_discontinued_flag": raw_disc or "no data",
                "scopus_status": scopus_status,
            }

            # Safe duplicate handling & mapping
            if norm_p != "no data":
                if norm_p in seen_p_issns:
                    logger.warning(
                        f"[WARNING] Duplicate Print-ISSN '{norm_p}' in Scopus dataset! "
                        f"Existing: {seen_p_issns[norm_p]['source_title']} vs New: {record['source_title']}"
                    )
                else:
                    seen_p_issns[norm_p] = record
                self.issn_map[norm_p] = record

            if norm_e != "no data":
                if norm_e in seen_e_issns:
                    logger.warning(
                        f"[WARNING] Duplicate E-ISSN '{norm_e}' in Scopus dataset! "
                        f"Existing: {seen_e_issns[norm_e]['source_title']} vs New: {record['source_title']}"
                    )
                else:
                    seen_e_issns[norm_e] = record
                # Note: If Print-ISSN already mapped this key, Print-ISSN takes precedence in key index
                if norm_e not in self.issn_map:
                    self.issn_map[norm_e] = record

        t_const_end = time.perf_counter()
        self.construction_time = t_const_end - t_const_start

    def verify_journal(self, journal: CFRJournal) -> ScopusVerificationResult:
        """Verify a single CFRJournal against the Scopus dataset."""
        norm_p = normalize_issn(journal.print_issn)
        norm_e = normalize_issn(journal.e_issn)

        match_record = None
        match_type = "No Match"

        # 1. Try Print-ISSN first
        if norm_p != "no data" and norm_p in self.issn_map:
            match_record = self.issn_map[norm_p]
            match_type = "Print ISSN"

        # 2. Try E-ISSN fallback if no match
        elif norm_e != "no data" and norm_e in self.issn_map:
            match_record = self.issn_map[norm_e]
            match_type = "E-ISSN"

        if match_record:
            return ScopusVerificationResult(
                scopus_status=match_record["scopus_status"],
                match_type=match_type,
                sourcerecord_id=match_record["sourcerecord_id"],
                source_title=match_record["source_title"],
                scopus_issn=match_record["scopus_issn"],
                scopus_eissn=match_record["scopus_eissn"],
                scopus_publisher=match_record["scopus_publisher"],
                scopus_coverage=match_record["scopus_coverage"],
                raw_active_status=match_record["raw_active_status"],
                raw_discontinued_flag=match_record["raw_discontinued_flag"],
            )

        # No match found
        return ScopusVerificationResult(
            scopus_status="Not Indexed",
            match_type="No Match",
        )


def verify_scopus_indexing(
    journals: List[CFRJournal], source_file: str
) -> Tuple[List[Tuple[CFRJournal, ScopusVerificationResult]], dict]:
    """
    Exposed functional API to verify a list of CFRJournal records against Scopus Source Title List.

    Returns:
        - List of (CFRJournal, ScopusVerificationResult) tuples
        - Timing & statistics dict
    """
    verifier = ScopusVerifier(source_file)

    t_verify_start = time.perf_counter()
    verified_results = []
    for journal in journals:
        res = verifier.verify_journal(journal)
        verified_results.append((journal, res))
    t_verify_end = time.perf_counter()

    verify_time = t_verify_end - t_verify_start
    total_scopus_time = verifier.load_time + verifier.construction_time + verify_time

    stats = {
        "dataset_load_time": verifier.load_time,
        "construction_time": verifier.construction_time,
        "verification_time": verify_time,
        "total_scopus_time": total_scopus_time,
        "per_journal_time": verify_time / len(journals) if journals else 0.0,
        "total_journals": len(journals),
        "active_indexed": sum(1 for _, r in verified_results if r.scopus_status == "Active / Indexed"),
        "inactive": sum(1 for _, r in verified_results if r.scopus_status == "Inactive"),
        "discontinued": sum(1 for _, r in verified_results if r.scopus_status == "Discontinued"),
        "not_indexed": sum(1 for _, r in verified_results if r.scopus_status == "Not Indexed"),
        "unable_to_verify": sum(1 for _, r in verified_results if r.scopus_status == "Unable to Verify"),
    }

    return verified_results, stats
