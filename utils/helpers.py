import re
from typing import List

def extract_chat_id(link: str) -> str:
    """Extract chat ID from username or invite link."""
    if link.startswith("https://t.me/"):
        parts = link.split("/")
        return parts[-1]
    if link.startswith("@"):
        return link[1:]
    return link