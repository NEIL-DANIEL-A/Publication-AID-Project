import logging
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from config.urls import DEBUG_SUBDIR, OUTPUT_DIR_NAME, SCIMAGO_JOURNAL_BASE as JOURNAL_BASE_URL, SCIMAGO_SEARCH_BASE as SEARCH_BASE_URL
from scrapling.core.utils._utils import log as scrapling_log
from scrapling.fetchers import Fetcher, StealthySession
from models import JournalResult
from processors.issn import normalize_issn

# Silence Scrapling's verbose internal fetch logs
scrapling_log.setLevel(logging.WARNING)

DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), OUTPUT_DIR_NAME, DEBUG_SUBDIR)


def is_challenge_page(text: str) -> bool:
    """Detect if the page is a Cloudflare / bot security challenge page."""
    challenge_indicators = [
        "just a moment",
        "turnstile",
        "challenge-platform",
        "checking your browser",
        "access denied",
        "cf-challenge",
    ]
    lower_text = text.lower()
    return any(indicator in lower_text for indicator in challenge_indicators)


def _page_setup(page):
    """Ensure fast browser navigation by using domcontentloaded for goto and load_state."""
    orig_wait = page.wait_for_load_state

    def fast_wait(state="load", **kwargs):
        if state == "load":
            state = "domcontentloaded"
        return orig_wait(state=state, **kwargs)

    page.wait_for_load_state = fast_wait

    orig_goto = page.goto

    def fast_goto(url, **kwargs):
        kwargs.setdefault("wait_until", "domcontentloaded")
        return orig_goto(url, **kwargs)

    page.goto = fast_goto


class ScimagoScraper:
    def __init__(self, headless: bool = True, verbose: bool = True):
        self.headless = headless
        self.verbose = verbose
        self._stealth_session: Optional[StealthySession] = None
        self._stealth_lock = threading.RLock()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self):
        """Initialize scraper resources."""
        pass

    def close(self):
        """Close stealth browser session if initialized."""
        if self._stealth_session is not None:
            try:
                self._stealth_session.__exit__(None, None, None)
            except Exception:
                try:
                    self._stealth_session.close()
                except Exception:
                    pass
            self._stealth_session = None
            if self.verbose:
                print("[INFO] Browser session closed.")

    def _get_stealth_session(self) -> StealthySession:
        with self._stealth_lock:
            if self._stealth_session is None:
                if self.verbose:
                    print("[INFO] Initializing fallback browser session...")
                raw_session = StealthySession(
                    headless=self.headless,
                    max_pages=5,
                    disable_resources=True,
                    page_setup=_page_setup,
                    timeout=10000,
                    retries=2,
                    solve_cloudflare=True,
                )
                self._stealth_session = raw_session.__enter__()
            return self._stealth_session

    def save_debug_html(self, filename: str, content: str):
        """Save HTML response to debug directory for diagnostic analysis."""
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            filepath = os.path.join(DEBUG_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            if self.verbose:
                print(f"[INFO] Saved debug HTML to {filepath}")
        except Exception as e:
            if self.verbose:
                print(f"[WARNING] Could not save debug file {filename}: {e}")

    def fetch_url(self, url: str):
        """
        Fetch URL using fast HTTP Fetcher first.
        Fallback to StealthySession if a security challenge is detected or status is non-200.
        Thread-safe: StealthySession access is serialized via RLock.
        """
        try:
            res = Fetcher.get(url)
            if res.status == 200 and not is_challenge_page(res.text):
                return res
            if self.verbose:
                print(f"[INFO] Security challenge or HTTP {res.status}. Switching to stealth browser for {url}...")
            with self._stealth_lock:
                session = self._get_stealth_session()
                return session.fetch(url, disable_resources=True)
        except Exception as e:
            if self.verbose:
                print(f"[WARNING] HTTP fetch failed for {url} ({e}). Retrying with stealth browser...")
            with self._stealth_lock:
                session = self._get_stealth_session()
                return session.fetch(url, disable_resources=True)

    def search_scimago(self, issn: str):
        """Open SCImago journal search URL."""
        search_url = SEARCH_BASE_URL.format(issn=issn)
        if self.verbose:
            print(f"[INFO] Visiting search URL: {search_url}")
        response = self.fetch_url(search_url)
        return response, search_url

    def extract_journal_id(self, response, issn: str) -> Optional[str]:
        """
        Extract numeric SCImago journal ID from search results page.
        Parses query parameters (param 'q') from hrefs matching journalsearch.php with tip=sid.
        """
        if is_challenge_page(response.text):
            if self.verbose:
                print("[WARNING] SCImago security / challenge page detected on search.")
            self.save_debug_html(f"challenge_search_{issn}.html", response.text)
            return None

        # Search for anchor links pointing to journal page
        for a in response.css("a"):
            href = a.attrib.get("href", "")
            if "journalsearch.php" in href and "tip=sid" in href:
                parsed = urllib.parse.urlparse(href)
                params = urllib.parse.parse_qs(parsed.query)
                q_val = params.get("q", [""])[0]
                if q_val.isdigit():
                    return q_val

        # Secondary search if URL is full or formatted differently
        match = re.search(r"journalsearch\.php\?q=(\d+)&(?:amp;)?tip=sid", response.text)
        if match:
            return match.group(1)

        return None

    def fetch_journal_page(self, journal_id: str):
        """Open journal page."""
        journal_url = JOURNAL_BASE_URL.format(journal_id=journal_id)
        if self.verbose:
            print(f"[INFO] Visiting journal URL: {journal_url}")
        response = self.fetch_url(journal_url)
        return response, journal_url

    def extract_sjr(self, response) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract SJR value using .hsjr or .hindexnumber.hindex-white.
        Returns tuple of (sjr_value, source_selector).
        """
        hsjr_elements = response.css(".hsjr")
        if hsjr_elements:
            for el in hsjr_elements:
                text = el.text.strip()
                match = re.search(r"\d+(?:\.\d+)?", text)
                if match:
                    return match.group(0), ".hsjr"

        white_boxes = response.css(".hindexnumber.hindex-white")
        for box in white_boxes:
            match = re.search(r"\b\d+\.\d+\b", box.text)
            if match:
                return match.group(0), ".hindexnumber.hindex-white"

        return None, None

    def extract_quartile(self, response) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract Quartile (Q1, Q2, Q3, Q4) dynamically without hardcoding only Q2.
        Returns tuple of (quartile_value, source_selector).
        """
        white_boxes = response.css(".hindexnumber.hindex-white")
        for box in white_boxes:
            for span in box.css("span"):
                span_cls = span.attrib.get("class", "")
                span_text = span.text.strip()
                cls_match = re.search(r"\b(Q[1-4])\b", span_cls)
                if cls_match:
                    return cls_match.group(1), f"span.{span_cls}"
                text_match = re.search(r"\b(Q[1-4])\b", span_text)
                if text_match:
                    return text_match.group(1), ".hindexnumber.hindex-white span"

            box_text = box.text
            match = re.search(r"\b(Q[1-4])\b", box_text)
            if match:
                return match.group(1), ".hindexnumber.hindex-white"

        for span in response.css("span"):
            span_cls = span.attrib.get("class", "")
            cls_match = re.search(r"\b(Q[1-4])\b", span_cls)
            if cls_match:
                return cls_match.group(1), f"span.{span_cls}"

        for h in response.css(".hindexnumber"):
            match = re.search(r"\b(Q[1-4])\b", h.text)
            if match:
                return match.group(1), ".hindexnumber"

        return None, None

    def extract_h_index(self, response) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract H-Index using label-based relationship.
        Inspects headers/labels containing 'H-Index' and extracts the associated numeric value.
        """
        for h2 in response.css("h2"):
            txt = h2.text.strip() if h2.text else ""
            if "h-index" in txt.lower():
                parent = h2.parent
                if parent:
                    h_els = parent.css(".hindexnumber")
                    if h_els:
                        val = h_els[0].text.strip()
                        if val.isdigit():
                            return val, "div.cuadrado > div.hindexnumber"
                    parent_text = parent.get_all_text() if hasattr(parent, "get_all_text") else parent.text
                    match = re.search(r"\b(\d+)\b", parent_text)
                    if match:
                        return match.group(1), "div.cuadrado (h2: H-Index text regex)"

        for div in response.css("div"):
            if "h-index" in div.text.lower():
                h_els = div.css(".hindexnumber")
                if h_els:
                    val = h_els[0].text.strip()
                    if val.isdigit():
                        return val, "div (h-index label) > .hindexnumber"

        return None, None

    def extract_coverage(self, response) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract Coverage using label-based relationship.
        Inspects headers/labels containing 'Coverage' and extracts the text value (e.g. '1974-2026').
        """
        for h2 in response.css("h2"):
            txt = h2.text.strip() if h2.text else ""
            if "coverage" in txt.lower():
                parent = h2.parent
                if parent:
                    c_els = parent.css(".cuadrado-detail")
                    if c_els:
                        val = c_els[0].text.strip()
                        if val:
                            return val, "div.cuadrado > div.cuadrado-detail"
                    parent_text = parent.get_all_text() if hasattr(parent, "get_all_text") else parent.text
                    match = re.search(r"\b\d{4}(?:\s*,\s*\d{4})*(?:\s*-\s*\d{4}|\s*-\s*\w+)?\b", parent_text)
                    if match:
                        return match.group(0).strip(), "div.cuadrado (h2: Coverage text regex)"

        for div in response.css("div"):
            if "coverage" in div.text.lower():
                c_els = div.css(".cuadrado-detail")
                if c_els:
                    val = c_els[0].text.strip()
                    if val:
                        return val, "div (coverage label) > .cuadrado-detail"

        return None, None

    def scrape_journal(self, issn_input: str) -> JournalResult:
        """
        Complete pipeline: search ISSN -> extract Journal ID -> fetch page ->
        extract SJR, Quartile, H-Index, Coverage -> return JournalResult.
        Measures exact per-ISSN execution time with time.perf_counter().
        """
        issn_start = time.perf_counter()
        norm_issn = normalize_issn(issn_input)

        if not norm_issn or norm_issn == "no data":
            if self.verbose:
                print(f"[ERROR] Invalid or empty ISSN: '{issn_input}'")
            elapsed = round(time.perf_counter() - issn_start, 2)
            return JournalResult(
                issn=issn_input,
                journal_id="no data",
                sjr="no data",
                quartile="no data",
                h_index="no data",
                coverage="no data",
                search_url="no data",
                journal_url="no data",
                status="FAILED",
                error="Empty or invalid ISSN provided",
                execution_time=elapsed,
            )

        search_url = SEARCH_BASE_URL.format(issn=norm_issn)
        journal_url = "no data"

        try:
            # 1. Search page
            search_response, search_url = self.search_scimago(norm_issn)

            if search_response.status != 200:
                if self.verbose:
                    print(f"[WARNING] Search returned HTTP {search_response.status}")
                self.save_debug_html(f"search_http_{search_response.status}_{norm_issn}.html", search_response.text)
                elapsed = round(time.perf_counter() - issn_start, 2)
                return JournalResult(
                    issn=norm_issn,
                    journal_id="no data",
                    sjr="no data",
                    quartile="no data",
                    h_index="no data",
                    coverage="no data",
                    search_url=search_url,
                    journal_url="no data",
                    status="FAILED",
                    error=f"HTTP {search_response.status} on search page",
                    execution_time=elapsed,
                )

            # 2. Extract Journal ID
            journal_id = self.extract_journal_id(search_response, norm_issn)
            if not journal_id:
                if self.verbose:
                    print(f"[WARNING] No journal ID found for ISSN: {norm_issn}")
                self.save_debug_html(f"search_{norm_issn}.html", search_response.text)
                elapsed = round(time.perf_counter() - issn_start, 2)
                return JournalResult(
                    issn=norm_issn,
                    journal_id="no data",
                    sjr="no data",
                    quartile="no data",
                    h_index="no data",
                    coverage="no data",
                    search_url=search_url,
                    journal_url="no data",
                    status="FAILED",
                    error="No matching journal found on SCImago",
                    execution_time=elapsed,
                )

            if self.verbose:
                print(f"[INFO] Extracted Journal ID: {journal_id}")

            # 3. Fetch Journal Page
            journal_response, journal_url = self.fetch_journal_page(journal_id)

            if is_challenge_page(journal_response.text):
                if self.verbose:
                    print("[WARNING] SCImago security challenge page detected on journal URL.")
                self.save_debug_html(f"challenge_journal_{journal_id}.html", journal_response.text)
                elapsed = round(time.perf_counter() - issn_start, 2)
                return JournalResult(
                    issn=norm_issn,
                    journal_id=journal_id,
                    sjr="no data",
                    quartile="no data",
                    h_index="no data",
                    coverage="no data",
                    search_url=search_url,
                    journal_url=journal_url,
                    status="FAILED",
                    error="Security challenge page encountered",
                    execution_time=elapsed,
                )

            # 4. Extract metrics independently
            sjr_val, sjr_src = self.extract_sjr(journal_response)
            quartile_val, quartile_src = self.extract_quartile(journal_response)
            h_index_val, h_index_src = self.extract_h_index(journal_response)
            coverage_val, coverage_src = self.extract_coverage(journal_response)

            if self.verbose:
                if sjr_val:
                    print(f"[INFO] SJR selector: {sjr_src}")
                    print(f"[INFO] SJR value: {sjr_val}")
                else:
                    print(f"[WARNING] SJR could not be extracted for journal ID: {journal_id}")

                if quartile_val:
                    print(f"[INFO] Quartile source: {quartile_src}")
                    print(f"[INFO] Quartile value: {quartile_val}")
                else:
                    print(f"[WARNING] Quartile could not be extracted for journal ID: {journal_id}")

                if h_index_val:
                    print(f"[INFO] H-Index source: {h_index_src}")
                    print(f"[INFO] H-Index value: {h_index_val}")
                else:
                    print(f"[WARNING] H-Index could not be extracted for journal ID: {journal_id}")

                if coverage_val:
                    print(f"[INFO] Coverage source: {coverage_src}")
                    print(f"[INFO] Coverage value: {coverage_val}")
                else:
                    print(f"[WARNING] Coverage could not be extracted for journal ID: {journal_id}")

            if not (sjr_val and quartile_val and h_index_val and coverage_val):
                self.save_debug_html(f"journal_{journal_id}.html", journal_response.text)

            extracted_fields = [sjr_val, quartile_val, h_index_val, coverage_val]
            if all(f is not None for f in extracted_fields):
                status = "SUCCESS"
                error = ""
            elif any(f is not None for f in extracted_fields):
                status = "PARTIAL"
                error = "One or more metrics could not be extracted"
            else:
                status = "FAILED"
                error = "All metrics failed to extract from journal page"

            elapsed = round(time.perf_counter() - issn_start, 2)

            result = JournalResult(
                issn=norm_issn,
                journal_id=journal_id,
                sjr=sjr_val if sjr_val else "no data",
                quartile=quartile_val if quartile_val else "no data",
                h_index=h_index_val if h_index_val else "no data",
                coverage=coverage_val if coverage_val else "no data",
                search_url=search_url,
                journal_url=journal_url,
                status=status,
                error=error,
                execution_time=elapsed,
            )
            return result

        except Exception as e:
            if self.verbose:
                print(f"[ERROR] Exception occurred while scraping ISSN {norm_issn}: {e}")
            elapsed = round(time.perf_counter() - issn_start, 2)
            return JournalResult(
                issn=norm_issn,
                journal_id="no data",
                sjr="no data",
                quartile="no data",
                h_index="no data",
                coverage="no data",
                search_url=search_url,
                journal_url=journal_url,
                status="FAILED",
                error=str(e),
                execution_time=elapsed,
            )

    def scrape_journals_batch(self, issns: list, max_workers: int = 5) -> List[JournalResult]:
        """
        Scrape a batch of ISSNs concurrently using ThreadPoolExecutor.
        Maintains order of returned results corresponding to input issns list.
        """
        if not issns:
            return []

        results_map = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_issn = {
                executor.submit(self.scrape_journal, issn): issn
                for issn in issns
            }
            for future in as_completed(future_to_issn):
                issn = future_to_issn[future]
                try:
                    res = future.result()
                    results_map[issn] = res
                except Exception as e:
                    if self.verbose:
                        print(f"[ERROR] Batch worker failed for ISSN {issn}: {e}")
                    results_map[issn] = JournalResult(
                        issn=issn,
                        journal_id="no data",
                        sjr="no data",
                        quartile="no data",
                        h_index="no data",
                        coverage="no data",
                        search_url="no data",
                        journal_url="no data",
                        status="FAILED",
                        error=str(e),
                        execution_time=0.0,
                    )

        return [results_map.get(issn) for issn in issns]

