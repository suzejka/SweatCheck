from services.db_service import DatabaseService
from sqlalchemy import text

class UserService:
    # -------------------------
    # Session helpers
    # -------------------------
    def __init__(self, app, ui):
        pass
        self.app = app
        self.ui = ui
        self.database_service = DatabaseService()

    def current_user(self):
        return self.app.storage.user.get("user")


    def set_user(self, user: dict | None):
        self.app.storage.user["user"] = user

    def require_login(self) -> bool:
        if not self.current_user():
            self.ui.navigate.to("/login")
            return False
        return True
    

    def refresh_user_in_session(self):
        u = self.current_user()
        if not u:
            return
        fresh = self.database_service.get_user_by_id(u["id"])
        if fresh:
            self.set_user(fresh)

    def logout(self):
        self.app.storage.user.clear()  # czyści całą sesję użytkownika
        self.ui.navigate.to("/login")  # przekierowanie na login


