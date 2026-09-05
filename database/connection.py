import os

from dotenv import load_dotenv

load_dotenv()

_client = None


def get_supabase_client():
    """
    Initialize and return Supabase client.
    Validates SUPABASE_URL and SUPABASE_KEY env variables.
    Raises RuntimeError if missing.
    Reuses singleton client.
    """
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip() or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "Supabase credentials missing. Set SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) in .env. "
            "See .env.example"
        )

    try:
        from supabase import create_client
    except ImportError as e:
        raise RuntimeError("supabase package not installed. Run: pip install -r requirements.txt") from e

    _client = create_client(url, key)
    return _client


def is_supabase_configured() -> bool:
    """Return True if env credentials are present (without initializing client)."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip() or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return bool(url and key)
