"""Which pages exist and who may see them. The API still enforces every permission."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    path: str  # relative to app/main.py
    title: str
    icon: str
    admin_only: bool = False
    default: bool = False


PAGES = (
    PageSpec("views/chat.py", "Chat", ":material/chat:", default=True),
    PageSpec("views/conversations.py", "Conversations", ":material/history:"),
    PageSpec("views/documents.py", "Documents", ":material/description:"),
    PageSpec("views/ask.py", "Ask", ":material/quiz:"),
    PageSpec("views/admin_users.py", "Admin · Users", ":material/group:", admin_only=True),
    PageSpec(
        "views/admin_corpora.py", "Admin · Corpora", ":material/folder_shared:", admin_only=True
    ),
    PageSpec(
        "views/admin_system.py", "Admin · System", ":material/monitor_heart:", admin_only=True
    ),
)


def visible_pages(is_admin: bool) -> list[PageSpec]:
    return [page for page in PAGES if is_admin or not page.admin_only]
