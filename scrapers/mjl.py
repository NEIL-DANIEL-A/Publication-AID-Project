"""
scrapers/mjl.py
---------------
Clarivate Master Journal List (MJL) Verification Stage - Hybrid.

Strategy:
  Primary (fast): Direct HTTP POST to MJL rank-search API
    POST https://mjl.clarivate.com/api/mjl/jprof/public/rank-search
    with JSON payload {"searchValue":"2632-2153", ...}
    This is what the Angular frontend triggers when navigating to
    https://mjl.clarivate.com/search-results?issn=<ISSN>
    Varying the ISSN in that URL exactly varies searchValue.
    Latency: ~0.4s/journal, thread-safe, no browser.

  Fallback (robust): Playwright browser automation
    Navigate to https://mjl.clarivate.com/search-results?issn={issn}
    Intercept the XHR response from /api/mjl/jprof/public/rank-search
    Used only if direct POST fails (network, 403, empty response).
    Latency: ~3s/journal, sequential browser reuse.

Product codes from MJL API mapped to WoS index names:
  D  -> SCIE  (Science Citation Index Expanded)
  E  -> SSCI  (Social Sciences Citation Index)
  C/H-> AHCI  (Arts & Humanities Citation Index)
  F  -> ESCI  (Emerging Sources Citation Index)
"""

import json
import time
import uuid
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from config.urls import MJL_API_PATTERN, MJL_API_URL, MJL_HOME_URL, MJL_SEARCH_BASE
from models import CFRJournal, MJLVerificationResult
from processors.issn import normalize_issn

DEFAULT_TIMEOUT_S = 10
COOKIE_ACCEPT_ID = "onetrust-accept-btn-handler"

# --------------------------------------------------------------------------- #
#  WoS product code mapping
# --------------------------------------------------------------------------- #

_CORE_COLLECTION_CODES = {
    "D": "SCIE",
    "E": "SSCI",
    "C": "AHCI",
    "H": "AHCI",
    "F": "ESCI",
}

_PRODUCT_CODE_DESCRIPTIONS = {
    "BA": "Biological Abstracts",
    "BP": "BIOSIS Previews",
    "B7": "Zoological Record",
    "CR": "Current Chemical Reactions",
    "I":  "Index Chemicus",
    "ES": "Essential Science Indicators",
    "JS": "Journal Citation Reports - Science",
    "JH": "Journal Citation Reports - Social Sciences",
}


def _extract_wos_indexes(products: list) -> str:
    """
    Extract Web of Science Core Collection index names from a products list.
    Prioritises Core Collection indexes (SCIE, SSCI, AHCI, ESCI).
    Falls back to all product descriptions if no core collection found.
    Uses both productCode and description substring for robustness.
    """
    if not products:
        return "no data"

    core = []
    other = []

    for product in products:
        code = str(product.get("productCode") or "").strip()
        desc = str(product.get("description") or "").strip()
        desc_lower = desc.lower()

        if "science citation index expanded" in desc_lower:
            core.append("SCIE")
            continue
        if "social sciences citation index" in desc_lower:
            core.append("SSCI")
            continue
        if "arts & humanities citation index" in desc_lower or "arts and humanities citation index" in desc_lower:
            core.append("AHCI")
            continue
        if "emerging sources citation index" in desc_lower:
            core.append("ESCI")
            continue

        if code in _CORE_COLLECTION_CODES:
            core.append(_CORE_COLLECTION_CODES[code])
        elif code in _PRODUCT_CODE_DESCRIPTIONS:
            other.append(_PRODUCT_CODE_DESCRIPTIONS[code])

    if core:
        return ", ".join(sorted(set(core)))
    if other:
        return ", ".join(sorted(set(other)))
    return "no data"


# --------------------------------------------------------------------------- #
#  Response parsing
# --------------------------------------------------------------------------- #

def _parse_mjl_response(response_text: str, searched_norm_issn: str) -> Tuple[str, str, str, str]:
    """
    Parse the rank-search API JSON response.

    Returns:
      (mjl_status, mjl_index, mjl_match_type, mjl_source_title)
    """
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        return "Unable to Verify", "no data", "No Match", "no data"

    profiles = data.get("journalProfiles") or []
    total = data.get("totalRecords", 0)

    if not profiles or total == 0:
        return "Not Found", "no data", "No Match", "no data"

    for entry in profiles:
        profile = entry.get("journalProfile") or entry
        p_issn = normalize_issn(str(profile.get("issn") or ""))
        e_issn = normalize_issn(str(profile.get("eissn") or ""))

        if searched_norm_issn and searched_norm_issn in (p_issn, e_issn):
            index_str = _extract_wos_indexes(profile.get("products") or [])
            source_title = (
                profile.get("publicationTitle")
                or profile.get("publicationTitleISO")
                or "no data"
            )
            return "Found", index_str, "Exact ISSN", str(source_title)

    if total == 1:
        profile = profiles[0].get("journalProfile") or profiles[0]
        index_str = _extract_wos_indexes(profile.get("products") or [])
        source_title = (
            profile.get("publicationTitle")
            or profile.get("publicationTitleISO")
            or "no data"
        )
        return "Found", index_str, "Single Result", str(source_title)

    return "Not Found", "no data", "No Match", "no data"


# --------------------------------------------------------------------------- #
#  Direct HTTP POST (primary, fast, thread-safe)
# --------------------------------------------------------------------------- #

_MJL_HEADERS = {
    "Referer": MJL_HOME_URL,
    "X-1P-AppId": "mjl",
    "Authorization": "Bearer",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}

def _build_mjl_payload(formatted_issn: str) -> dict:
    return {
        "searchValue": formatted_issn,
        "pageNum": 1,
        "pageSize": 10,
        "sortOrder": [{"name": "RELEVANCE", "order": "DESC"}],
        "filters": [
            {"filterName": "COVERED_LATEST_JEDI", "matchType": "BOOLEAN_EXACT", "caseSensitive": False, "values": [{"type": "VALUE", "value": "true"}]},
            {"filterName": "PRODUCT_CODE", "matchType": "TEXT_EXACT", "caseSensitive": False, "values": [
                {"type": "VALUE", "value": "D"},
                {"type": "VALUE", "value": "J"},
                {"type": "VALUE", "value": "SS"},
                {"type": "VALUE", "value": "H"},
                {"type": "VALUE", "value": "EX"},
            ]},
        ],
        "searchIdentifier": str(uuid.uuid4()),
    }

def _direct_post_mjl(formatted_issn: str, timeout: int = DEFAULT_TIMEOUT_S) -> Optional[str]:
    """
    Direct POST to MJL rank-search API without browser.
    Returns raw JSON string on success (including Not Found), None on network failure.
    Thread-safe: uses urllib (no shared state).
    """
    payload = _build_mjl_payload(formatted_issn)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(MJL_API_URL, data=data, headers=_MJL_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            body = resp.read().decode("utf-8")
            # Validate JSON
            json.loads(body)
            return body
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, Exception):
        return None


# --------------------------------------------------------------------------- #
#  MJLVerifier class (Playwright fallback)
# --------------------------------------------------------------------------- #

class MJLVerifier:
    """
    Playwright-based verifier for the Clarivate Master Journal List.
    Uses URL-based ISSN search (?issn=XXXX) and network response interception
    to get results without fragile UI interaction.
    Used as fallback when direct POST fails.
    """

    def __init__(self, headless: bool = True, verbose: bool = False):
        self.headless = headless
        self.verbose = verbose
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop()

    def _log(self, msg: str):
        if self.verbose:
            print(f"[MJL] {msg}", flush=True)

    def _start(self):
        """Launch Playwright browser (lazy - only when fallback needed)."""
        from playwright.sync_api import sync_playwright
        self._pw_ctx = sync_playwright()
        self._playwright = self._pw_ctx.start()

        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        self._context.add_cookies([{
            "name": "OptanonAlertBoxClosed",
            "value": "2026-01-01T00:00:00.000Z",
            "domain": ".clarivate.com",
            "path": "/"
        }])
        import re
        self._context.route(
            re.compile(r"(pendo\.io|vidyard|google-analytics|recaptcha\.net/recaptcha|cookielaw\.org|onetrust)"),
            lambda route: route.abort()
        )
        self._page = self._context.new_page()
        try:
            self._page.goto(MJL_HOME_URL, wait_until="domcontentloaded", timeout=15_000)
            time.sleep(4)
            self._remove_overlays()
        except Exception:
            pass
        self._log("Browser ready (pre-warmed)")

    def _remove_overlays(self):
        """Remove OneTrust consent overlays that block pointer events."""
        try:
            self._page.evaluate("""() => {
                const el = document.getElementById('onetrust-consent-sdk');
                if (el) el.remove();
                const dark = document.querySelector('.onetrust-pc-dark-filter');
                if (dark) dark.remove();
            }""")
        except Exception:
            pass

    def _stop(self):
        """Cleanly close browser."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

    def _search_issn(self, formatted_issn: str, norm_issn: str) -> Optional[str]:
        """
        Navigate to the MJL URL with ?issn= parameter and intercept the
        rank-search API response.

        Returns the raw response body JSON string, or None on timeout/failure.
        """
        page = self._page
        url = MJL_SEARCH_BASE.format(issn=formatted_issn)
        captured: list = []

        def on_response(response):
            if MJL_API_PATTERN in response.url and response.status == 200:
                try:
                    body = response.text()
                    captured.append(body)
                    self._log(f"Captured rank-search ({len(body)} bytes)")
                except Exception:
                    pass

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            page.wait_for_timeout(3000)

            return captured[-1] if captured else None

        except Exception as e:
            self._log(f"Navigation error for ISSN {formatted_issn}: {e}")
            return None
        finally:
            page.remove_listener("response", on_response)

    def verify_journal(self, journal: CFRJournal) -> MJLVerificationResult:
        """
        Verify a single CFRJournal on the MJL.
        Hybrid: tries direct POST first (~0.5s), falls back to Playwright (~3s) only on failure.
        Uses Print ISSN first; falls back to E-ISSN.
        """
        norm_p = normalize_issn(journal.print_issn)
        norm_e = normalize_issn(journal.e_issn)

        def fmt(n: str) -> str:
            if n == "no data" or len(n) < 8:
                return n
            return f"{n[:4]}-{n[4:8]}"

        # Helper to try direct POST then fallback to browser for a single ISSN
        def _try_issn(formatted: str, norm: str, label: str) -> Optional[Tuple[str, str, str, str, str]]:
            # 1. Direct POST (fast path)
            raw = _direct_post_mjl(formatted)
            if raw is not None:
                self._log(f"Direct POST {label} {formatted} -> {len(raw)} bytes")
                status, index, match_type, source_title = _parse_mjl_response(raw, norm)
                return raw, status, index, match_type, source_title
            # 2. Fallback to Playwright if direct failed (network/403)
            if self._page is None:
                # Lazy browser init only when needed
                self._start()
            self._log(f"Direct POST failed for {label} {formatted}, falling back to browser")
            raw = self._search_issn(formatted, norm)
            if raw:
                status, index, match_type, source_title = _parse_mjl_response(raw, norm)
                return raw, status, index, match_type, source_title
            return None

        # Attempt 1: Print ISSN
        if norm_p != "no data":
            self._log(f"Searching P-ISSN {fmt(norm_p)} | '{journal.journal_title[:40]}'")
            result = _try_issn(fmt(norm_p), norm_p, "P-ISSN")
            if result:
                _, status, index, match_type, source_title = result
                if status == "Found":
                    return MJLVerificationResult(
                        mjl_status="Found",
                        mjl_index=index,
                        mjl_issn_used=fmt(norm_p),
                        mjl_match_type="Print ISSN",
                        mjl_source_title=source_title,
                    )
                elif status == "Not Found" and norm_e == "no data":
                    return MJLVerificationResult(
                        mjl_status="Not Found",
                        mjl_index="no data",
                        mjl_issn_used=fmt(norm_p),
                        mjl_match_type="No Match",
                        mjl_source_title="no data",
                    )
                # else try E-ISSN

        # Attempt 2: E-ISSN fallback
        if norm_e != "no data":
            self._log(f"Searching E-ISSN {fmt(norm_e)} | '{journal.journal_title[:40]}'")
            result = _try_issn(fmt(norm_e), norm_e, "E-ISSN")
            if result:
                _, status, index, match_type, source_title = result
                return MJLVerificationResult(
                    mjl_status=status,
                    mjl_index=index if status == "Found" else "no data",
                    mjl_issn_used=fmt(norm_e),
                    mjl_match_type="E-ISSN" if status == "Found" else "No Match",
                    mjl_source_title=source_title if status == "Found" else "no data",
                )

        return MJLVerificationResult(
            mjl_status="Unable to Verify",
            mjl_index="no data",
            mjl_issn_used="no data",
            mjl_match_type="No Match",
            mjl_source_title="no data",
        )


# --------------------------------------------------------------------------- #
#  Functional wrapper - Hybrid with threading for direct POST
# --------------------------------------------------------------------------- #

def _direct_verify_single(journal: CFRJournal) -> Optional[MJLVerificationResult]:
    """Fast path without browser - try direct POST for both ISSNs."""
    norm_p = normalize_issn(journal.print_issn)
    norm_e = normalize_issn(journal.e_issn)

    def fmt(n: str) -> str:
        if n == "no data" or len(n) < 8:
            return n
        return f"{n[:4]}-{n[4:8]}"

    if norm_p != "no data":
        raw = _direct_post_mjl(fmt(norm_p))
        if raw is not None:
            status, index, _, source_title = _parse_mjl_response(raw, norm_p)
            if status == "Found":
                return MJLVerificationResult(mjl_status="Found", mjl_index=index, mjl_issn_used=fmt(norm_p), mjl_match_type="Print ISSN", mjl_source_title=source_title)
            elif status == "Not Found" and norm_e == "no data":
                return MJLVerificationResult(mjl_status="Not Found", mjl_index="no data", mjl_issn_used=fmt(norm_p), mjl_match_type="No Match", mjl_source_title="no data")
            # else try E-ISSN

    if norm_e != "no data":
        raw = _direct_post_mjl(fmt(norm_e))
        if raw is not None:
            status, index, _, source_title = _parse_mjl_response(raw, norm_e)
            return MJLVerificationResult(
                mjl_status=status,
                mjl_index=index if status == "Found" else "no data",
                mjl_issn_used=fmt(norm_e),
                mjl_match_type="E-ISSN" if status == "Found" else "No Match",
                mjl_source_title=source_title if status == "Found" else "no data",
            )

    # None means network failure - needs browser fallback
    return None


def verify_mjl_indexing(
    active_pairs: List[Tuple[CFRJournal, object]],
    headless: bool = True,
    verbose: bool = False,
    max_workers: int = 5,
) -> List[Tuple[CFRJournal, object, "MJLVerificationResult"]]:
    """
    Verify MJL indexing for a list of (CFRJournal, ScopusVerificationResult) pairs.
    Hybrid: Direct POST via ThreadPool (fast), browser fallback only for failures.

    Returns list of (CFRJournal, ScopusVerificationResult, MJLVerificationResult).
    """
    results = []
    if not active_pairs:
        return results

    # Phase 1: Fast direct POST with threading (no browser)
    print(f"[INFO] MJL Phase 1: Direct API POST ({len(active_pairs)} journals, {max_workers} workers)...")
    phase1_start = time.perf_counter()
    direct_results: dict = {}
    needs_fallback = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_direct_verify_single, j): (j, s) for j, s in active_pairs}
        for future in as_completed(future_map):
            journal, scopus_res = future_map[future]
            try:
                res = future.result()
                if res is not None:
                    direct_results[journal.sl_no] = res
                else:
                    needs_fallback.append((journal, scopus_res))
            except Exception:
                needs_fallback.append((journal, scopus_res))

    phase1_time = time.perf_counter() - phase1_start
    print(f"[INFO] MJL Phase 1 complete: {len(direct_results)} resolved, {len(needs_fallback)} need browser fallback ({phase1_time:.2f}s)")

    # Phase 2: Browser fallback only for failures
    fallback_results: dict = {}
    if needs_fallback:
        print(f"[INFO] MJL Phase 2: Browser fallback for {len(needs_fallback)} journals...")
        with MJLVerifier(headless=headless, verbose=verbose) as verifier:
            for i, (journal, scopus_res) in enumerate(needs_fallback, 1):
                t0 = time.perf_counter()
                mjl_res = verifier.verify_journal(journal)
                elapsed = round(time.perf_counter() - t0, 2)
                icon = "[OK]" if mjl_res.mjl_status == "Found" else ("[?]" if mjl_res.mjl_status == "Unable to Verify" else "[X]")
                print(
                    f"  [MJL-FB {i}/{len(needs_fallback)}] {journal.journal_title[:35]:<35} | "
                    f"{icon} {mjl_res.mjl_status:<20} | "
                    f"Index: {mjl_res.mjl_index:<25} ({elapsed:.2f}s)",
                    flush=True,
                )
                fallback_results[journal.sl_no] = mjl_res

    # Merge and print in original order
    for i, (journal, scopus_res) in enumerate(active_pairs, 1):
        if journal.sl_no in direct_results:
            mjl_res = direct_results[journal.sl_no]
            icon = "[OK]" if mjl_res.mjl_status == "Found" else ("[X]" if mjl_res.mjl_status == "Not Found" else "[?]")
            # We already printed fallback; for direct we print here if verbose or always
            if verbose or True:
                # Reconstruct elapsed approx - use phase1 avg
                pass
            print(
                f"  [MJL {i}/{len(active_pairs)}] {journal.journal_title[:35]:<35} | "
                f"{icon} {mjl_res.mjl_status:<20} | "
                f"Index: {mjl_res.mjl_index:<25} (direct)",
                flush=True,
            )
        else:
            mjl_res = fallback_results.get(journal.sl_no, MJLVerificationResult(mjl_status="Unable to Verify", mjl_index="no data", mjl_issn_used="no data", mjl_match_type="No Match", mjl_source_title="no data"))
            # Already printed in fallback phase
            if journal.sl_no not in fallback_results:
                print(
                    f"  [MJL {i}/{len(active_pairs)}] {journal.journal_title[:35]:<35} | "
                    f"[OK] {mjl_res.mjl_status:<20} | "
                    f"Index: {mjl_res.mjl_index:<25} (fallback failed)",
                    flush=True,
                )
        results.append((journal, scopus_res, mjl_res))

    return results


# --------------------------------------------------------------------------- #
#  Standalone smoke test
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    """
    Quick smoke test with 3 known journals.
    Run: python -m scrapers.mjl
    """
    test_journals = [
        CFRJournal("1", "Nature", "0028-0836", "1476-4687", "Springer Nature", "UK"),
        CFRJournal("2", "Scientometrics", "0138-9130", "1588-2861", "Springer", "Netherlands"),
        CFRJournal("3", "Some Unknown Journal", "9999-9999", "8888-8888", "Unknown", "Unknown"),
    ]

    print("=== MJL Smoke Test (Hybrid) ===\n")
    # Test direct POST path
    for jrnl in test_journals:
        print(f"\nDirect POST: {jrnl.journal_title}")
        r = _direct_verify_single(jrnl)
        if r:
            print(f"  Status: {r.mjl_status} | Index: {r.mjl_index} | ISSN: {r.mjl_issn_used}")
        else:
            print("  Direct POST failed, trying browser fallback")
            with MJLVerifier(headless=True, verbose=True) as v:
                r2 = v.verify_journal(jrnl)
                print(f"  Fallback Status: {r2.mjl_status} | Index: {r2.mjl_index}")

    print("\n=== Full verify_mjl_indexing (hybrid threaded) ===")
    pairs = [(j, None) for j in test_journals]
    results = verify_mjl_indexing(pairs, headless=True, verbose=True)
    for _, _, r in results:
        print(f"  {r.mjl_status} | {r.mjl_index}")
