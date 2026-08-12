from fastapi import BackgroundTasks, FastAPI

from app import account_watch, logic

# Sem agendador interno de propósito: o EasyPanel não mantém esse processo
# rodando continuamente entre requisições (o agendador em background nunca
# disparava sozinho, só quando uma rota HTTP era chamada), e cada reinício do
# container reagendava um disparo imediato — isso, combinado com o cron
# externo, chegou a gerar chamadas de export-leads a cada ~2 min num fim de
# semana, sobrecarregando a fila de ações do SendFlow (link de convite parou
# de funcionar). Agora QUEM dispara cada ciclo é só o cron externo
# (cron-job.org) batendo nas rotas abaixo — nada roda sozinho dentro do
# processo.
app = FastAPI(title="SendFlow Analytics Poller")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/poll-now")
async def poll_now():
    """Dispara uma consulta manual de ENTRADAS/SAÍDAS. Chamado pelo cron
    externo (cron-job.org) a cada 15 min."""
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


@app.post("/check-account-bans-now")
async def check_account_bans_now():
    """Verifica se alguma conta WhatsApp foi suspensa desde a última checagem
    e avisa no Slack com o histórico de ações recentes. Só leitura (GET
    /accounts, GET /actions) — não toca nenhum número ao vivo, roda rápido,
    não precisa de BackgroundTasks."""
    await account_watch.check_account_bans()
    return {"status": "ok"}
