from .mongo import MongoDB
from bson import ObjectId
from datetime import datetime
from typing import List, Optional, Dict, Any

# ---------- Accounts ----------
async def add_account(user_id: int, phone: str, session_string: str) -> dict:
    coll = MongoDB.db.accounts
    existing = await coll.find_one({"phone": phone})
    if existing:
        # Update session_string if changed
        await coll.update_one({"_id": existing["_id"]}, {"$set": {"session_string": session_string, "last_active": datetime.utcnow()}})
        return existing
    doc = {
        "user_id": user_id,
        "phone": phone,
        "session_string": session_string,
        "status": "active",
        "added_at": datetime.utcnow(),
        "last_active": datetime.utcnow(),
        "joined_chats": []
    }
    result = await coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc

async def get_accounts_by_user(user_id: int) -> List[dict]:
    cursor = MongoDB.db.accounts.find({"user_id": user_id})
    return await cursor.to_list(length=None)

async def get_all_accounts() -> List[dict]:
    cursor = MongoDB.db.accounts.find()
    return await cursor.to_list(length=None)

async def update_account_status(phone: str, status: str):
    await MongoDB.db.accounts.update_one({"phone": phone}, {"$set": {"status": status, "last_active": datetime.utcnow()}})

async def update_account_joined_chats(phone: str, chat_id: int):
    await MongoDB.db.accounts.update_one(
        {"phone": phone},
        {"$addToSet": {"joined_chats": chat_id}, "$set": {"last_active": datetime.utcnow()}}
    )

async def get_account_by_phone(phone: str) -> Optional[dict]:
    return await MongoDB.db.accounts.find_one({"phone": phone})

async def delete_account(phone: str):
    await MongoDB.db.accounts.delete_one({"phone": phone})

# ---------- Users ----------
async def add_user(telegram_id: int, username: str = None):
    coll = MongoDB.db.users
    existing = await coll.find_one({"telegram_id": telegram_id})
    if not existing:
        doc = {"telegram_id": telegram_id, "username": username, "is_admin": False, "created_at": datetime.utcnow()}
        await coll.insert_one(doc)

async def set_admin(telegram_id: int, is_admin: bool):
    await MongoDB.db.users.update_one({"telegram_id": telegram_id}, {"$set": {"is_admin": is_admin}}, upsert=True)

async def is_admin(telegram_id: int) -> bool:
    user = await MongoDB.db.users.find_one({"telegram_id": telegram_id})
    return user.get("is_admin", False) if user else False

async def get_all_admins() -> List[int]:
    cursor = MongoDB.db.users.find({"is_admin": True})
    admins = await cursor.to_list(length=None)
    return [u["telegram_id"] for u in admins]

# ---------- Joined Chats ----------
async def add_joined_chat(chat_id: int, chat_title: str, chat_type: str, joined_by: List[int]):
    coll = MongoDB.db.joined_chats
    existing = await coll.find_one({"chat_id": chat_id})
    if existing:
        # Merge joined_by
        await coll.update_one({"_id": existing["_id"]}, {"$addToSet": {"joined_by": {"$each": joined_by}}})
    else:
        doc = {"chat_id": chat_id, "chat_title": chat_title, "chat_type": chat_type, "joined_by": joined_by, "joined_at": datetime.utcnow()}
        await coll.insert_one(doc)

async def get_all_joined_chats() -> List[dict]:
    cursor = MongoDB.db.joined_chats.find()
    return await cursor.to_list(length=None)

async def delete_joined_chat(chat_id: int):
    await MongoDB.db.joined_chats.delete_one({"chat_id": chat_id})

# ---------- Settings ----------
async def get_setting(key: str) -> Optional[dict]:
    doc = await MongoDB.db.settings.find_one({"key": key})
    return doc["value"] if doc else None

async def set_setting(key: str, value: dict):
    await MongoDB.db.settings.update_one({"key": key}, {"$set": {"value": value, "updated_at": datetime.utcnow()}}, upsert=True)
