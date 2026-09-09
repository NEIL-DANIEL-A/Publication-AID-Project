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
            "mode_col": "",
            "mode_label": "Open Access",
        },
        {
            "name": "Wiley Hybrid",
            "url": "https://authors.wiley.com/author-resources/Journal-Authors/open-access/article-publication-charges/index.html",
            "filename": "Wiley_Journal_APCs_OnlineOpen.xlsx",
            "direct_url": "https://authors.wiley.com/asset/Wiley-Journal-APCs-OnlineOpen.xlsx",
            "header_row": 6,
            "issn_col": "Online\nISSN",
            "apc_col": "USD $",
            "mode_col": "",
            "mode_label": "Hybrid",
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
    "Oxford University Press": [
        {
            "name": "OUP APC",
            "url": "https://academic.oup.com/pages/open-research/open-access/charges-licences-and-self-archiving",
            "filename": "OUP_Charges.xlsx",
            "direct_url": "https://global.oup.com/fdscontent/academic/xls/openaccess/charges.xlsx",
            "header_row": 0,
            "issn_col": "ISSN",
            "apc_col": "APC rate",
            "apc_currency_col": "APC Base Currency",
            "mode_col": "Journal Type",
        },
    ],
    "SAGE": [
        {
            "name": "SAGE Hybrid",
            "url": "https://www.sagepub.com/journals/information-for-authors/publishing-options",
            "filename": "SAGE_Hybrid.xlsx",
            "direct_url": "https://www.sagepub.com/docs/default-source/rp-pages/info-for-authors/hybrid-oa-sage-choice/sage-choice-price-list-2026---external.xlsx?sfvrsn=4e6e819b_8",
            "header_row": 0,
            "issn_col": "ISSN",
            "apc_col": "2026 OA APC ($)",
            "apc_gbp_col": "2026 OA APC (£)",
            "mode_label": "hybrid",
        },
        {
            "name": "SAGE Gold OA",
            "url": "https://www.sagepub.com/journals/information-for-authors/publishing-options",
            "filename": "SAGE_Gold_OA.xlsx",
            "direct_url": "https://www.sagepub.com/docs/default-source/rp-pages/info-for-authors/sage-gold-oa-apcs-2026.xlsx?sfvrsn=5f7181ea_6",
            "header_row": 0,
            "issn_col": "",
            "apc_col": "Current Price 2026",
            "apc_gbp_col": "",
            "mode_label": "GOLD OA",
            "title_col": "Journal Title1",
            "currency_col": "Currency",
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
            "mode_label": "Hybrid",
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
            "mode_label": "Fully OA",
        },
    ],
}

# Column aliases: map lowercase/variant header names to canonical name
# Used by _find_column() for flexible matching across header variations
APC_COLUMN_ALIASES = {
    "issn": ["issn", "print issn", "issn (print)", "issn print", "print_issn", "journal issn", "online issn", "e-issn", "eissn"],
    "apc_usd": ["apc (usd)", "apc usd", "usd", "price (usd)", "cost (usd)", "apc"],
    "apc_eur": ["apc (eur)", "apc eur", "eur", "price (eur)", "cost (eur)"],
    "apc_gbp": ["apc (gbp)", "apc gbp", "gbp", "price (gbp)", "cost (gbp)"],
    "apc_rate": ["apc rate", "apc rate (gbp)", "apc rate (usd)", "apc rate (eur)", "rate", "charge", "apc charge"],
    "apc_currency": ["apc base currency", "currency", "base currency", "apc currency"],
    "mode": ["oa type", "mode", "open access type", "onlineopen category", "access type", "type", "oa mode", "journal type"],
}
