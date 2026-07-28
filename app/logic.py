import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app import sendflow_client, sheets_client

logger = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def today_str() -> str:
    return datetime.now(_tz()).strftime("%d/%m/%Y")


def today_ddmmyyyy() -> str:
    return datetime.now(_tz()).strftime("%d%m%Y")


async def poll_analytics() -> None:
    # Autocorrige ENTRADAS/SAÍDAS da linha de hoje com o total oficial do
    # SendFlow (endpoint /releases/{id}/analytics), sobrescrevendo o contador
    # que o sendflow-leads-service incrementa em tempo real via webhook
    # member.added/removed — se aquele webhook cair sob volume alto (já
    # aconteceu 3x: 23/07, 27/07, 28/07), este serviço repõe o valor certo no
    # próximo ciclo, sem precisar de reconciliação manual.
    #
    # NÃO mexe no Supabase nem no LEADS NO DIA: leads individuais que o
    # webhook não capturou continuam faltando lá até uma reconciliação manual
    # (ver checklist no HANDOFF.md do sendflow-leads-service). Este serviço
    # só corrige os dois contadores de evento, não a lista de leads únicos.
    try:
        analytics = await sendflow_client.get_analytics()
    except Exception:
        logger.exception("falha ao consultar analytics do SendFlow")
        return

    add_dates = analytics.get("add", {}).get("dates", {})
    remove_dates = analytics.get("remove", {}).get("dates", {})
    hoje = today_ddmmyyyy()
    entradas = add_dates.get(hoje, 0)
    saidas = remove_dates.get(hoje, 0)

    try:
        sheets_client.upsert_row(
            "DATA", today_str(), {"ENTRADAS": entradas, "SAÍDAS": saidas}
        )
    except Exception:
        logger.exception("falha ao atualizar ENTRADAS/SAÍDAS na planilha")
        return

    logger.info("ENTRADAS/SAÍDAS de hoje corrigidas: %s/%s", entradas, saidas)


def _numero_do_lead(lead: dict) -> str:
    # Confirmado contra a API real: CSV com colunas Posição;Grupo;Nome;Número.
    raw = lead.get("Número") or lead.get("Numero") or lead.get("number") or ""
    raw = str(raw).lstrip("'").split("@")[0]
    return "".join(ch for ch in raw if ch.isdigit())


async def poll_total_limpo() -> None:
    # Calcula "Total Leads bruto - Admins - Duplicados" direto pela lista real
    # de participantes da API (POST /actions/export-leads), sem depender do
    # Supabase/webhook do sendflow-leads-service. Escreve só numa coluna nova
    # de comparação (settings.total_limpo_column) — não substitui o TOTAL
    # LIMPO (G3) que já existe, que continua vindo do Supabase.
    try:
        leads = await sendflow_client.export_leads()
    except Exception:
        logger.exception("falha ao consultar export-leads do SendFlow")
        return

    if leads and not _numero_do_lead(leads[0]):
        logger.warning(
            "não consegui achar o campo de número no export-leads, confira o "
            "formato real do payload: chaves=%s",
            list(leads[0].keys()),
        )

    numeros = set()
    for lead in leads:
        numero = _numero_do_lead(lead)
        if not numero or numero in settings.admin_numbers_set:
            continue
        numeros.add(numero)

    total_limpo = len(numeros)

    try:
        sheets_client.upsert_row(
            "DATA", today_str(), {settings.total_limpo_column: total_limpo}
        )
    except Exception:
        logger.exception("falha ao atualizar Total Limpo (API) na planilha")
        return

    logger.info(
        "Total Limpo (API) calculado: %s únicos (de %s participantes brutos, "
        "admins e duplicados já excluídos)",
        total_limpo,
        len(leads),
    )
