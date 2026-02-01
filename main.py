from __future__ import annotations

import base64
import io
import os
import time
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv
from nicegui import app, ui
from sqlalchemy import text

from auth import create_user, get_user_by_id
from auth import login as auth_login
from db import get_session, init_db
from storage import get_signed_url, save_image

load_dotenv()
# -------------------------
# Init
# -------------------------
init_db()

ui.add_head_html(
    """
<style id="mobile_header_footer_icon_only_css">
@media (max-width: 640px) {

  /* ukryj WSZYSTKO w treści buttona poza ikoną i badge */
  .mobile-icon-only-area .q-btn .q-btn__content > :not(.q-icon):not(.q-badge) {
    display: none !important;
  }

  /* dla pewności: Quasar czasem używa tych klas */
  .mobile-icon-only-area .q-btn .q-btn__label,
  .mobile-icon-only-area .q-btn .q-btn__content-text,
  .mobile-icon-only-area .q-btn .block {
    display: none !important;
  }

  .mobile-icon-only-area .q-btn .q-btn__content {
    gap: 0 !important;
    justify-content: center;
  }

  .mobile-icon-only-area .q-btn {
    min-width: 44px;
    min-height: 44px;
    padding: 8px 10px !important;
  }
}
</style>
""",
    shared=True,
)


PINK = "#A11D4E"  # bordo
BG = "#FFF6FA"  # jasny róż
PANEL = "#FFE3EF"  # pudrowy róż


def to_upload_url(file_path: str) -> str:
    # file_path to object_path w supabase bucket
    return get_signed_url_cached(file_path, expires_seconds=3600)


# -------------------------
# Session helpers
# -------------------------
def current_user():
    return app.storage.user.get("user")


def set_user(user: dict | None):
    app.storage.user["user"] = user


def require_login() -> bool:
    if not current_user():
        ui.navigate.to("/login")
        return False
    return True


def refresh_user_in_session():
    u = current_user()
    if not u:
        return
    fresh = get_user_by_id(u["id"])
    if fresh:
        set_user(fresh)


SIGNED_URL_TTL_SECONDS = 60 * 10  # 10 minut cache; signed url możesz robić np. na 1h


def _signed_url_cache():
    """Zwraca słownik cache w storage użytkownika."""
    cache = app.storage.user.get("signed_url_cache")
    if not isinstance(cache, dict):
        cache = {}
        app.storage.user["signed_url_cache"] = cache
    return cache


def get_signed_url_cached(object_path: str, *, expires_seconds: int = 3600) -> str:
    """
    Cache'uje signed URL dla object_path.
    expires_seconds: ważność samego signed URL (np. 3600 = 1h w supabase)
    Cache trzymamy krócej (SIGNED_URL_TTL_SECONDS), żeby nie ryzykować wygasłego linku.
    """
    if not object_path:
        return ""

    now = time.time()
    cache = _signed_url_cache()
    entry = cache.get(object_path)

    if entry and isinstance(entry, dict):
        url = entry.get("url", "")
        ts = float(entry.get("ts", 0))
        if url and (now - ts) < SIGNED_URL_TTL_SECONDS:
            return url

    url = get_signed_url(object_path, expires_seconds=expires_seconds) or ""
    cache[object_path] = {"url": url, "ts": now}
    return url


# -------------------------
# DB helpers
# -------------------------
def list_friends(user_id: int):
    with get_session() as s:
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


def update_nick(user_id: int, new_nick: str) -> tuple[bool, str]:
    new_nick = (new_nick or "").strip()
    if len(new_nick) < 2:
        return False, "Nick musi mieć min. 2 znaki."

    try:
        with get_session() as s:
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


def send_friend_request(requester_id: int, addressee_email: str) -> tuple[bool, str]:
    addressee_email = (addressee_email or "").strip().lower()
    if not addressee_email:
        return False, "Podaj email."

    with get_session() as s:
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


def list_incoming_requests(user_id: int):
    with get_session() as s:
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


def list_outgoing_requests(user_id: int):
    with get_session() as s:
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


def accept_request(user_id: int, request_id: int) -> tuple[bool, str]:
    with get_session() as s:
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


def decline_request(user_id: int, request_id: int) -> tuple[bool, str]:
    with get_session() as s:
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


def remove_friend(user_id: int, friend_id: int) -> tuple[bool, str]:
    with get_session() as s:
        s.execute(
            text("DELETE FROM friends WHERE user_id=:u AND friend_id=:f"),
            {"u": user_id, "f": friend_id},
        )
        s.execute(
            text("DELETE FROM friends WHERE user_id=:u AND friend_id=:f"),
            {"u": friend_id, "f": user_id},
        )
    return True, "Usunięto znajomą."


def unread_notifications_count(user_id: int) -> int:
    with get_session() as s:
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


def list_notifications(user_id: int, limit: int = 30):
    with get_session() as s:
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


def parse_notifications(user_id: int):
    notifications = list_notifications(user_id)
    parsed = []
    for n in notifications:
        p = dict(n)  # kopiuj
        p_payload = p.get("payload") or {}
        if p["type"] == "friend_request":
            from_user_id = p_payload.get("from_user_id")
            from_user = get_user_by_id(from_user_id) if from_user_id else None
            p["message"] = (
                f"Nowe zaproszenie od {from_user['nick']}"
                if from_user
                else "Nowe zaproszenie"
            )
            p["user_friendly_type"] = "Zaproszenie do znajomych"
            p["user_friendly_created_at"] = (
                p["created_at"].strftime("%Y-%m-%d %H:%M") if p["created_at"] else ""
            )
        elif p["type"] == "friend_accept":
            by_user_id = p_payload.get("by_user_id")
            by_user = get_user_by_id(by_user_id) if by_user_id else None
            p["message"] = (
                f"{by_user['nick']} zaakceptował(a) Twoje zaproszenie"
                if by_user
                else "Ktoś zaakceptował(a) Twoje zaproszenie"
            )
            p["user_friendly_type"] = "Zaakceptowano zaproszenie"
            p["user_friendly_created_at"] = (
                p["created_at"].strftime("%Y-%m-%d %H:%M") if p["created_at"] else ""
            )
        elif p["type"] == "friend_decline":
            by_user_id = p_payload.get("by_user_id")
            by_user = get_user_by_id(by_user_id) if by_user_id else None
            p["message"] = (
                f"{by_user['nick']} odrzucił(a) Twoje zaproszenie"
                if by_user
                else "Ktoś odrzucił(a) Twoje zaproszenie"
            )
            p["user_friendly_type"] = "Odrzucono zaproszenie"
            p["user_friendly_created_at"] = (
                p["created_at"].strftime("%Y-%m-%d %H:%M") if p["created_at"] else ""
            )
        else:
            p["message"] = "Nieznany typ powiadomienia"
        parsed.append(p)
    return parsed


def mark_all_notifications_read(user_id: int):
    with get_session() as s:
        s.execute(
            text(
                """
            UPDATE notifications SET is_read=true WHERE user_id=:u AND is_read=false
        """
            ),
            {"u": user_id},
        )


def add_friend_by_email(user_id: int, friend_email: str) -> tuple[bool, str]:
    friend_email = (friend_email or "").strip().lower()
    if not friend_email:
        return False, "Podaj email."

    with get_session() as s:
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


def update_avatar(user_id: int, avatar_path: str):
    with get_session() as s:
        s.execute(
            text("UPDATE users SET avatar_path = :p WHERE id = :id"),
            {"p": avatar_path, "id": user_id},
        )


def create_workout(
    user_id: int,
    title: str,
    calories: Optional[int],
    fatigue: int,
    photo_path: Optional[str],
    video_url: Optional[str],
) -> tuple[bool, str]:
    title = (title or "").strip()
    video_url = (video_url or "").strip() or None

    if not title:
        return False, "Podaj nazwę treningu."
    if fatigue < 1 or fatigue > 10:
        return False, "Zmęczenie musi być w zakresie 1–10."
    if video_url and not (
        video_url.startswith("http://") or video_url.startswith("https://")
    ):
        return False, "Link do wideo musi zaczynać się od http:// lub https://"

    with get_session() as s:
        s.execute(
            text(
                """
            INSERT INTO workouts(user_id, title, calories, fatigue, photo_path, video_url)
            VALUES(:uid, :t, :c, :f, :p, :v)
        """
            ),
            {
                "uid": user_id,
                "t": title,
                "c": calories,
                "f": fatigue,
                "p": photo_path,
                "v": video_url,
            },
        )

    return True, "Dodano trening 💪"


def get_feed_workouts(user_id: int):
    with get_session() as s:
        rows = s.execute(
            text(
                """
            SELECT w.*, u.nick, u.avatar_path
            FROM workouts w
            JOIN users u ON u.id = w.user_id
            WHERE w.user_id = :uid
               OR w.user_id IN (SELECT friend_id FROM friends WHERE user_id = :uid)
            ORDER BY w.created_at DESC
            LIMIT 200
        """
            ),
            {"uid": user_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def workouts_last_30_days_counts(user_id: int) -> pd.DataFrame:
    with get_session() as s:
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


# -------------------------
# UI helpers (mobile-ish)
# -------------------------


def logout():
    app.storage.user.clear()  # czyści całą sesję użytkownika
    ui.navigate.to("/login")  # przekierowanie na login


def nav_button(label: str, icon: str, path: str):
    # desktop/tablet
    ui.button(label, icon=icon, on_click=lambda: ui.navigate.to(path)).props(
        "flat round"
    ).classes("gt-xs")

    # mobile
    with ui.button(icon=icon, on_click=lambda: ui.navigate.to(path)).props(
        "flat round"
    ).classes("lt-sm"):
        ui.tooltip(label)


def app_shell(title: str, *, show_back: bool = False):
    ui.colors(primary=PINK, secondary=PANEL, accent=PINK)
    ui.query("body").style(f"background-color:{BG};")

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center"):
            if show_back:
                ui.button(
                    icon="arrow_back", on_click=lambda: ui.navigate.to("/")
                ).props("flat round")
            ui.label(title).classes("text-lg font-bold")

        if current_user():
            u = current_user()
            cnt = unread_notifications_count(int(u["id"]))
            with ui.element("div").classes("relative"):
                ui.button(
                    icon="notifications",
                    on_click=lambda: ui.navigate.to("/notifications"),
                ).props("flat round").classes("gt-xs text-white")

                with ui.button(
                    icon="notifications",
                    on_click=lambda: ui.navigate.to("/notifications"),
                ).props("flat round").classes("lt-sm text-white"):
                    ui.tooltip("🔔")

                if cnt > 0:
                    ui.badge(str(cnt)).classes("absolute -top-1 -right-1").style(
                        f"background:white !important; color:{PINK} !important;"
                    )

            ui.button("Wyloguj", icon="logout", on_click=logout).props(
                "flat round"
            ).classes("gt-xs text-white")

            with ui.button(icon="logout", on_click=logout).props("flat round").classes(
                "lt-sm text-white"
            ):
                ui.tooltip("Wyloguj")

    # bottom nav for mobile
    if current_user():
        with ui.footer().classes("w-full"):
            with ui.row().classes("w-full justify-around").style(
                f"background:{PANEL}; padding:10px;"
            ):
                nav_button("Feed", "dynamic_feed", "/")
                nav_button("Znajomi", "group", "/friends")
                nav_button("Dodaj", "add", "/add")
                nav_button("Raport", "insights", "/report")
                nav_button("Profil", "person", "/profile")


def card():
    return (
        ui.card()
        .classes("w-full")
        .style(
            "background:rgba(255,255,255,0.75); border:1px solid rgba(161,29,78,0.18); border-radius:18px;"
        )
    )


def center_column():
    return (
        ui.column()
        .classes("w-full items-stretch")
        .style("max-width:720px; margin:0 auto; padding: 12px;")
    )


# -------------------------
# Pages
# -------------------------
@ui.page("/login")
def page_login():
    app_shell("SweatCheck")

    with ui.column().classes("w-full items-stretch").style(
        "max-width:520px; margin: 0 auto; padding: 12px;"
    ):
        with card():
            ui.label("Zaloguj się").classes("text-base font-bold")
            email = ui.input("Email").props("type=email").classes("w-full")
            pwd = ui.input("Hasło").props("type=password").classes("w-full")
            msg = ui.label().classes("text-sm")

            def do_login():
                user = auth_login(email.value, pwd.value)
                if user:
                    set_user(user)
                    ui.navigate.to("/")
                else:
                    msg.set_text("Błędny email lub hasło.")
                    msg.style("color:#b00020;")

            ui.button("Zaloguj", on_click=do_login).classes("w-full").props(
                "unelevated"
            )

        with card():
            ui.label("Załóż konto").classes("text-base font-bold")
            nick = ui.input("Nick").classes("w-full")
            remail = ui.input("Email").props("type=email").classes("w-full")
            rpwd = (
                ui.input("Hasło (min. 8 znaków)")
                .props("type=password")
                .classes("w-full")
            )
            reg_msg = ui.label().classes("text-sm")

            def do_register():
                ok, text_ = create_user(nick.value, remail.value, rpwd.value)
                reg_msg.set_text(text_)
                reg_msg.style("color:#0b6b2d;" if ok else "color:#b00020;")

            ui.button("Utwórz konto", on_click=do_register).classes("w-full").props(
                "unelevated"
            )


@ui.page("/")
def page_feed():
    if not require_login():
        return
    refresh_user_in_session()

    app_shell("Tablica")

    u = current_user()
    workouts = get_feed_workouts(int(u["id"]))

    with center_column():
        if not workouts:
            with card():
                ui.label("Brak treningów. Dodaj swój pierwszy wpis w zakładce „Dodaj”.")
        else:
            for w in workouts:
                with card():
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center"):
                            if w.get("avatar_path"):
                                ui.image(to_upload_url(w["avatar_path"])).classes(
                                    "w-14 h-14 rounded-full"
                                )
                            else:
                                ui.icon("person").classes("text-2xl")

                            with ui.column().classes("gap-0"):
                                ui.label(f"{w['nick']} — {w['title']}").classes(
                                    "font-bold"
                                )
                                # created_at może być datetime lub string - normalizujemy do tekstu
                                ca = w["created_at"]
                                ui.label(str(ca)).classes("text-xs opacity-70")

                        ui.chip(f"Zmęczenie: {w['fatigue']}/10").style(
                            f"background:{PANEL}; color:#2A0A16;"
                        )

                    if w.get("calories") is not None:
                        ui.label(f"🔥 {w['calories']} kcal").classes("text-sm")

                    if w.get("photo_path"):
                        ui.image(to_upload_url(w["photo_path"])).classes(
                            "w-full rounded-xl"
                        )

                    if w.get("video_url"):
                        ui.link("🎬 Link do filmiku", w["video_url"]).classes("text-sm")


def delete_notification(user_id: int, notification_id: int) -> tuple[bool, str]:
    with get_session() as s:
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


@ui.page("/notifications")
def page_notifications():
    if not require_login():
        return
    refresh_user_in_session()
    app_shell("Powiadomienia")

    u = current_user()
    with center_column():
        ui.button(
            "Oznacz wszystkie jako przeczytane",
            on_click=lambda: (
                mark_all_notifications_read(int(u["id"])),
                ui.navigate.to("/notifications"),
            ),
        ).classes("w-full").props("unelevated")

        notes = parse_notifications(int(u["id"]))
        if not notes:
            with card():
                ui.label("Brak powiadomień.")
            return

        for n in notes:
            with card().classes("relative"):
                ui.button(
                    icon="delete",
                    on_click=lambda nid=n["id"]: (
                        delete_notification(int(u["id"]), nid),
                        ui.navigate.to("/notifications"),
                    ),
                ).props("flat round dense").classes("absolute top-2 right-2")
                ui.label(f"{n['user_friendly_type']}").classes("font-bold")
                ui.label(str(n["user_friendly_created_at"])).classes(
                    "text-xs opacity-70"
                )
                ui.label(str(n["message"])).classes("text-sm opacity-80")


@ui.page("/add")
def page_add_workout():
    if not require_login():
        return
    refresh_user_in_session()

    app_shell("Dodaj trening")

    u = current_user()
    photo_bytes: dict[str, Optional[bytes]] = {"data": None}

    async def on_photo_upload(e):
        data = None

        # Wariant A: bytes w e.content
        if hasattr(e, "content") and isinstance(
            getattr(e, "content"), (bytes, bytearray)
        ):
            data = e.content

        # Wariant B: file-like w e.file (czasem read() jest async)
        elif hasattr(e, "file") and hasattr(e.file, "read"):
            r = e.file.read()
            data = await r if hasattr(r, "__await__") else r

        # Wariant C: czasem e.value
        elif hasattr(e, "value"):
            v = e.value
            data = await v if hasattr(v, "__await__") else v

        if not isinstance(data, (bytes, bytearray)):
            ui.notify("Nie udało się odczytać pliku jako bytes.", type="negative")
            return

        photo_bytes["data"] = bytes(data)

    with center_column():
        with card():
            ui.label("Nowy trening").classes("text-base font-bold")

            title = ui.input("Nazwa treningu (np. 'Pilates 30 min')").classes("w-full")

            with ui.row().classes("w-full items-center"):
                use_cal = ui.checkbox("Wpisz kalorie (opcjonalnie)")
                calories = ui.number(
                    "Spalone kalorie", value=300, min=0, max=5000
                ).classes("w-full")
                calories.set_visibility(False)

            def toggle_cal():
                calories.set_visibility(bool(use_cal.value))

            use_cal.on("update:model-value", lambda e: toggle_cal())
            toggle_cal()

            ui.label("Poziom zmęczenia po (1–10)").classes("text-sm opacity-80")
            fatigue = ui.slider(min=1, max=10, value=6).props("label-always")

            video_url = ui.input("Link do filmiku (opcjonalnie)").classes("w-full")

            ui.label("Zdjęcie (opcjonalnie)").classes("text-sm opacity-80")
            ui.upload(
                on_upload=on_photo_upload,
                auto_upload=True,
                multiple=False,
            ).props('accept=".jpg,.jpeg,.png"').classes("w-full")

            msg = ui.label().classes("text-sm")

            async def do_submit():
                ppath = None
                data = photo_bytes["data"]

                if hasattr(data, "__await__"):
                    data = await data

                if data:
                    ppath = save_image(data, int(u["id"]), "workout")

                ok, text_ = create_workout(
                    user_id=int(u["id"]),
                    title=title.value,
                    calories=int(calories.value) if use_cal.value else None,
                    fatigue=int(fatigue.value),
                    photo_path=ppath,
                    video_url=video_url.value,
                )
                msg.set_text(text_)
                msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    ui.navigate.to("/")

            ui.button("Dodaj", on_click=do_submit).classes("w-full").props("unelevated")


@ui.page("/friends")
def page_friends():
    if not require_login():
        return
    refresh_user_in_session()

    app_shell("Znajomi")

    u = current_user()
    uid = int(u["id"])

    with center_column():
        # --- Send friend request ---
        with card():
            ui.label("Dodaj znajomą po emailu").classes("font-bold")
            email = ui.input("Email znajomej").props("type=email").classes("w-full")
            msg = ui.label().classes("text-sm")

            def do_add():
                ok, text_ = send_friend_request(uid, email.value)
                msg.set_text(text_)
                msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    ui.navigate.to("/friends")

            ui.button("Wyślij zaproszenie", icon="person_add", on_click=do_add).classes(
                "w-full"
            ).props("unelevated")

        # --- Incoming requests ---
        incoming = list_incoming_requests(uid)
        with card():
            ui.label("Zaproszenia do Ciebie").classes("font-bold")
            if not incoming:
                ui.label("Brak nowych zaproszeń.").classes("opacity-80")
            else:
                for r in incoming:
                    rid = int(r["id"])
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center"):
                            if r.get("avatar_path"):
                                ui.image(to_upload_url(r["avatar_path"])).classes(
                                    "w-16 h-16 rounded-full"
                                )
                            else:
                                ui.icon("person").classes("text-3xl")
                            with ui.column().classes("gap-0"):
                                ui.label(r["nick"]).classes("font-bold")
                                ui.label(r["email"]).classes("text-xs opacity-70")

                        with ui.row().classes("items-center"):

                            def _accept(rid=rid):
                                ok, txt = accept_request(uid, rid)
                                ui.notify(txt, type="positive" if ok else "negative")
                                ui.navigate.to("/friends")

                            def _decline(rid=rid):
                                ok, txt = decline_request(uid, rid)
                                ui.notify(txt, type="positive" if ok else "negative")
                                ui.navigate.to("/friends")

                            ui.button("Akceptuj", icon="check", on_click=_accept).props(
                                "unelevated"
                            )
                            ui.button("Odrzuć", icon="close", on_click=_decline).props(
                                "flat"
                            )

        # --- Outgoing requests ---
        outgoing = list_outgoing_requests(uid)
        with card():
            ui.label("Wysłane zaproszenia").classes("font-bold")
            if not outgoing:
                ui.label("Brak oczekujących zaproszeń.").classes("opacity-80")
            else:
                for r in outgoing:
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center"):
                            if r.get("avatar_path"):
                                ui.image(to_upload_url(r["avatar_path"])).classes(
                                    "w-16 h-16 rounded-full"
                                )
                            else:
                                ui.icon("person").classes("text-3xl")
                            with ui.column().classes("gap-0"):
                                ui.label(r["nick"]).classes("font-bold")
                                ui.label(r["email"]).classes("text-xs opacity-70")
                        ui.chip("pending").style(f"background:{PANEL}; color:#2A0A16;")

        # --- Friends list + remove ---
        friends = list_friends(uid)
        with card():
            ui.label("Twoi znajomi").classes("font-bold")
            if not friends:
                ui.label("Nie masz jeszcze znajomych w aplikacji.").classes(
                    "opacity-80"
                )
            else:
                for f in friends:
                    fid = int(f["id"])
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center"):
                            if f.get("avatar_path"):
                                ui.image(to_upload_url(f["avatar_path"])).classes(
                                    "w-16 h-16 rounded-full"
                                )
                            else:
                                ui.icon("person").classes("text-3xl")
                            with ui.column().classes("gap-0"):
                                ui.label(f["nick"]).classes("font-bold")
                                ui.label(f["email"]).classes("text-xs opacity-70")

                        def _remove(fid=fid):
                            ok, txt = remove_friend(uid, fid)
                            ui.notify(txt, type="positive" if ok else "negative")
                            ui.navigate.to("/friends")

                        ui.button("Usuń", icon="person_remove", on_click=_remove).props(
                            "flat"
                        )


@ui.page("/profile")
def page_profile():
    if not require_login():
        return
    refresh_user_in_session()

    app_shell("Profil")

    u = current_user()
    avatar_bytes: dict[str, Optional[bytes]] = {"data": None}

    async def on_avatar_upload(e):
        data = None

        # Wariant A: bytes w e.content
        if hasattr(e, "content") and isinstance(
            getattr(e, "content"), (bytes, bytearray)
        ):
            data = e.content

        # Wariant B: file-like w e.file (czasem read() jest async)
        elif hasattr(e, "file") and hasattr(e.file, "read"):
            r = e.file.read()
            data = await r if hasattr(r, "__await__") else r

        # Wariant C: czasem e.value
        elif hasattr(e, "value"):
            v = e.value
            data = await v if hasattr(v, "__await__") else v

        if not isinstance(data, (bytes, bytearray)):
            ui.notify("Nie udało się odczytać avatara jako bytes.", type="negative")
            return

        avatar_bytes["data"] = bytes(data)

    with center_column():
        with card():
            ui.label("Avatar").classes("font-bold")

            if u.get("avatar_path"):
                ui.image(to_upload_url(u["avatar_path"])).classes(
                    "w-24 h-24 rounded-full"
                )
            else:
                ui.label("Brak avatara.").classes("opacity-80")

            ui.upload(
                on_upload=on_avatar_upload,
                auto_upload=True,
                multiple=False,
            ).props('accept=".jpg,.jpeg,.png"').classes("w-full")

            msg = ui.label().classes("text-sm")

            async def save_avatar():
                data = avatar_bytes["data"]
                if not data:
                    msg.set_text("Najpierw wybierz plik.")
                    msg.style("color:#b00020;")
                    return

                # jeśli mimo wszystko wpadło coroutine
                if hasattr(data, "__await__"):
                    data = await data

                path = save_image(data, int(u["id"]), "avatar")
                update_avatar(int(u["id"]), path)

                fresh = get_user_by_id(int(u["id"]))
                set_user(fresh)
                ui.navigate.to("/profile")

            ui.button("Zapisz avatar", on_click=save_avatar).classes("w-full").props(
                "unelevated"
            )

            with card():
                ui.label("Dane").classes("font-bold")

                nick_input = ui.input("Nick", value=u["nick"]).classes("w-full")
                nick_msg = ui.label().classes("text-sm")

                def save_nick():
                    ok, txt = update_nick(int(u["id"]), nick_input.value)
                    nick_msg.set_text(txt)
                    nick_msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                    if ok:
                        fresh = get_user_by_id(int(u["id"]))
                        set_user(fresh)

                ui.button("Zapisz nick", on_click=save_nick).classes("w-full").props(
                    "unelevated"
                )

                ui.label(f"Email: {u['email']}").classes("opacity-80")


@ui.page("/report")
def page_report():
    if not require_login():
        return
    refresh_user_in_session()

    app_shell("Raport 30 dni")

    u = current_user()
    df = workouts_last_30_days_counts(int(u["id"]))

    with center_column():
        with card():
            ui.label("Kto ile treningów zrobił (ostatnie 30 dni)").classes("font-bold")
            if df.empty:
                ui.label(
                    "Brak treningów w ostatnich 30 dniach (Ty i znajomi)."
                ).classes("opacity-80")
            else:
                ui.table(
                    columns=[
                        {"name": "nick", "label": "Osoba", "field": "nick"},
                        {"name": "cnt", "label": "Treningi", "field": "cnt"},
                    ],
                    rows=df.to_dict(orient="records"),
                    row_key="nick",
                ).classes("w-full")

        if not df.empty:
            fig = plt.figure()
            plt.bar(df["nick"], df["cnt"])
            plt.xticks(rotation=25, ha="right")
            plt.ylabel("Liczba treningów (30 dni)")
            plt.title("Aktywność — ostatnie 30 dni")

            buf = io.BytesIO()
            fig.tight_layout()
            fig.savefig(buf, format="png", dpi=160)
            plt.close(fig)
            buf.seek(0)

            with card():
                ui.label("Wykres").classes("font-bold")
                png_bytes = buf.getvalue()
                data_url = "data:image/png;base64," + base64.b64encode(
                    png_bytes
                ).decode("ascii")
                ui.image(data_url).classes("w-full rounded-xl")


# -------------------------
# Run
# -------------------------
if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.getenv("PORT", "8080"))
    ui.run(
        title="SweatCheck",
        host="0.0.0.0",
        reload=False,
        workers=1,
        port=port,
        storage_secret=os.getenv("STORAGE_SECRET"),
    )

    app.on_connect(
        lambda: print(
            [
                i[1]
                for i in ui.context.client.environ["asgi.scope"]["headers"]
                if i[0] == b"user-agent"
            ]
        )
    )
