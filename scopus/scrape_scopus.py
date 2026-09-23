"""
Scopus Journal Details Scraper
Using Scrapling (https://github.com/D4Vinci/Scrapling)

Extracts accurate journal metrics and metadata from Scopus:
- Journal Name
- Publisher
- ISSN
- E-ISSN
- Subject Area
- CiteScore
- SJR
- SNIP

Missing values are represented strictly as 'N/A' (or 'no data'). No random/fabricated values.
"""

import argparse
import csv
import os
import re
import sys
import time
from typing import Dict, List, Optional
from scrapling import DynamicFetcher


def extract_issns_from_text(text: str) -> tuple[str, str]:
    """
    Extracts ISSN and E-ISSN from text using robust lookbehind regex.
    """
    m_issn = re.search(r'(?<![E\w-])ISSN:\s*([0-9Xx]{4}-[0-9Xx]{4})', text)
    issn = m_issn.group(1).strip() if m_issn else "N/A"

    m_eissn = re.search(r'E-ISSN:\s*([0-9Xx]{4}-[0-9Xx]{4})', text)
    eissn = m_eissn.group(1).strip() if m_eissn else "N/A"

    return issn, eissn


def extract_journal_details(page, fallback_title: str = "N/A") -> Dict[str, str]:
    """
    Extracts all requested metadata and metrics from a Scopus source detail page.
    """
    page.wait_for_timeout(2500)  # Wait for dynamic metric elements to populate

    # 1. Journal Name
    journal_name = "N/A"
    title_el = page.query_selector("h2")
    if title_el:
        t = title_el.inner_text().strip()
        # Ensure it's not a metric header or cookie modal
        if t and not any(k in t for k in ["CiteScore", "SJR", "SNIP", "Cookie", "Sign in"]):
            journal_name = t

    if journal_name == "N/A":
        # Fallback to document header or fallback_title
        j_elem = page.query_selector(".documentHeader, #pageTitleHeader")
        if j_elem:
            journal_name = j_elem.inner_text().strip()
        else:
            journal_name = fallback_title

    # 2. Publisher
    publisher = "N/A"
    pub_el = page.query_selector("li:has-text('Publisher:') span.right")
    if pub_el:
        publisher = pub_el.inner_text().strip()
    else:
        # Regex search in body/list
        page_text = page.inner_text("body")
        pub_m = re.search(r'Publisher:\s*([^\n\r]+)', page_text)
        if pub_m:
            publisher = pub_m.group(1).strip()
    if not publisher:
        publisher = "N/A"

    # 3. ISSN and E-ISSN
    # Check all LI elements or page text for ISSN / E-ISSN
    issn, eissn = "N/A", "N/A"
    for li in page.query_selector_all("li"):
        li_text = li.inner_text().strip()
        if "ISSN" in li_text:
            cur_issn, cur_eissn = extract_issns_from_text(li_text)
            if cur_issn != "N/A":
                issn = cur_issn
            if cur_eissn != "N/A":
                eissn = cur_eissn

    if issn == "N/A" and eissn == "N/A":
        page_text = page.inner_text("body")
        issn, eissn = extract_issns_from_text(page_text)

    # 4. Subject Area
    badges = [b.inner_text().strip() for b in page.query_selector_all("#csSubjContainer .badges, #SA .badges, [id*='subject'] .badges")]
    badges = [b for b in badges if b]
    if badges:
        subject_area = "; ".join(badges)
    else:
        # Fallback to #SA text or subject area list
        sa_el = page.query_selector("#SA")
        if sa_el:
            raw_sa = sa_el.inner_text().replace("Subject area:", "").strip()
            subject_area = raw_sa if raw_sa else "N/A"
        else:
            subject_area = "N/A"

    # 5. Metrics (CiteScore, SJR, SNIP)
    citescore, sjr, snip = "N/A", "N/A", "N/A"
    for h2 in page.query_selector_all("h2"):
        t = h2.inner_text().strip()
        lines = [line.strip() for line in t.splitlines() if line.strip()]
        if len(lines) >= 2:
            header, val = lines[0], lines[1]
            if "CiteScore" in header and "rank" not in header.lower():
                citescore = val
            elif "SJR" in header:
                sjr = val
            elif "SNIP" in header:
                snip = val

    return {
        "Journal Name": journal_name if journal_name else "N/A",
        "Publisher": publisher if publisher else "N/A",
        "ISSN": issn if issn else "N/A",
        "E-ISSN": eissn if eissn else "N/A",
        "Subject Area": subject_area if subject_area else "N/A",
        "CiteScore": citescore if citescore else "N/A",
        "SJR": sjr if sjr else "N/A",
        "SNIP": snip if snip else "N/A"
    }


def scrape_scopus_journals(limit: int = 20, output_csv: str = "scopus_journals.csv", source_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """
    Launches Scrapling DynamicFetcher to scrape Scopus journal sources and details.
    """
    scraped_records: List[Dict[str, str]] = []

    def session_action(page):
        page.wait_for_timeout(3000)
        
        # Determine targets
        targets: List[tuple[str, str]] = []  # (title, url)

        if source_ids:
            for sid in source_ids:
                targets.append((f"Source {sid}", f"https://www.scopus.com/sourceid/{sid}"))
        else:
            print(f"Loading Scopus Sources list to extract top {limit} journals...", flush=True)
            # If limit > 20, we can adjust resultsPerPage
            if limit > 20:
                try:
                    target_opt = "50" if limit <= 50 else ("100" if limit <= 100 else "200")
                    page.select_option("#sourceResults-resultsPerPage", target_opt)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

            rows = page.query_selector_all("#sourceResults tbody tr")
            print(f"Found {len(rows)} journals in table.", flush=True)
            for r in rows[:limit]:
                link = r.query_selector("td:nth-child(2) a")
                if link:
                    title = link.inner_text().strip()
                    href = link.get_attribute("href")
                    if href:
                        full_url = f"https://www.scopus.com{href}" if href.startswith("/") else href
                        targets.append((title, full_url))

        print(f"\n[+] Total journals to scrape: {len(targets)}", flush=True)
        
        # Iterate through targets in the same browser session
        for idx, (fallback_title, url) in enumerate(targets, 1):
            print(f"[{idx}/{len(targets)}] Scraping: {fallback_title} -> {url}", flush=True)
            t0 = time.time()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                details = extract_journal_details(page, fallback_title=fallback_title)
                elapsed = time.time() - t0
                print(f"    Done in {elapsed:.2f}s | ISSN: {details['ISSN']} | E-ISSN: {details['E-ISSN']} | CiteScore: {details['CiteScore']} | SJR: {details['SJR']} | SNIP: {details['SNIP']}", flush=True)
                scraped_records.append(details)
            except Exception as e:
                print(f"    [!] Error scraping {url}: {e}", flush=True)
                scraped_records.append({
                    "Journal Name": fallback_title,
                    "Publisher": "N/A",
                    "ISSN": "N/A",
                    "E-ISSN": "N/A",
                    "Subject Area": "N/A",
                    "CiteScore": "N/A",
                    "SJR": "N/A",
                    "SNIP": "N/A"
                })

    start_url = "https://www.scopus.com/sources.uri"
    DynamicFetcher.fetch(start_url, page_action=session_action)

    # Save to CSV
    if scraped_records:
        fieldnames = [
            "Journal Name",
            "Publisher",
            "ISSN",
            "E-ISSN",
            "Subject Area",
            "CiteScore",
            "SJR",
            "SNIP"
        ]
        with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for record in scraped_records:
                writer.writerow(record)
        print(f"\n[+] Successfully saved {len(scraped_records)} journals to {output_csv}", flush=True)

    return scraped_records


def main():
    parser = argparse.ArgumentParser(description="Scrape Scopus Journal metadata and metrics using Scrapling.")
    parser.add_argument("--limit", type=int, default=20, help="Number of journals to scrape from Scopus sources list (default: 20)")
    parser.add_argument("--output", type=str, default="scopus_journals.csv", help="Output CSV filepath (default: scopus_journals.csv)")
    parser.add_argument("--source-ids", nargs="*", help="Optional list of specific Scopus source IDs to scrape (e.g. 28773 20315)")

    args = parser.parse_args()
    scrape_scopus_journals(limit=args.limit, output_csv=args.output, source_ids=args.source_ids)


if __name__ == "__main__":
    main()
