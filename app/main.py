import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app import logic
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.timezone)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        logic.poll_analytics,
        "interval",
        minutes=settings.poll_interval_minutes,
        id="poll_analytics",
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        logic.poll_total_limpo,
        "interval",
        minutes=settings.total_limpo_poll_interval_minutes,
        id="poll_total_limpo",
        next_run_time=datetime.now(),
    )
    scheduler.start()
    logger.info(
        "scheduler iniciado: poll de analytics a cada %s min, poll de total "
        "limpo a cada %s min (%s)",
        settings.poll_interval_minutes,
        settings.total_limpo_poll_interval_minutes,
        settings.timezone,
    )
    yield
    scheduler.shutdown()


app = FastAPI(title="SendFlow Analytics Poller", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/poll-now")
async def poll_now():
    """Dispara uma consulta manual imediata de ENTRADAS/SAÍDAS (fora do
    agendamento), útil pra testar antes de esperar o próximo ciclo."""
    await logic.poll_analytics()
    return {"status": "ok"}


@app.post("/poll-total-limpo-now")
async def poll_total_limpo_now():
    """Dispara uma consulta manual imediata do Total Limpo (API)."""
    await logic.poll_total_limpo()
    return {"status": "ok"}
