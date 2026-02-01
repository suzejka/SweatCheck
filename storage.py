import os
import uuid

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "images").strip()

if not SUPABASE_URL:
    raise RuntimeError("Brak SUPABASE_URL w .env")
if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Brak SUPABASE_SERVICE_ROLE_KEY w .env")

if not SUPABASE_URL.endswith("/"):
    SUPABASE_URL += "/"

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def save_image(file_bytes: bytes, user_id: int, kind: str) -> str:
    """Zwraca STORAGE KEY (ścieżkę obiektu w buckecie), a nie publiczny URL."""
    object_path = f"{user_id}/{kind}/{uuid.uuid4().hex}.jpg"
    sb.storage.from_(BUCKET).upload(
        path=object_path,
        file=file_bytes,
        file_options={"content-type": "image/jpeg", "upsert": "true"},
    )
    return object_path


def get_signed_url(object_path: str, expires_seconds: int = 3600) -> str:
    """Zwraca tymczasowy URL (signed) do prywatnego obiektu."""
    res = sb.storage.from_(BUCKET).create_signed_url(object_path, expires_seconds)
    # supabase-py zwraca dict z 'signedURL' / 'signed_url' zależnie od wersji
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
    # fallback, gdyby klient zwracał obiekt
    return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)
