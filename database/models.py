from datetime import datetime
from typing import List, Optional

def account_model(
    user_id: int,
    phone: str,
    session_string: str,
    status: str = "active",
    added_at: Optional[datetime] = None,
    last_active: Optional[datetime] = None,
    joined_chats: Optional[List[int]] = None,
) -> dict:
    return {
        "user_id": user_id,
        "phone": phone,
        "session_string": session_string,
        "status": status,  # active / restricted / expired
        "added_at": added_at or datetime.utcnow(),
        "last_active": last_active or datetime.utcnow(),
        "joined_chats": joined_chats or [],
    }

def user_model(telegram_id: int, username: str = None, is_admin: bool = False) -> dict:
    return {
        "telegram_id": telegram_id,
        "username": username,
        "is_admin": is_admin,
        "created_at": datetime.utcnow(),
    }

def joined_chat_model(chat_id: int, chat_title: str, chat_type: str, joined_by: List[int]) -> dict:
    return {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "chat_type": chat_type,  # group, channel, supergroup
        "joined_by": joined_by,  # list of account user_ids (telegram IDs of accounts)
        "joined_at": datetime.utcnow(),
    }

def settings_model(key: str, value: dict) -> dict:
    return {
        "key": key,
        "value": value,
        "updated_at": datetime.utcnow(),
    }