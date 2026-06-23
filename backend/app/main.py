"""FastAPI application entrypoint for the management plane."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import init_db
from .routers import media, playback, settings, showings, tickets
from .services import scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start_scheduler()
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(title="Home Theater Manager", version="1.0.0", lifespan=lifespan)

app.include_router(media.router)
app.include_router(showings.router)
app.include_router(tickets.router)
app.include_router(playback.router)
app.include_router(settings.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
