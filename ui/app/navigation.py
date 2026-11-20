"""Which pages exist and who may see them. The API still enforces every permission."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    path: str  # relative to app/main.py
    title: str
    icon: str
    roles: frozenset[str] | None = None  # None: every signed-in user
    default: bool = False


ADMINS = frozenset({"admin"})
MONITORS = frozenset({"admin", "monitor"})


PAGES = (
    PageSpec("views/chat.py", "Chat", ":material/chat:", default=True),
    PageSpec("views/conversations.py", "Conversations", ":material/history:"),
    PageSpec("views/documents.py", "Documents", ":material/description:"),
    PageSpec("views/ask.py", "Ask", ":material/quiz:"),
    PageSpec("views/admin_users.py", "Admin · Users", ":material/group:", roles=ADMINS),
    PageSpec("views/admin_corpora.py", "Admin · Corpora", ":material/folder_shared:", roles=ADMINS),
    PageSpec("views/admin_system.py", "Admin · System", ":material/monitor_heart:", roles=ADMINS),
    PageSpec("views/monitoring.py", "Monitoring", ":material/monitoring:", roles=MONITORS),
)


def visible_pages(role: str) -> list[PageSpec]:
    return [page for page in PAGES if page.roles is None or role in page.roles]
