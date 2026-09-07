"""
APC (Article Processing Charge) source definitions for each publisher.
Maps publisher name -> list of sources, each with URL + column/field config.
"""

APC_SOURCES = {
    "Wiley": [
        {
            "name": "Wiley OA",
            "url": "https://authors.wiley.com/author-resources/Journal-Authors/open-access/article-publication-charges/index.html",
            "filename": "Wiley_Journal_APCs_Open_Access.xlsx",
            "direct_url": "https://authors.wiley.com/asset/Wiley-Journal-APCs-Open-Access.xlsx",
            "header_row": 6,
            "issn_col": "Online ISSN",
            "apc_col": "USD",
            "mode_col": "License Types Offered",
        },
        {
            "name": "Wiley Hybrid",
            "url": "https://authors.wiley.com/author-resources/Journal-Authors/open-access/article-publication-charges/index.html",
            "filename": "Wiley_Journal_APCs_OnlineOpen.xlsx",
            "direct_url": "https://authors.wiley.com/asset/Wiley-Journal-APCs-OnlineOpen.xlsx",
            "header_row": 6,
            "issn_col": "Online\nISSN",
            "apc_col": "USD $",
            "mode_col": "License types offered",
        },
    ],
    "Elsevier": [
        {
            "name": "Elsevier APC",
            "url": "https://www.elsevier.com/about/policies-and-standards/pricing",
            "filename": "Elsevier_APC.xlsx",
            "direct_url": "https://legacyfileshare.elsevier.com/els%5Fcom%5Fpricing/article-publishing-charge.xlsx",
            "header_row": 4,
            "issn_col": "ISSN",
            "apc_col": "USD",
            "mode_col": "Business model",
        },
    ],
    "Springer Nature": [
        {
            "name": "Springer Nature Hybrid",
            "url": "https://www.springernature.com/gp/open-science/journals-books/journals",
            "filename": "Springer_Nature_Hybrid_APC.pdf",
            "pdf_url": "https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/27820862/data/v3",
            "issn_col": "ISSN",
            "apc_col": "EUR",
            "apc_col_usd": "USD",
            "apc_col_gbp": "GBP",
            "mode_col": "Type",
        },
        {
            "name": "Springer Nature Fully OA",
            "url": "https://www.springernature.com/gp/open-science/journals-books/journals",
            "filename": "Springer_Nature_FullyOA_APC.pdf",
            "pdf_url": "https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/27820860/data/v3",
            "issn_col": "ISSN",
            "apc_col": "EUR",
            "apc_col_usd": "USD",
            "apc_col_gbp": "GBP",
            "mode_col": "Type",
        },
    ],
}

# Column aliases: map lowercase/variant header names to canonical name
# Used by _find_column() for flexible matching across header variations
APC_COLUMN_ALIASES = {
    "issn": ["issn", "print issn", "issn (print)", "issn print", "print_issn", "journal issn"],
    "apc_usd": ["apc (usd)", "apc usd", "usd", "price (usd)", "cost (usd)", "apc"],
    "apc_eur": ["apc (eur)", "apc eur", "eur", "price (eur)", "cost (eur)"],
    "apc_gbp": ["apc (gbp)", "apc gbp", "gbp", "price (gbp)", "cost (gbp)"],
    "mode": ["oa type", "mode", "open access type", "onlineopen category", "access type", "type", "oa mode"],
}
