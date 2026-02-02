import os
from contextlib import contextmanager
from typing import Optional
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from passlib.hash import bcrypt_sha256
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_HOST = os.getenv("DATABASE_HOST")
DB_USER = os.getenv("DATABASE_USER")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD")
DB_NAME = os.getenv("DATABASE_NAME")

missing = [
    key
    for key, value in {
        "DATABASE_HOST": DB_HOST,
        "DATABASE_USER": DB_USER,
        "DATABASE_PASSWORD": DB_PASSWORD,
        "DATABASE_NAME": DB_NAME,
    }.items()
    if not value
]
if missing:
    raise RuntimeError(
        f"Brak zmiennych w .env (lub w zmiennych środowiskowych): {', '.join(missing)}"
    )


class DatabaseService:

    DATABASE_URL = (
        "postgresql+psycopg2://"
        f"{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}/{DB_NAME}"
    )

    def __init__(self):

        self.engine = create_engine(
            self.DATABASE_URL,
            pool_pre_ping=True,
            future=True,
        )

        self.session_local = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False, future=True
        )

    @contextmanager
    def get_session(self):
        session = self.session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def init_db(self):
        """Tworzy tabele (MVP) jeśli nie istnieją."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                nick TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                avatar_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
                )
            )

            conn.execute(
                text(
                    """
            CREATE TABLE IF NOT EXISTS friends (
                user_id INT NOT NULL,
                friend_id INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, friend_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(friend_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
                )
            )

            conn.execute(
                text(
                    """
            CREATE TABLE IF NOT EXISTS workouts (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                title TEXT NOT NULL,
                calories INT,
                fatigue INT NOT NULL, -- 1..10
                photo_path TEXT,
                video_url TEXT,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
                )
            )

            # migracja: dodaj kolumnę comment, jeśli tabela istniała wcześniej
            conn.execute(
                text(
                    """
                ALTER TABLE workouts
                ADD COLUMN IF NOT EXISTS comment TEXT;
                """
                )
            )

            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                requester_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                addressee_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending', -- pending/accepted/declined/cancelled
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                responded_at TIMESTAMP,
                UNIQUE(requester_id, addressee_id)
                );
            """
                )
            )

            conn.execute(
                text(
                    """
                -- powiadomienia
                CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type TEXT NOT NULL, -- friend_request, friend_accept, friend_decline, etc.
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """
                )
            )

            conn.execute(
                text(
                    """
                ALTER TABLE workouts
                ADD COLUMN IF NOT EXISTS performed_at TIMESTAMP;
                """
                )
            )

            # backfill: dla starych rekordów ustaw performed_at=created_at
            conn.execute(
                text(
                    """
                UPDATE workouts
                SET performed_at = created_at
                WHERE performed_at IS NULL;
                """
                )
            )

            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'USER';
                """))

    # -------------------------
    # DB helpers
    # -------------------------
    def list_friends(self, user_id: int):
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT u.* FROM friends f
                JOIN users u ON u.id = f.friend_id
                WHERE f.user_id = :uid
                ORDER BY u.nick
            """
                ),
                {"uid": user_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def update_nick(self, user_id: int, new_nick: str) -> tuple[bool, str]:
        new_nick = (new_nick or "").strip()
        if len(new_nick) < 2:
            return False, "Nick musi mieć min. 2 znaki."

        try:
            with self.get_session() as s:
                s.execute(
                    text(
                        """
                    UPDATE users SET nick = :n WHERE id = :id
                """
                    ),
                    {"n": new_nick, "id": user_id},
                )
            return True, "Zmieniono nick."
        except Exception as e:
            msg = str(e).lower()
            if "users_nick_key" in msg or ("unique" in msg and "nick" in msg):
                return False, "Ten nick jest już zajęty."
            return False, "Nie udało się zmienić nicku."
        
    def set_role(self, user_id: int, role: str) -> tuple[bool, str]:
        role = (role or "").strip().upper()
        if role not in {"USER", "ADMIN"}:
            return False, "Nieprawidłowa rola."
        with self.get_session() as s:
            s.execute(text("UPDATE users SET role=:r WHERE id=:id"), {"r": role, "id": user_id})
        return True, "Zapisano rolę."

    def broadcast_notification(self, *, type_: str, message: str) -> tuple[bool, str]:
        type_ = (type_ or "").strip()
        message = (message or "").strip()
        if not message:
            return False, "Wpisz treść powiadomienia."

        # payload trzymamy w JSONB; zrobimy prosto: {"message": "..."}
        with self.get_session() as s:
            s.execute(text("""
                INSERT INTO notifications(user_id, type, payload)
                SELECT u.id, :t, jsonb_build_object('message', :m)
                FROM users u
            """), {"t": type_ or "admin_broadcast", "m": message})

        return True, "Wysłano powiadomienie do wszystkich."

    def send_friend_request(
        self, requester_id: int, addressee_email: str
    ) -> tuple[bool, str]:
        addressee_email = (addressee_email or "").strip().lower()
        if not addressee_email:
            return False, "Podaj email."

        with self.get_session() as s:
            addressee = s.execute(
                text("SELECT id, nick FROM users WHERE email = :e"),
                {"e": addressee_email},
            ).fetchone()

            if not addressee:
                return False, "Nie znaleziono użytkownika o takim emailu."

            addressee_id = int(addressee._mapping["id"])
            addressee_nick = addressee._mapping["nick"]

            if addressee_id == requester_id:
                return False, "Nie możesz zaprosić siebie."

            # czy już są znajomymi?
            already = s.execute(
                text(
                    """
                SELECT 1 FROM friends WHERE user_id=:u AND friend_id=:f
            """
                ),
                {"u": requester_id, "f": addressee_id},
            ).fetchone()
            if already:
                return False, "Jesteście już znajomymi."

            # stwórz/odśwież pending
            s.execute(
                text(
                    """
                INSERT INTO friend_requests(requester_id, addressee_id, status)
                VALUES (:r, :a, 'pending')
                ON CONFLICT (requester_id, addressee_id)
                DO UPDATE SET status='pending', created_at=CURRENT_TIMESTAMP, responded_at=NULL
            """
                ),
                {"r": requester_id, "a": addressee_id},
            )

            # powiadomienie dla addressee
            s.execute(
                text(
                    """
                INSERT INTO notifications(user_id, type, payload)
                VALUES (:uid, 'friend_request', jsonb_build_object('from_user_id', :from_id))
            """
                ),
                {"uid": addressee_id, "from_id": requester_id},
            )

        return True, f"Wysłano zaproszenie do: {addressee_nick}"

    def list_incoming_requests(self, user_id: int):
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT fr.id, fr.created_at, u.id as from_id, u.nick, u.email, u.avatar_path
                FROM friend_requests fr
                JOIN users u ON u.id = fr.requester_id
                WHERE fr.addressee_id = :uid AND fr.status = 'pending'
                ORDER BY fr.created_at DESC
            """
                ),
                {"uid": user_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def list_outgoing_requests(self, user_id: int):
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT fr.id, fr.created_at, u.id as to_id, u.nick, u.email, u.avatar_path
                FROM friend_requests fr
                JOIN users u ON u.id = fr.addressee_id
                WHERE fr.requester_id = :uid AND fr.status = 'pending'
                ORDER BY fr.created_at DESC
            """
                ),
                {"uid": user_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def accept_request(self, user_id: int, request_id: int) -> tuple[bool, str]:
        with self.get_session() as s:
            req = s.execute(
                text(
                    """
                SELECT requester_id, addressee_id, status
                FROM friend_requests
                WHERE id=:id
            """
                ),
                {"id": request_id},
            ).fetchone()

            if not req:
                return False, "Nie znaleziono zaproszenia."
            if int(req._mapping["addressee_id"]) != user_id:
                return False, "To nie jest Twoje zaproszenie."
            if req._mapping["status"] != "pending":
                return False, "To zaproszenie nie jest już aktywne."

            requester_id = int(req._mapping["requester_id"])

            # friends (dwukierunkowo)
            s.execute(
                text(
                    """
                INSERT INTO friends(user_id, friend_id) VALUES (:u,:f) ON CONFLICT DO NOTHING
            """
                ),
                {"u": user_id, "f": requester_id},
            )
            s.execute(
                text(
                    """
                INSERT INTO friends(user_id, friend_id) VALUES (:u,:f) ON CONFLICT DO NOTHING
            """
                ),
                {"u": requester_id, "f": user_id},
            )

            # status request
            s.execute(
                text(
                    """
                UPDATE friend_requests
                SET status='accepted', responded_at=CURRENT_TIMESTAMP
                WHERE id=:id
            """
                ),
                {"id": request_id},
            )

            # powiadomienie dla requester
            s.execute(
                text(
                    """
                INSERT INTO notifications(user_id, type, payload)
                VALUES (:uid, 'friend_accept', jsonb_build_object('by_user_id', :by))
            """
                ),
                {"uid": requester_id, "by": user_id},
            )

        return True, "Zaproszenie zaakceptowane."

    def decline_request(self, user_id: int, request_id: int) -> tuple[bool, str]:
        with self.get_session() as s:
            req = s.execute(
                text(
                    """
                SELECT requester_id, addressee_id, status
                FROM friend_requests
                WHERE id=:id
            """
                ),
                {"id": request_id},
            ).fetchone()

            if not req:
                return False, "Nie znaleziono zaproszenia."
            if int(req._mapping["addressee_id"]) != user_id:
                return False, "To nie jest Twoje zaproszenie."
            if req._mapping["status"] != "pending":
                return False, "To zaproszenie nie jest już aktywne."

            requester_id = int(req._mapping["requester_id"])

            s.execute(
                text(
                    """
                UPDATE friend_requests
                SET status='declined', responded_at=CURRENT_TIMESTAMP
                WHERE id=:id
            """
                ),
                {"id": request_id},
            )

            s.execute(
                text(
                    """
                INSERT INTO notifications(user_id, type, payload)
                VALUES (:uid, 'friend_decline', jsonb_build_object('by_user_id', :by))
            """
                ),
                {"uid": requester_id, "by": user_id},
            )

        return True, "Zaproszenie odrzucone."

    def remove_friend(self, user_id: int, friend_id: int) -> tuple[bool, str]:
        with self.get_session() as s:
            s.execute(
                text("DELETE FROM friends WHERE user_id=:u AND friend_id=:f"),
                {"u": user_id, "f": friend_id},
            )
            s.execute(
                text("DELETE FROM friends WHERE user_id=:u AND friend_id=:f"),
                {"u": friend_id, "f": user_id},
            )
        return True, "Usunięto znajomą."

    def unread_notifications_count(self, user_id: int) -> int:
        with self.get_session() as s:
            row = s.execute(
                text(
                    """
                SELECT COUNT(*)::int AS c FROM notifications
                WHERE user_id=:u AND is_read=false
            """
                ),
                {"u": user_id},
            ).fetchone()
        return int(row._mapping["c"]) if row else 0

    def list_notifications(self, user_id: int, limit: int = 30):
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT id, type, payload, is_read, created_at
                FROM notifications
                WHERE user_id=:u
                ORDER BY created_at DESC
                LIMIT :lim
            """
                ),
                {"u": user_id, "lim": limit},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def mark_all_notifications_read(self, user_id: int):
        with self.get_session() as s:
            s.execute(
                text(
                    """
                UPDATE notifications SET is_read=true WHERE user_id=:u AND is_read=false
            """
                ),
                {"u": user_id},
            )

    def add_friend_by_email(self, user_id: int, friend_email: str) -> tuple[bool, str]:
        friend_email = (friend_email or "").strip().lower()
        if not friend_email:
            return False, "Podaj email."

        with self.get_session() as s:
            friend = s.execute(
                text("SELECT * FROM users WHERE email = :email"),
                {"email": friend_email},
            ).fetchone()

            if not friend:
                return False, "Nie znaleziono użytkownika o takim emailu."

            fid = int(friend._mapping["id"])
            fnick = friend._mapping["nick"]

            if fid == user_id:
                return False, "Nie możesz dodać siebie."

            # MVP: relacja dwukierunkowa, bez zaproszeń
            s.execute(
                text(
                    "INSERT INTO friends(user_id, friend_id) VALUES(:u, :f) ON CONFLICT DO NOTHING"
                ),
                {"u": user_id, "f": fid},
            )
            s.execute(
                text(
                    "INSERT INTO friends(user_id, friend_id) VALUES(:u, :f) ON CONFLICT DO NOTHING"
                ),
                {"u": fid, "f": user_id},
            )

        return True, f"Dodano: {fnick}"

    def update_avatar(self, user_id: int, avatar_path: str):
        with self.get_session() as s:
            s.execute(
                text("UPDATE users SET avatar_path = :p WHERE id = :id"),
                {"p": avatar_path, "id": user_id},
            )

    def create_workout(
        self,
        user_id: int,
        title: str,
        calories: Optional[int],
        fatigue: int,
        photo_path: Optional[str],
        video_url: Optional[str],
        comment: Optional[str],
        performed_at: Optional[str] = None,
    ) -> tuple[bool, str]:
        title = (title or "").strip()
        video_url = (video_url or "").strip() or None
        comment = (comment or "").strip() or None

        if not title:
            return False, "Podaj nazwę treningu."
        if fatigue < 1 or fatigue > 10:
            return False, "Zmęczenie musi być w zakresie 1–10."
        if video_url and not (
            video_url.startswith("http://") or video_url.startswith("https://")
        ):
            return False, "Link do wideo musi zaczynać się od http:// lub https://"

        with self.get_session() as s:
            s.execute(
                text(
                    """
                INSERT INTO workouts(user_id, title, calories, fatigue, photo_path, video_url, comment, performed_at)
                VALUES(:uid, :t, :c, :f, :p, :v, :m, :pa)
            """
                ),
                {
                    "uid": user_id,
                    "t": title,
                    "c": calories,
                    "f": fatigue,
                    "p": photo_path,
                    "v": video_url,
                    "m": comment,
                    "pa": performed_at,
                },
            )

        return True, "Dodano trening 💪"

    def get_workout_by_id_for_owner(self, workout_id: int, user_id: int):
        """Zwraca trening tylko jeśli należy do użytkownika (do edycji/usuwania)."""
        with self.get_session() as s:
            row = s.execute(
                text(
                    """
                SELECT * FROM workouts
                WHERE id = :wid AND user_id = :uid
            """
                ),
                {"wid": workout_id, "uid": user_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def update_workout(
        self,
        workout_id: int,
        user_id: int,
        title: str,
        calories: Optional[int],
        fatigue: int,
        new_photo_path: Optional[str],
        video_url: Optional[str],
        comment: Optional[str],
    ) -> tuple[bool, str]:
        title = (title or "").strip()
        video_url = (video_url or "").strip() or None
        comment = (comment or "").strip() or None

        if not title:
            return False, "Podaj nazwę treningu."
        if fatigue < 1 or fatigue > 10:
            return False, "Zmęczenie musi być w zakresie 1–10."
        if video_url and not (
            video_url.startswith("http://") or video_url.startswith("https://")
        ):
            return False, "Link do wideo musi zaczynać się od http:// lub https://"

        current = self.get_workout_by_id_for_owner(workout_id, user_id)
        if not current:
            return False, "Nie znaleziono treningu (albo nie masz uprawnień)."

        photo_path = (
            new_photo_path if new_photo_path is not None else current.get("photo_path")
        )

        with self.get_session() as s:
            s.execute(
                text(
                    """
                UPDATE workouts
                SET title=:t,
                    calories=:c,
                    fatigue=:f,
                    photo_path=:p,
                    video_url=:v,
                    comment=:m
                WHERE id=:wid AND user_id=:uid
            """
                ),
                {
                    "t": title,
                    "c": calories,
                    "f": fatigue,
                    "p": photo_path,
                    "v": video_url,
                    "m": comment,
                    "wid": workout_id,
                    "uid": user_id,
                },
            )
        return True, "Zapisano zmiany ✅"

    def delete_workout(self, workout_id: int, user_id: int) -> tuple[bool, str]:
        with self.get_session() as s:
            row = s.execute(
                text("SELECT 1 FROM workouts WHERE id=:wid AND user_id=:uid"),
                {"wid": workout_id, "uid": user_id},
            ).fetchone()
            if not row:
                return False, "Nie znaleziono treningu (albo nie masz uprawnień)."

            s.execute(
                text("DELETE FROM workouts WHERE id=:wid AND user_id=:uid"),
                {"wid": workout_id, "uid": user_id},
            )
        return True, "Usunięto trening 🗑️"

    def get_feed_workouts(self, user_id: int):
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT w.*, u.nick, u.avatar_path
                FROM workouts w
                JOIN users u ON u.id = w.user_id
                WHERE w.user_id = :uid
                OR w.user_id IN (SELECT friend_id FROM friends WHERE user_id = :uid)
                ORDER BY COALESCE(w.performed_at, w.created_at) DESC
                LIMIT 200
            """
                ),
                {"uid": user_id},
            ).fetchall()
        return [dict(r._mapping) for r in rows]

    def workouts_last_30_days_counts(self, user_id: int) -> pd.DataFrame:
        with self.get_session() as s:
            rows = s.execute(
                text(
                    """
                SELECT u.nick, COUNT(*)::int as cnt
                FROM workouts w
                JOIN users u ON u.id = w.user_id
                WHERE (w.user_id = :uid OR w.user_id IN (SELECT friend_id FROM friends WHERE user_id = :uid))
                AND w.created_at >= (NOW() - INTERVAL '30 days')
                GROUP BY u.nick
                ORDER BY cnt DESC, u.nick ASC
            """
                ),
                {"uid": user_id},
            ).fetchall()

        if not rows:
            return pd.DataFrame(columns=["nick", "cnt"])
        return pd.DataFrame([dict(r._mapping) for r in rows])

    def delete_notification(
        self, user_id: int, notification_id: int
    ) -> tuple[bool, str]:
        with self.get_session() as s:
            note = s.execute(
                text(
                    """
                SELECT id FROM notifications
                WHERE id=:nid AND user_id=:uid
            """
                ),
                {"nid": notification_id, "uid": user_id},
            ).fetchone()

            if not note:
                return False, "Nie znaleziono powiadomienia."

            s.execute(
                text(
                    """
                DELETE FROM notifications WHERE id=:nid AND user_id=:uid
            """
                ),
                {"nid": notification_id, "uid": user_id},
            )

        return True, "Usunięto powiadomienie."

    def get_user_by_id(self, user_id: int):
        with self.get_session() as s:
            row = s.execute(
                text("SELECT * FROM users WHERE id = :id"),
                {"id": user_id},
            ).fetchone()
        return dict(row._mapping) if row else None

    def change_password(
        self, user_id: int, old_password: str, new_password: str
    ) -> tuple[bool, str]:
        old_password = old_password or ""
        new_password = new_password or ""

        if len(new_password) < 8:
            return False, "Nowe hasło musi mieć minimum 8 znaków."

        with self.get_session() as s:
            row = s.execute(
                text("SELECT password_hash FROM users WHERE id = :id"),
                {"id": user_id},
            ).fetchone()

            if not row:
                return False, "Nie znaleziono użytkownika."

            password_hash = row._mapping["password_hash"]

            try:
                ok = bcrypt_sha256.verify(old_password, password_hash)
            except Exception:
                ok = False

            if not ok:
                return False, "Aktualne hasło jest nieprawidłowe."

            new_hash = bcrypt_sha256.hash(new_password)

            s.execute(
                text("UPDATE users SET password_hash = :ph WHERE id = :id"),
                {"ph": new_hash, "id": user_id},
            )

        return True, "Hasło zostało zmienione."
