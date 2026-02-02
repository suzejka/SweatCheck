from services.db_service import DatabaseService


class NotificationService:
    def __init__(self):
        self.database_service = DatabaseService()

    def parse_notifications(self, user_id: int):
        notifications = self.database_service.list_notifications(user_id)
        parsed = []
        for n in notifications:
            p = dict(n)  # kopiuj
            p_payload = p.get("payload") or {}
            if p["type"] == "friend_request":
                from_user_id = p_payload.get("from_user_id")
                from_user = (
                    self.database_service.get_user_by_id(from_user_id)
                    if from_user_id
                    else None
                )
                p["message"] = (
                    f"Nowe zaproszenie od **{from_user['nick']}**"
                    if from_user
                    else "Nowe zaproszenie"
                )
                p["user_friendly_type"] = "Zaproszenie do znajomych"
                p["user_friendly_created_at"] = (
                    p["created_at"].strftime("%Y-%m-%d %H:%M")
                    if p["created_at"]
                    else ""
                )
            elif p["type"] == "friend_accept":
                by_user_id = p_payload.get("by_user_id")
                by_user = (
                    self.database_service.get_user_by_id(by_user_id)
                    if by_user_id
                    else None
                )
                p["message"] = (
                    f"**{by_user['nick']}** zaakceptował(a) Twoje zaproszenie"
                    if by_user
                    else "Ktoś zaakceptował(a) Twoje zaproszenie"
                )
                p["user_friendly_type"] = "Zaakceptowano zaproszenie"
                p["user_friendly_created_at"] = (
                    p["created_at"].strftime("%Y-%m-%d %H:%M")
                    if p["created_at"]
                    else ""
                )
            elif p["type"] == "friend_decline":
                by_user_id = p_payload.get("by_user_id")
                by_user = (
                    self.database_service.get_user_by_id(by_user_id)
                    if by_user_id
                    else None
                )
                p["message"] = (
                    f"**{by_user['nick']}** odrzucił(a) Twoje zaproszenie"
                    if by_user
                    else "Ktoś odrzucił(a) Twoje zaproszenie"
                )
                p["user_friendly_type"] = "Odrzucono zaproszenie"
                p["user_friendly_created_at"] = (
                    p["created_at"].strftime("%Y-%m-%d %H:%M")
                    if p["created_at"]
                    else ""
                )
            elif p["type"] == "admin_broadcast":
                p["message"] = p_payload.get("message")
                p["user_friendly_type"] = "Ogłoszenie od adminki"
                p["user_friendly_created_at"] = (
                    p["created_at"].strftime("%Y-%m-%d %H:%M")
                    if p["created_at"]
                    else ""
                )
            else:
                p["message"] = "Nieznany typ powiadomienia"
            parsed.append(p)
        return parsed
