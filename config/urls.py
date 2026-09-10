"""
Centralized URLs for Publication-AID Project.
Single place to change any external endpoint.
"""

# CFR Anna University
CFR_START_URL = "https://cfr.annauniv.edu/research/academics/journals-list.php"

# Scopus - Elsevier Source Title List
ELSEVIER_SCOPUS_POLICY_URL = "https://www.elsevier.com/solutions/scopus/how-scopus-works/content/content-policy-and-selection"
# Direct download URL pattern (discovered via ELSEVIER_SCOPUS_POLICY_URL, fallback ctfassets)
SCOPUS_DOWNLOAD_URL_PATTERN = "ext_list"  # used to find .xlsx link on policy page

# MJL / Clarivate
MJL_SEARCH_BASE = "https://mjl.clarivate.com/search-results?issn={issn}"
MJL_API_URL = "https://mjl.clarivate.com/api/mjl/jprof/public/rank-search"
MJL_API_PATTERN = "rank-search"
MJL_HOME_URL = "https://mjl.clarivate.com/search-results"

# SCImago
SCIMAGO_SEARCH_BASE = "https://www.scimagojr.com/journalsearch.php?q={issn}"
SCIMAGO_JOURNAL_BASE = "https://www.scimagojr.com/journalsearch.php?q={journal_id}&tip=sid&clean=0"

# APC (Article Processing Charge)
APC_CACHE_DIR = "apc_cache"
ELSEVIER_GPOA_URL = "https://www.elsevier.com/about/policies-and-standards/pricing/gpoa-journals-list"

# Output
OUTPUT_DIR_NAME = "output"
DEBUG_SUBDIR = "debug"
