from passlib.hash import bcrypt_sha256
from sqlalchemy import text

from services.db_service import DatabaseService

database_service = DatabaseService()


def hash_password(password: str) -> str:
    password = str(password)  # bezpieczeństwo typów
    return bcrypt_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt_sha256.verify(str(password), password_hash)
    except Exception:
        return False


def create_user(nick: str, email: str, password: str) -> tuple[bool, str]:
    nick = (nick or "").strip()
    email = (email or "").strip().lower()
    password = password or ""

    print("DEBUG password repr:", repr(password)[:200])
    print("DEBUG password bytes len:", len(str(password).encode("utf-8")))

    if not nick or not email or not password:
        return False, "Uzupełnij nick, email i hasło."
    if len(password) < 8:
        return False, "Hasło musi mieć min. 8 znaków."

    pwd_hash = hash_password(password)

    try:
        with database_service.get_session() as s:
            s.execute(
                text(
                    "INSERT INTO users(nick, email, password_hash) VALUES(:nick, :email, :ph)"
                ),
                {"nick": nick, "email": email, "ph": pwd_hash},
            )
        return True, "Konto utworzone. Zaloguj się."
    except Exception as e:
        msg = str(e).lower()
        if "users_nick_key" in msg or ("unique" in msg and "nick" in msg):
            return False, "Ten nick jest już zajęty."
        if "users_email_key" in msg or ("unique" in msg and "email" in msg):
            return False, "Ten email jest już użyty."
        return False, "Nie udało się utworzyć konta."


def login(email: str, password: str):
    email = (email or "").strip().lower()
    password = password or ""

    with database_service.get_session() as s:
        row = s.execute(
            text("SELECT * FROM users WHERE email = :email"),
            {"email": email},
        ).fetchone()

    if not row:
        return None

    user = dict(row._mapping)
    if not verify_password(password, user["password_hash"]):
        return None
    return user



