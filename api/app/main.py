from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.v1 import admin_users, ask, auth, chat, conversations

app = FastAPI(title="AnswerWorks API")
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(chat.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send browsers that open the bare address to the interactive docs."""
    return RedirectResponse("/docs")
