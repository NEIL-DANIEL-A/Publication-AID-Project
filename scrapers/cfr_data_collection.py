"""
CFR Data Collection Module.
Scrapes English Journal List records from the CFR Anna University portal:
https://cfr.annauniv.edu/research/academics/english-journals-list.php

Collects records across pages dynamically (with pagination discovery) and extracts:
- Sl.No
- Full Journal Title
- Print-ISSN
- E-ISSN
- Publisher
- Country
"""

import os
import re
import urllib.parse
from typing import List, Optional, Set, Tuple

from scrapling.fetchers import Fetcher
from scrapling.parser import Adaptor

from models import CFRJournal

START_URL = "https://cfr.annauniv.edu/research/academics/english-journals-list.php"
DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "debug")


def save_cfr_debug_html(filename: str, content: str):
    """Save debugging HTML to output/debug/ directory."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, filename)
        with open(filepath, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
        print(f"[INFO] Saved CFR debug HTML: {filepath}")
    except Exception as e:
        print(f"[WARNING] Could not save CFR debug HTML {filename}: {e}")


def clean_cell_text(raw_text: str) -> str:
    """Clean table cell text by removing non-breaking spaces and redundant whitespace."""
    if not raw_text:
        return ""
    # Replace non-breaking space \xa0 with standard space
    cleaned = raw_text.replace("\xa0", " ").strip()
    # Normalize internal whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def find_next_page_url(doc: Adaptor, current_url: str) -> Optional[str]:
    """
    Search for a next-page link across common pagination patterns:
    - rel="next"
    - text matching "next", ">", "»"
    - classes like .next, .page-link with next/forward arrows
    """
    # 1. rel="next"
    for a in doc.css('a[rel="next"], a[rel="Next"]'):
        href = a.attrib.get("href")
        if href:
            return urllib.parse.urljoin(current_url, href)

    # 2. Text inspection of anchor tags
    for a in doc.css("a"):
        text = clean_cell_text(a.text or "").lower()
        aria_label = a.attrib.get("aria-label", "").lower()
        title = a.attrib.get("title", "").lower()
        classes = a.attrib.get("class", "").lower()
        href = a.attrib.get("href", "").strip()

        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        # Check if text or aria-label indicates 'next'
        if any(marker in text for marker in ["next", ">", "»", "next page"]):
            return urllib.parse.urljoin(current_url, href)
        if any(marker in aria_label for marker in ["next", "next page"]):
            return urllib.parse.urljoin(current_url, href)
        if any(marker in title for marker in ["next", "next page"]):
            return urllib.parse.urljoin(current_url, href)
        if "next" in classes and ("page" in classes or "pagination" in classes):
            return urllib.parse.urljoin(current_url, href)

    return None


def parse_cfr_table_rows(doc: Adaptor) -> List[CFRJournal]:
    """
    Extract journal records from CFR HTML table.
    Looks for table with the 6 expected headers:
    Sl.No, Full Journal Title, Print-ISSN, E-ISSN, Publisher, Country.
    """
    journals = []
    tables = doc.css("table")
    if not tables:
        return journals

    target_table = None
    header_col_indices = {}

    for tbl in tables:
        rows = tbl.css("tr")
        if not rows:
            continue
        header_cells = rows[0].css("th, td")
        header_texts = [clean_cell_text(c.text or "").upper() for c in header_cells]

        # Check if table contains journal columns
        has_sl_no = any("SL" in h or "S.NO" in h for h in header_texts)
        has_title = any("TITLE" in h or "JOURNAL" in h for h in header_texts)
        has_issn = any("ISSN" in h for h in header_texts)

        if (has_sl_no and has_title) or has_issn:
            target_table = tbl
            # Build column mapping
            for idx, h in enumerate(header_texts):
                if "SL" in h or "S.NO" in h:
                    header_col_indices.setdefault("sl_no", idx)
                elif "TITLE" in h or "JOURNAL" in h:
                    header_col_indices.setdefault("title", idx)
                elif "PRINT" in h and "ISSN" in h:
                    header_col_indices.setdefault("print_issn", idx)
                elif "E-" in h or "ONLINE" in h or "ELECTRONIC" in h:
                    header_col_indices.setdefault("e_issn", idx)
                elif "PUBLISHER" in h:
                    header_col_indices.setdefault("publisher", idx)
                elif "COUNTRY" in h:
                    header_col_indices.setdefault("country", idx)
            break

    if not target_table:
        target_table = tables[0]

    rows = target_table.css("tr")
    if len(rows) <= 1:
        return journals

    for row in rows[1:]:
        tds = row.css("td")
        if len(tds) < 6:
            continue

        if header_col_indices and len(header_col_indices) >= 5:
            sl_no = clean_cell_text(tds[header_col_indices.get("sl_no", 0)].text or "")
            title = clean_cell_text(tds[header_col_indices.get("title", 1)].text or "")
            p_issn = clean_cell_text(tds[header_col_indices.get("print_issn", 2)].text or "")
            e_issn = clean_cell_text(tds[header_col_indices.get("e_issn", 3)].text or "")
            publisher = clean_cell_text(tds[header_col_indices.get("publisher", 4)].text or "")
            country = clean_cell_text(tds[header_col_indices.get("country", 5)].text or "")
        else:
            sl_no = clean_cell_text(tds[0].text or "")
            title = clean_cell_text(tds[1].text or "")
            p_issn = clean_cell_text(tds[2].text or "")
            e_issn = clean_cell_text(tds[3].text or "")
            publisher = clean_cell_text(tds[4].text or "")
            country = clean_cell_text(tds[5].text or "")

        # Skip rows that might be sub-headers or empty
        if not title and not p_issn and not e_issn:
            continue
        if sl_no.upper() in ["SL.NO", "SL. NO", "S.NO"]:
            continue

        journal = CFRJournal(
            sl_no=sl_no,
            journal_title=title,
            print_issn=p_issn,
            e_issn=e_issn,
            publisher=publisher,
            country=country,
        )
        journals.append(journal)

    return journals


def scrape_cfr_journals(start_url: str = START_URL) -> Tuple[List[CFRJournal], int]:
    """
    Main function to scrape CFR journal records across all pages.
    Returns:
        Tuple[List[CFRJournal], int]: (records, total_pages_scraped)
    """
    all_journals: List[CFRJournal] = []
    visited_urls: Set[str] = set()
    current_url: Optional[str] = start_url
    page_num = 1

    while current_url and current_url not in visited_urls:
        visited_urls.add(current_url)

        try:
            response = Fetcher.get(current_url, verify=False)
            if response.status != 200:
                print(f"[ERROR] Failed to fetch CFR page {page_num} ({current_url}): HTTP {response.status}")
                save_cfr_debug_html(f"cfr_page_{page_num}_error.html", response.text or "")
                break

            # Handle body encoding safely
            raw_body = response.body if hasattr(response, "body") else response.text.encode("utf-8")
            decoded_html = None
            for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
                try:
                    decoded_html = raw_body.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            if decoded_html is None:
                decoded_html = raw_body.decode("latin-1", errors="replace")

            doc = Adaptor(decoded_html)
            page_journals = parse_cfr_table_rows(doc)

            if not page_journals:
                print(f"[WARNING] CFR page {page_num}: 0 journals extracted from {current_url}")
                save_cfr_debug_html(f"cfr_page_{page_num}.html", decoded_html)
            else:
                print(f"[INFO] CFR page {page_num}: {len(page_journals)} journals")
                all_journals.extend(page_journals)

            # Check pagination for next page
            next_url = find_next_page_url(doc, current_url)
            if next_url and next_url not in visited_urls:
                current_url = next_url
                page_num += 1
            else:
                current_url = None

        except Exception as e:
            print(f"[ERROR] Exception occurred on CFR page {page_num} ({current_url}): {e}")
            save_cfr_debug_html(f"cfr_page_{page_num}_exception.html", str(e))
            break

    print("\n[SUCCESS] CFR collection complete")
    print(f"Total pages: {len(visited_urls)}")
    print(f"Total journals: {len(all_journals)}")

    return all_journals, len(visited_urls)
