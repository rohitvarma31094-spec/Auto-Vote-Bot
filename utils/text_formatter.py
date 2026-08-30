from typing import Dict, List
from config import Config

def premium_text(text: str) -> str:
    """Wrap text in premium style (just return as is with markdown)."""
    return text

def format_account_list(accounts: List[dict], title: str = "📱 Accounts") -> str:
    if not accounts:
        return "❌ No accounts."
    lines = [f"{title}:"]
    for acc in accounts:
        status_icon = Config.PREMIUM_EMOJIS["green_tick"] if acc["status"] == "active" else Config.PREMIUM_EMOJIS["red_cross"]
        lines.append(f"{status_icon} `{acc['phone']}` - {acc['status']}")
    return "\n".join(lines)

def format_join_results(results: Dict[str, str]) -> str:
    lines = ["**Join Results:**"]
    for phone, status in results.items():
        lines.append(f"📱 `{phone}`: {status}")
    return "\n".join(lines)

def format_leave_results(results: Dict[tuple, str]) -> str:
    lines = ["**Leave Results:**"]
    for (phone, chat), status in results.items():
        lines.append(f"📱 `{phone}` | Chat {chat}: {status}")
    return "\n".join(lines)

def format_vote_results(results: Dict[str, str]) -> str:
    lines = ["**Vote Results:**"]
    for phone, status in results.items():
        lines.append(f"📱 `{phone}`: {status}")
    return "\n".join(lines)

def format_reaction_results(results: Dict[str, str]) -> str:
    lines = ["**Reaction Results:**"]
    for phone, status in results.items():
        lines.append(f"📱 `{phone}`: {status}")
    return "\n".join(lines)