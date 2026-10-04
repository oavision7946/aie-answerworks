from fastapi import FastAPI

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.v1 import ask

app = FastAPI(title="AnswerWorks API")
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(ask.router)
