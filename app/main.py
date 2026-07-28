import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI

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
    scheduler.add_job(
        logic.sync_leads,
        "interval",
        minutes=settings.leads_sync_interval_minutes,
        id="sync_leads",
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        logic.daily_append,
        CronTrigger(hour=0, minute=0, timezone=settings.timezone),
        id="daily_append",
    )
    scheduler.start()
    logger.info(
        "scheduler iniciado: poll de analytics a cada %s min, poll de total "
        "limpo a cada %s min, sync de leads a cada %s min, append diário 00:00 (%s)",
        settings.poll_interval_minutes,
        settings.total_limpo_poll_interval_minutes,
        settings.leads_sync_interval_minutes,
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
async def poll_total_limpo_now(background_tasks: BackgroundTasks):
    """Dispara o Total Limpo (API) em segundo plano e responde na hora — essa
    chamada pode levar minutos (export-leads é pesado sob volume alto), tempo
    maior que o timeout de clientes de cron externos (ex: cron-job.org limita
    em 30s no plano grátis). Responder logo evita reportar falha por timeout
    mesmo quando o trabalho real completa normalmente no servidor."""
    background_tasks.add_task(logic.poll_total_limpo)
    return {"status": "accepted"}


@app.post("/sync-leads-now")
async def sync_leads_now(background_tasks: BackgroundTasks):
    """Dispara a sincronização de leads (Supabase) em segundo plano — mesmo
    motivo do poll-total-limpo-now acima."""
    background_tasks.add_task(logic.sync_leads)
    return {"status": "accepted"}


@app.post("/daily-append-now")
async def daily_append_now():
    """Dispara manualmente a criação da linha do dia (normalmente só roda à meia-noite)."""
    await logic.daily_append()
    return {"status": "ok"}
