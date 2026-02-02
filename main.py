from __future__ import annotations

import base64
import io
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
from dotenv import load_dotenv
from nicegui import app, ui

from auth import create_user
from auth import login as auth_login
from services.db_service import DatabaseService
from services.notification_service import NotificationService
from services.user_service import UserService
from storage import get_signed_url, save_image
from utils.helpers import domain

load_dotenv()

user_service = UserService(app, ui)
database_service = DatabaseService()
notification_service = NotificationService()

# -------------------------
# Init
# -------------------------
app.add_static_files("/static", str(Path(__file__).parent / "static"))
database_service.init_db()

# PRIMARY = "#A11D4E"
# BG = "#FFF6FA"
# PANEL = "#FFE3EF"


PRIMARY = "#8E1D4A"  # bordo / wine
PRIMARY_SOFT = "#B03A67"

BG = "#FAF7F9"  # bardzo jasny różowy off-white
PANEL = "#FFFFFF"  # powierzchnie kart

TEXT = "#1A1A1A"
MUTED = "#6B5A63"

BORDER = "rgba(140, 30, 75, 0.12)"

ui.add_head_html(
    """
<script>
(function() {
  function setFavicon(url) {
    const rels = ['icon', 'shortcut icon', 'apple-touch-icon'];
    rels.forEach(rel => {
      let link = document.querySelector('link[rel="' + rel + '"]');
      if (!link) {
        link = document.createElement('link');
        link.rel = rel;
        document.head.appendChild(link);
      }
      link.type = 'image/png';
      link.href = url;
    });
  }
  setFavicon('/static/favicon.png');
})();
</script>
""",
    shared=True,
)

ui.add_head_html(
    """
<style>
:root {
  --bg: #FAF7F9;
  --surface: #FFFFFF;
  --text: #1A1A1A;
  --muted: #6B5A63;

  --primary: #8E1D4A;
  --primary-soft: #B03A67;

  --border: rgba(140, 30, 75, 0.12);

  --shadow-soft: 0 8px 24px rgba(0,0,0,.06);
  --radius-lg: 22px;
  --radius-md: 16px;
}

html, body {
  background: var(--bg) !important;
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont,
               "SF Pro Display", "SF Pro Text",
               "Segoe UI", Roboto, Arial;
}

/* Header: iOS glass */
.q-header {
  background: rgba(255,255,255,.75) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
}

/* Footer glass */
.q-footer {
  background: rgba(255,255,255,.78) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-top: 1px solid var(--border);
}

/* Apple card */
.apple-card {
  background: rgba(255,255,255,.88) !important;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) !important;
  box-shadow: var(--shadow-soft);
}

/* Inputs */
.q-field__control {
  border-radius: var(--radius-md) !important;
}

/* Buttons = pill */
.q-btn {
  border-radius: 999px !important;
  font-weight: 600;
}

/* Bordo primary button */
.apple-primary {
  background: var(--primary) !important;
  color: white !important;
  box-shadow: 0 10px 22px rgba(142, 29, 74, 0.22);
}

/* Subtle secondary */
.apple-secondary {
  background: rgba(142, 29, 74, 0.08) !important;
  color: var(--primary) !important;
}

/* Muted helper text */
.apple-muted {
  color: var(--muted);
}
                 
.q-header, .q-header * {
  color: var(--text) !important;
}

.q-header .q-btn,
.q-header .q-icon {
  color: var(--primary) !important;
}

/* “Wyloguj” (z tekstem) jako subtelny pill */
.q-header .q-btn .q-btn__content {
  font-weight: 600;
}
.apple-linkcard {
  display: block;
  width: 100%;
  text-decoration: none !important;
  color: var(--text) !important;
  background: rgba(255,255,255,.78);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: 0 8px 24px rgba(0,0,0,.05);
  padding: 12px 14px;
  transition: transform .08s ease, box-shadow .08s ease;
}
.apple-linkcard:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 26px rgba(0,0,0,.07);
}
.apple-linkcard .sub {
  color: var(--muted);
  font-size: 12px;
  margin-top: 2px;
}


/* Dodatkowo: sam input/textarea (placeholder siedzi tutaj) */
.q-field__native,
.q-field__input {
  padding-left: 0 !important;   /* żeby nie dublować paddingu */
}

/* Jeżeli masz ikony prepend/append (np. kalendarz), lekko je odsuń */
.q-field__marginal {
  padding-left: 6px !important;
  padding-right: 6px !important;
}

.q-field__control-container {
  padding-left: 14px !important;
  padding-right: 12px !important;
}

/* 2) QUASAR "placeholder" = label */
.q-field__label {
  padding-left: 14px !important;   /* przesuwa szary tekst w prawo */
}

/* 3) Gdy label "pływa" nad polem (po focus / gdy ma wartość) – żeby nie uciekał */
.q-field--float .q-field__label {
  padding-left: 14px !important;
}

/* 4) Jeśli gdzieś użyjesz prawdziwego placeholdera HTML */
.q-field__native::placeholder,
.q-field__input::placeholder {
  padding-left: 0 !important;      /* padding jest na containerze */
}
/* Ładny markdown w notyfikacjach */
.notice-md {
  font-size: 14px;
  line-height: 1.35;
  color: rgba(26,26,26,.85);
  white-space: pre-line;
}

.notice-md p { margin: 6px 0; }
.notice-md ul, .notice-md ol { margin: 6px 0 6px 18px; }
.notice-md li { margin: 4px 0; }

.notice-md code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.92em;
  padding: 2px 6px;
  border-radius: 8px;
  background: rgba(142, 29, 74, 0.08);
}

.notice-md pre {
  padding: 10px 12px;
  border-radius: 14px;
  overflow-x: auto;
  background: rgba(0,0,0,.04);
}

.notice-md blockquote {
  margin: 8px 0;
  padding-left: 10px;
  border-left: 3px solid rgba(140, 30, 75, 0.25);
  color: rgba(26,26,26,.75);
}

.notice-md a {
  color: #8E1D4A;
  text-decoration: none;
}
.notice-md a:hover { text-decoration: underline; }
</style>
                
""",
    shared=True,
)

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

ui.add_head_html(
    """
<link rel="stylesheet" href="https://unpkg.com/cropperjs@1.6.2/dist/cropper.min.css">
<script src="https://unpkg.com/cropperjs@1.6.2/dist/cropper.min.js"></script>

<style>
/* Okrągły podgląd jak avatar */
#avatar_crop_preview {
  width: 96px;
  height: 96px;
  border-radius: 9999px;
  overflow: hidden;
  border: 1px solid rgba(0,0,0,.08);
  box-shadow: 0 6px 18px rgba(0,0,0,.06);
}
                 
#avatar_crop_img {
  max-width: 100%;
  display: block;
}

/* Żeby overlay był widoczny */
.cropper-container { max-width: 100% !important; }

/* Zmniejsz “grubość” uploadu w dialogu */
.avatar-upload .q-uploader {
  border-radius: 18px !important;
}
.avatar-upload .q-uploader__header {
  min-height: 44px !important;
  padding: 8px 10px !important;
}
.avatar-upload .q-uploader__list {
  display: none !important; /* ukrywa wielką listę postępu */
}
</style>
""",
    shared=True,
)


def to_upload_url(file_path: str) -> str:
    # file_path to object_path w supabase bucket
    return get_signed_url_cached(file_path, expires_seconds=3600)


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
    ui.colors(primary=PRIMARY, secondary=PANEL, accent=PRIMARY)
    ui.query("body").style(f"background-color:{BG};")

    with ui.header(elevated=True).classes("items-center justify-between"):
        with ui.row().classes("items-center"):
            if show_back:
                ui.button(
                    icon="arrow_back", on_click=lambda: ui.navigate.to("/")
                ).props("flat round")
            ui.image("/static/favicon.png").style("height:40px; width:40px;")

        if user_service.current_user():
            u = user_service.current_user()
            is_admin = (u.get("role") == "ADMIN")

            if is_admin:
                ui.button("Panel admina", icon="admin_panel_settings",
                        on_click=lambda: ui.navigate.to("/admin")
                ).props("flat round").classes("gt-xs")

                with ui.button(icon="admin_panel_settings",
                            on_click=lambda: ui.navigate.to("/admin")
                ).props("flat round").classes("lt-sm"):
                    ui.tooltip("Panel admina")
            cnt = database_service.unread_notifications_count(int(u["id"]))
            with ui.element("div").classes("relative"):
                ui.button(
                    icon="notifications",
                    on_click=lambda: ui.navigate.to("/notifications"),
                ).props("flat round").classes("gt-xs")

                with ui.button(
                    icon="notifications",
                    on_click=lambda: ui.navigate.to("/notifications"),
                ).props("flat round").classes("lt-sm"):
                    ui.tooltip("🔔")

                if cnt > 0:
                    ui.badge(str(cnt)).classes("absolute -top-1 -right-1").style(
                        f"background:{PRIMARY_SOFT} !important; color:{BG} !important;"
                    )

            ui.button("Wyloguj", icon="logout", on_click=user_service.logout).props(
                "flat round"
            ).classes("gt-xs")

            with ui.button(icon="logout", on_click=user_service.logout).props(
                "flat round"
            ).classes("lt-sm"):
                ui.tooltip("Wyloguj")

    # bottom nav for mobile
    if user_service.current_user():
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
    return ui.card().classes("w-full apple-card")


def center_column():
    return (
        ui.column()
        .classes("w-full items-stretch")
        .style("max-width:720px; margin:0 auto; padding:18px;")
    )


# -------------------------
# Pages
# -------------------------

@ui.page("/admin")
def page_admin():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()
    app_shell("Panel admina", show_back=True)

    u = user_service.current_user()
    if u.get("role") != "ADMIN":
        ui.notify("Brak uprawnień.", type="negative")
        ui.navigate.to("/")
        return

    with center_column():
        with card():
            ui.label("Wyślij powiadomienie do wszystkich").classes("text-base font-bold")
            msg = ui.textarea("Treść").classes("w-full")
            type_ = ui.input("Typ (opcjonalnie)", value="admin_broadcast").classes("w-full")
            status = ui.label("").classes("text-sm")

            def send():
                ok, txt = database_service.broadcast_notification(type_=type_.value, message=msg.value)
                status.set_text(txt)
                status.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    msg.value = ""
                    ui.notify("Wysłano ✅", type="positive")

            ui.button("Wyślij", icon="send", on_click=send).classes("w-full apple-primary").props("unelevated")

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
                    user_service.set_user(user)
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
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()

    app_shell("Tablica")

    u = user_service.current_user()
    workouts = database_service.get_feed_workouts(int(u["id"]))

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
                                    "text-base font-semibold"
                                )
                                # created_at może być datetime lub string - normalizujemy do tekstu
                                dt = w.get("performed_at") or w.get("created_at")
                                ts = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                                ui.label(ts).classes("text-sm apple-muted")

                        with ui.row().classes("items-center"):
                            ui.chip(f"Zmęczenie: {w['fatigue']}/10").style(
                                f"background:{PANEL}; color:{BG};"
                            )

                            if int(w.get("user_id", -1)) == int(u["id"]):
                                ui.button(
                                    icon="edit",
                                    on_click=lambda wid=int(w["id"]): ui.navigate.to(
                                        f"/workout/{wid}/edit"
                                    ),
                                ).props("flat round dense")

                                ui.button(
                                    icon="delete",
                                    on_click=lambda wid=int(w["id"]): (
                                        database_service.delete_workout(
                                            wid, int(u["id"])
                                        ),
                                        ui.navigate.to("/"),
                                    ),
                                ).props("flat round dense")

                    if w.get("calories") is not None:
                        ui.label(f"🔥 {w['calories']} kcal").classes(
                            "text-sm apple-muted italic"
                        )

                    if w.get("comment"):
                        ui.label(f"💬 {w['comment']}").classes("text-sm opacity-90")

                    if w.get("photo_path"):
                        ui.image(to_upload_url(w["photo_path"])).classes(
                            "w-full rounded-xl"
                        )

                    if w.get("video_url"):
                        url = w["video_url"]
                        with ui.link(target=url).classes("apple-linkcard"):
                            with ui.row().classes(
                                "w-full items-center justify-between no-wrap"
                            ):
                                with ui.row().classes("items-center no-wrap"):
                                    ui.icon("play_circle").classes("text-2xl").style(
                                        f"color:{PRIMARY};"
                                    )
                                    with ui.column().classes("gap-0"):
                                        ui.label("Film z treningu").classes(
                                            "text-sm font-semibold"
                                        )
                                        ui.label(domain(url)).classes("sub")
                                ui.icon("chevron_right").classes("text-xl").style(
                                    "opacity:.55;"
                                )


@ui.page("/notifications")
def page_notifications():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()
    app_shell("Powiadomienia")

    u = user_service.current_user()
    with center_column():
        ui.button(
            "Oznacz wszystkie jako przeczytane",
            on_click=lambda: (
                database_service.mark_all_notifications_read(int(u["id"])),
                ui.navigate.to("/notifications"),
            ),
        ).classes("w-full").props("unelevated")

        notes = notification_service.parse_notifications(int(u["id"]))
        if not notes:
            with card():
                ui.label("Brak powiadomień.")
            return

        for n in notes:
            with card().classes("relative"):
                ui.button(
                    icon="delete",
                    on_click=lambda nid=n["id"]: (
                        database_service.delete_notification(int(u["id"]), nid),
                        ui.navigate.to("/notifications"),
                    ),
                ).props("flat round dense").classes("absolute top-2 right-2")
                ui.label(f"{n['user_friendly_type']}").classes("font-bold")
                ui.label(str(n["user_friendly_created_at"])).classes(
                    "text-xs opacity-70"
                )
                ui.markdown(str(n["message"])).classes("notice-md")


@ui.page("/add")
def page_add_workout():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()

    app_shell("Dodaj trening")

    u = user_service.current_user()
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
            today_iso = date.today().isoformat()

            ui.label("Kiedy był trening?").classes("text-sm opacity-80")

            with ui.row().classes("w-full items-center"):
                with ui.input(value=today_iso).classes("w-full") as workout_date:
                    with ui.menu().props("no-parent-event") as menu:
                        with ui.date().bind_value(workout_date):
                            with ui.row().classes("justify-end"):
                                ui.button("Zamknij", on_click=menu.close).props("flat")
                    with workout_date.add_slot("append"):
                        ui.icon("edit_calendar").on("click", menu.open).classes(
                            "cursor-pointer"
                        )

            ui.label("Poziom zmęczenia po (1–10)").classes("text-sm opacity-80")
            fatigue = ui.slider(min=1, max=10, value=5).props("label-always")

            calories = ui.number(
                "Spalone kalorie (opcjonalnie)", min=0, max=5000
            ).classes("w-full")

            video_url = ui.input("Link do filmiku (opcjonalnie)").classes("w-full")
            comment = ui.textarea("Komentarz (opcjonalnie)").classes("w-full")

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

                selected_date = workout_date.value  # YYYY-MM-DD
                selected_time = "00:00"

                if selected_date == date.today().isoformat():
                    selected_time = datetime.now().strftime("%H:%M")

                performed_at = datetime.fromisoformat(
                    f"{selected_date} {selected_time}:00"
                )

                ok, text_ = database_service.create_workout(
                    user_id=int(u["id"]),
                    title=title.value,
                    calories=int(calories.value),
                    fatigue=int(fatigue.value),
                    photo_path=ppath,
                    video_url=video_url.value,
                    comment=comment.value,
                    performed_at=performed_at,
                )
                msg.set_text(text_)
                msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    ui.navigate.to("/")

            ui.button("Dodaj", on_click=do_submit).classes(
                "w-full apple-primary"
            ).props("unelevated")


@ui.page("/workout/{workout_id:int}/edit")
def page_edit_workout(workout_id: int):
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()
    app_shell("Edytuj trening", show_back=True)

    u = user_service.current_user()
    uid = int(u["id"])

    w = database_service.get_workout_by_id_for_owner(int(workout_id), uid)
    if not w:
        ui.notify("Nie znaleziono treningu (albo nie masz uprawnień).", type="negative")
        ui.navigate.to("/")
        return

    photo_bytes: dict[str, Optional[bytes]] = {"data": None}

    async def on_photo_upload(e):
        data = None
        if hasattr(e, "content") and isinstance(
            getattr(e, "content"), (bytes, bytearray)
        ):
            data = e.content
        elif hasattr(e, "file") and hasattr(e.file, "read"):
            r = e.file.read()
            data = await r if hasattr(r, "__await__") else r
        elif hasattr(e, "value"):
            v = e.value
            data = await v if hasattr(v, "__await__") else v

        if not isinstance(data, (bytes, bytearray)):
            ui.notify("Nie udało się odczytać pliku jako bytes.", type="negative")
            return
        photo_bytes["data"] = bytes(data)

    with center_column():
        with card():
            ui.label("Edytuj trening").classes("text-base font-bold")

            title = ui.input("Nazwa treningu", value=w.get("title") or "").classes(
                "w-full"
            )

            with ui.row().classes("w-full items-center"):
                use_cal = ui.checkbox(
                    "Wpisz kalorie (opcjonalnie)", value=w.get("calories") is not None
                )
                calories = ui.number(
                    "Spalone kalorie",
                    value=int(w["calories"]) if w.get("calories") is not None else 300,
                    min=0,
                    max=5000,
                ).classes("w-full")
                calories.set_visibility(bool(use_cal.value))

            def toggle_cal():
                calories.set_visibility(bool(use_cal.value))

            use_cal.on("update:model-value", lambda e: toggle_cal())
            toggle_cal()

            ui.label("Poziom zmęczenia po (1–10)").classes("text-sm opacity-80")
            fatigue = ui.slider(min=1, max=10, value=int(w.get("fatigue") or 6)).props(
                "label-always"
            )

            video_url = ui.input(
                "Link do filmiku (opcjonalnie)", value=w.get("video_url") or ""
            ).classes("w-full")
            comment = ui.textarea(
                "Komentarz (opcjonalnie)", value=w.get("comment") or ""
            ).classes("w-full")

            if w.get("photo_path"):
                ui.label("Aktualne zdjęcie").classes("text-sm opacity-80")
                ui.image(to_upload_url(w["photo_path"])).classes("w-full rounded-xl")

            ui.label("Podmień zdjęcie (opcjonalnie)").classes("text-sm opacity-80")
            ui.upload(
                on_upload=on_photo_upload, auto_upload=True, multiple=False
            ).props('accept=".jpg,.jpeg,.png"').classes("w-full")

            msg = ui.label().classes("text-sm")

            async def do_save():
                new_photo_path = None
                data = photo_bytes["data"]
                if hasattr(data, "__await__"):
                    data = await data
                if data:
                    new_photo_path = save_image(data, uid, "workout")

                ok, txt = database_service.update_workout(
                    workout_id=int(workout_id),
                    user_id=uid,
                    title=title.value,
                    calories=int(calories.value) if use_cal.value else None,
                    fatigue=int(fatigue.value),
                    new_photo_path=new_photo_path,
                    video_url=video_url.value,
                    comment=comment.value,
                )
                msg.set_text(txt)
                msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    ui.navigate.to("/")

            ui.button("Zapisz", icon="save", on_click=do_save).classes(
                "w-full apple-primary"
            ).props("unelevated")


@ui.page("/friends")
def page_friends():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()

    app_shell("Znajomi")

    u = user_service.current_user()
    uid = int(u["id"])

    with center_column():
        # --- Send friend request ---
        with card():
            ui.label("Dodaj znajomą po emailu").classes("font-bold")
            email = ui.input("Email znajomej").props("type=email").classes("w-full")
            msg = ui.label().classes("text-sm")

            def do_add():
                ok, text_ = database_service.send_friend_request(uid, email.value)
                msg.set_text(text_)
                msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                if ok:
                    ui.navigate.to("/friends")

            ui.button("Wyślij zaproszenie", icon="person_add", on_click=do_add).classes(
                "w-full apple-primary"
            ).props("unelevated")

        # --- Incoming requests ---
        incoming = database_service.list_incoming_requests(uid)
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
                                ok, txt = database_service.accept_request(uid, rid)
                                ui.notify(txt, type="positive" if ok else "negative")
                                ui.navigate.to("/friends")

                            def _decline(rid=rid):
                                ok, txt = database_service.decline_request(uid, rid)
                                ui.notify(txt, type="positive" if ok else "negative")
                                ui.navigate.to("/friends")

                            ui.button(
                                "Akceptuj", icon="check", on_click=_accept
                            ).classes("w-full apple-primary").props("unelevated")
                            ui.button(
                                "Odrzuć", icon="close", on_click=_decline
                            ).classes("w-full apple-secondary").props("flat")

        # --- Outgoing requests ---
        outgoing = database_service.list_outgoing_requests(uid)
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
        friends = database_service.list_friends(uid)
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
                            ok, txt = database_service.remove_friend(uid, fid)
                            ui.notify(txt, type="positive" if ok else "negative")
                            ui.navigate.to("/friends")

                        ui.button(
                            "Usuń", icon="person_remove", on_click=_remove
                        ).classes("w-full apple-secondary").props("flat")


@ui.page("/profile")
def page_profile():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()

    app_shell("Profil")

    u = user_service.current_user()
    uid = int(u["id"])

    avatar_bytes: dict[str, Optional[bytes]] = {"data": None}

    dlg = ui.dialog()
    crop_img = None  # ui.image w dialogu
    status = None  # ui.label w dialogu

    def open_avatar_dialog():
        avatar_bytes["data"] = None
        if status:
            status.set_text("Wybierz zdjęcie, żeby przyciąć.")
        dlg.open()

    def delete_avatar():
        database_service.update_avatar(uid, None)
        fresh = database_service.get_user_by_id(uid)
        user_service.set_user(fresh)
        ui.navigate.to("/profile")

    async def on_avatar_upload(e):
        data = None

        if hasattr(e, "content") and isinstance(
            getattr(e, "content"), (bytes, bytearray)
        ):
            data = e.content
        elif hasattr(e, "file") and hasattr(e.file, "read"):
            r = e.file.read()
            data = await r if hasattr(r, "__await__") else r
        elif hasattr(e, "value"):
            v = e.value
            data = await v if hasattr(v, "__await__") else v

        if not isinstance(data, (bytes, bytearray)):
            ui.notify("Nie udało się odczytać pliku.", type="negative")
            return

        avatar_bytes["data"] = bytes(data)

        b64 = base64.b64encode(avatar_bytes["data"]).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        ui.run_javascript(
            f"""
            (function(){{
            const img = document.getElementById('avatar_crop_img');
            if (!img) {{ console.warn('no avatar_crop_img'); return; }}
            img.src = "{data_url}";
            }})();
            """,
            timeout=10,
        )

        ui.run_javascript(
            """
            (async function(){
            const sleep = (ms) => new Promise(r => setTimeout(r, ms));

            // 1) poczekaj aż dialog DOM się ustabilizuje
            await sleep(80);

            const img = document.getElementById('avatar_crop_img');
            const wrap = document.getElementById('avatar_crop_wrap');
            if (!img || !wrap) { console.warn('missing img/wrap'); return; }

            // 2) poczekaj aż obraz się załaduje
            await new Promise(resolve => {
                if (img.complete && img.naturalWidth > 0) return resolve();
                img.onload = () => resolve();
            });

            // 3) poczekaj aż kontener ma realny rozmiar
            let tries = 0;
            while (wrap.clientHeight < 50 && tries < 20) {
                await sleep(50);
                tries++;
            }

            try {
                if (window._avatarCropper) window._avatarCropper.destroy();
                window._avatarCropper = new Cropper(img, {
                aspectRatio: 1,
                viewMode: 1,
                dragMode: 'move',
                autoCropArea: 1,
                background: false,
                movable: true,
                zoomable: true,
                scalable: false,
                rotatable: false,
                responsive: true,
                preview: '#avatar_crop_preview',
                });
            } catch (e) {
                console.error('Cropper init failed', e);
            }
            })();
            """,
            timeout=10,
        )

        status.set_text("Ustaw kadr (przeciągnij / zoom) i kliknij „Zapisz”.")

    async def save_cropped_avatar():
        if not avatar_bytes["data"]:
            ui.notify("Najpierw wybierz zdjęcie.", type="negative")
            return

        result = await ui.run_javascript(
            """
            (function(){
            if (typeof Cropper === 'undefined') return {ok:false, err:'NO_LIB'};
            if (!window._avatarCropper) return {ok:false, err:'NO_INSTANCE'};
            const canvas = window._avatarCropper.getCroppedCanvas({
                width: 512, height: 512,
                imageSmoothingEnabled: true,
                imageSmoothingQuality: 'high',
            });
            if (!canvas) return {ok:false, err:'NO_CANVAS'};
            return {ok:true, data: canvas.toDataURL('image/png')};
            })();
            """,
            timeout=10,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            ui.notify(
                f"Crop error: {result.get('err') if isinstance(result, dict) else 'UNKNOWN'}",
                type="negative",
            )
            return

        data_url = result["data"]
        cropped_bytes = base64.b64decode(data_url.split(",", 1)[1])

        path = save_image(cropped_bytes, uid, "avatar")
        database_service.update_avatar(uid, path)

        fresh = database_service.get_user_by_id(uid)
        user_service.set_user(fresh)

        dlg.close()
        ui.navigate.to("/profile")

    with center_column():
        # --- AWATAR ---
        with card():
            ui.label("Awatar").classes("font-bold")

            with ui.row().classes("w-full items-center justify-between"):
                if u.get("avatar_path"):
                    ui.image(to_upload_url(u["avatar_path"])).classes(
                        "w-24 h-24 rounded-full"
                    )
                else:
                    with ui.element("div").classes("w-24 h-24 rounded-full").style(
                        "background: rgba(0,0,0,.04); display:flex; align-items:center; justify-content:center;"
                    ):
                        ui.icon("person").classes("text-3xl").style(f"color:{MUTED};")

                with ui.row().classes("items-center").style("gap:10px;"):
                    if u.get("avatar_path"):
                        ui.button(
                            "Edytuj", icon="edit", on_click=open_avatar_dialog
                        ).classes("apple-secondary").props("unelevated")
                        ui.button("Usuń", icon="delete", on_click=delete_avatar).props(
                            "flat"
                        ).classes("text-red-600")
                    else:
                        ui.button(
                            "Dodaj awatar",
                            icon="add_a_photo",
                            on_click=open_avatar_dialog,
                        ).classes("apple-primary").props("unelevated")

        # --- DIALOG ---
        with dlg:
            with ui.card().classes("w-full apple-card").style("max-width: 720px;"):
                ui.label("Ustaw awatar").classes("text-base font-bold")

                with ui.row().classes("w-full items-start justify-between").style(
                    "gap:14px;"
                ):
                    with ui.column().classes("w-full").style("gap: 10px;"):
                        ui.upload(
                            on_upload=on_avatar_upload,
                            auto_upload=True,
                            multiple=False,
                        ).props('accept=".jpg,.jpeg,.png"').classes(
                            "w-full avatar-upload"
                        )

                        status = ui.label("Wybierz zdjęcie, żeby przyciąć.").classes(
                            "text-sm"
                        )

                        crop_img = ui.html(
                            """
                        <div id="avatar_crop_wrap" style="width:100%; height:420px; background:rgba(0,0,0,.03); border-radius:16px; overflow:hidden;">
                        <img id="avatar_crop_img" style="max-width:100%; display:block;">
                        </div>
                        """,
                            sanitize=False,
                        ).classes("w-full")

                    with ui.column().classes("items-center").style(
                        "width: 120px; gap: 8px;"
                    ):
                        ui.label("Podgląd").classes("text-xs opacity-70")
                        ui.element("div").props("id=avatar_crop_preview")

                with ui.row().classes("w-full justify-end").style(
                    "gap: 10px; margin-top: 12px;"
                ):
                    ui.button("Anuluj", on_click=dlg.close).classes(
                        "apple-secondary"
                    ).props("flat")
                    ui.button(
                        "Zapisz", icon="check", on_click=save_cropped_avatar
                    ).classes("apple-primary").props("unelevated")

        # --- DANE ---
        with card():
            ui.label("Dane").classes("text-base font-bold")

            def row_item(
                label: str,
                value: str,
                *,
                icon: str | None = None,
                on_click=None,
                muted: bool = False,
            ):
                with ui.row().classes("w-full items-center justify-between").style(
                    "padding: 12px 6px; border-top: 1px solid rgba(140, 30, 75, 0.10);"
                ):
                    with ui.row().classes("items-center").style("gap:10px;"):
                        if icon:
                            ui.icon(icon).style(f"color:{PRIMARY}; opacity:.85;")
                        with ui.column().classes("gap-0"):
                            ui.label(label).classes(
                                "text-xs uppercase tracking-wide"
                            ).style(f"color:{MUTED}; letter-spacing:.06em;")
                            ui.label(value).classes("text-base").style(
                                "line-height:1.15;"
                                + ("; opacity:.75;" if muted else "")
                            )

                    if on_click:
                        ui.button(icon="chevron_right", on_click=on_click).props(
                            "flat round dense"
                        ).style(f"color:{MUTED};")

            # --- dane: edycja nicku ---
            nick_dlg = ui.dialog()
            nick_msg = ui.label().classes("text-sm")

            with nick_dlg:
                with ui.card().classes("w-full apple-card").style("max-width:520px;"):
                    ui.label("Zmień nick").classes("text-base font-bold")
                    nick_input = ui.input("Nick", value=u["nick"]).classes("w-full")

                    with ui.row().classes("w-full justify-end").style(
                        "gap:10px; margin-top:10px;"
                    ):
                        ui.button("Anuluj", on_click=nick_dlg.close).classes(
                            "apple-secondary"
                        ).props("flat")

                        def _save_nick():
                            ok, txt = database_service.update_nick(
                                uid, nick_input.value
                            )
                            nick_msg.set_text(txt)
                            nick_msg.style("color:#0b6b2d;" if ok else "color:#b00020;")
                            if ok:
                                fresh = database_service.get_user_by_id(uid)
                                user_service.set_user(fresh)
                                nick_dlg.close()
                                ui.navigate.to("/profile")

                        ui.button("Zapisz", icon="check", on_click=_save_nick).classes(
                            "apple-primary"
                        ).props("unelevated")
                    nick_msg

            def open_nick_dialog():
                nick_msg.set_text("")
                nick_input.value = u["nick"]
                nick_dlg.open()

            # --- dialog: zmiana hasła ---
            pwd_dlg = ui.dialog()
            pwd_msg = None

            with pwd_dlg:
                with ui.card().classes("w-full apple-card").style("max-width:520px;"):
                    ui.label("Zmień hasło").classes("text-base font-bold")

                    old_pwd = (
                        ui.input("Aktualne hasło")
                        .props("type=password")
                        .classes("w-full")
                    )
                    new_pwd = (
                        ui.input("Nowe hasło (min. 8 znaków)")
                        .props("type=password")
                        .classes("w-full")
                    )
                    new_pwd2 = (
                        ui.input("Powtórz nowe hasło")
                        .props("type=password")
                        .classes("w-full")
                    )

                    pwd_msg = (
                        ui.label("")
                        .classes("text-sm")
                        .style(f"color:{MUTED}; margin-top:6px;")
                    )

                    with ui.row().classes("w-full justify-end").style(
                        "gap:10px; margin-top:10px;"
                    ):
                        ui.button("Anuluj", on_click=pwd_dlg.close).classes(
                            "apple-secondary"
                        ).props("flat")

                        def _change_password():
                            pwd_msg.set_text("")
                            pwd_msg.style(f"color:{MUTED};")

                            if (new_pwd.value or "") != (new_pwd2.value or ""):
                                pwd_msg.set_text("Nowe hasła nie są takie same.")
                                pwd_msg.style("color:#b00020;")
                                return

                            if len(new_pwd.value or "") < 8:
                                pwd_msg.set_text(
                                    "Nowe hasło musi mieć minimum 8 znaków."
                                )
                                pwd_msg.style("color:#b00020;")
                                return

                            ok, txt = database_service.change_password(
                                user_id=uid,
                                old_password=old_pwd.value or "",
                                new_password=new_pwd.value or "",
                            )

                            pwd_msg.set_text(txt)
                            pwd_msg.style("color:#0b6b2d;" if ok else "color:#b00020;")

                            if ok:
                                pwd_dlg.close()
                                ui.notify("Hasło zostało zmienione.", type="positive")

                        ui.button(
                            "Zapisz", icon="check", on_click=_change_password
                        ).classes("apple-primary").props("unelevated")

                    pwd_msg

            def open_pwd_dialog():
                old_pwd.value = ""
                new_pwd.value = ""
                new_pwd2.value = ""
                pwd_dlg.open()

            # Pierwszy “row” bez border-top
            with ui.row().classes("w-full items-center justify-between").style(
                "padding: 12px 6px;"
            ):
                with ui.row().classes("items-center").style("gap:10px;"):
                    ui.icon("badge").style(f"color:{PRIMARY}; opacity:.85;")
                    with ui.column().classes("gap-0"):
                        ui.label("Nick").classes(
                            "text-xs uppercase tracking-wide"
                        ).style(f"color:{MUTED}; letter-spacing:.06em;")
                        ui.label(u["nick"]).classes("text-base")
                ui.button(icon="chevron_right", on_click=open_nick_dialog).props(
                    "flat round dense"
                ).style(f"color:{MUTED};")

            row_item("Email", u["email"], icon="mail", muted=True)  # readonly
            row_item("Hasło", "••••••••", icon="lock", on_click=open_pwd_dialog)


@ui.page("/report")
def page_report():
    if not user_service.require_login():
        return
    user_service.refresh_user_in_session()

    app_shell("Raport 30 dni")

    u = user_service.current_user()
    df = database_service.workouts_last_30_days_counts(int(u["id"]))

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
