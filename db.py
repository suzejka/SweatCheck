import os
from contextlib import contextmanager
from urllib.parse import quote_plus

from dotenv import load_dotenv
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

DATABASE_URL = (
    "postgresql+psycopg2://"
    f"{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}/{DB_NAME}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Tworzy tabele (MVP) jeśli nie istnieją."""
    with engine.begin() as conn:
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
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
