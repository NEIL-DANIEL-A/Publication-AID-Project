import re


def normalize_issn(issn: str) -> str:
    """
    Normalize an ISSN string.
    Examples:
        "0129-6612"   -> "01296612"
        "2377-6277"   -> "23776277"
        " 0129-6612 " -> "01296612"
    If empty, unavailable, or invalid, returns "no data".
    """
    if not issn:
        return "no data"
    
    val = str(issn).strip()
    if not val or val.lower() in ["no data", "none", "nan", "null", "-", "nil", "na", "n/a"]:
        return "no data"

    cleaned = re.sub(r"[^0-9Xx]", "", val).upper()
    if not cleaned:
        return "no data"

    return cleaned
