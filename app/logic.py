import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app import notifications, sendflow_client, sheets_client, supabase_client

logger = logging.getLogger(__name__)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def today_str() -> str:
    return datetime.now(_tz()).strftime("%d/%m/%Y")


def today_ddmmyyyy() -> str:
    return datetime.now(_tz()).strftime("%d%m%Y")


def today_iso() -> str:
    return datetime.now(_tz()).strftime("%Y-%m-%d")


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
    except Exception as e:
        logger.exception("falha ao consultar analytics do SendFlow")
        await notifications.notify_slack(f"⚠️ poll_analytics: falha ao consultar /analytics ({e})")
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

    try:
        supabase_client.upsert_contagem_diaria(today_iso(), entradas=entradas, saidas=saidas)
    except Exception:
        logger.exception("falha ao gravar entradas/saidas em whatsapp_sheets_diario")

    logger.info("ENTRADAS/SAÍDAS de hoje corrigidas: %s/%s", entradas, saidas)


def _numero_do_lead(lead: dict) -> str:
    # Confirmado contra a API real: CSV com colunas Posição;Grupo;Nome;Número.
    raw = lead.get("Número") or lead.get("Numero") or lead.get("number") or ""
    raw = str(raw).lstrip("'").split("@")[0]
    return "".join(ch for ch in raw if ch.isdigit())


async def poll_total_limpo() -> None:
    # Calcula "Total Leads bruto - Admins - Duplicados" direto pela lista real
    # de participantes da API (POST /actions/export-leads) e a contagem de
    # grupos cheios (GET /releases/{id}/groups), sem depender do webhook
    # campaign.metrics do sendflow-leads-service. Escreve nas mesmas células
    # que o serviço principal usa (TOTAL GRUPOS CHEIOS/TOTAL LEADS na linha
    # settings.summary_row, TOTAL LIMPO na linha settings.total_limpo_row —
    # nem toda aba usa a mesma linha, ver comentário em config.py), substituindo
    # qualquer fórmula antiga que estivesse lá por um valor fixo.
    try:
        leads = await sendflow_client.export_leads()
    except Exception as e:
        logger.exception("falha ao consultar export-leads do SendFlow")
        await notifications.notify_slack(
            f"⚠️ poll_total_limpo: falha ao consultar /actions/export-leads ({e})"
        )
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
        if not numero:
            continue
        if numero not in settings.admin_numbers_set:
            numeros.add(numero)

    # TOTAL LEADS (bruto) é a contagem de LINHAS do export-leads — uma por
    # participação em grupo, então quem está em vários grupos da campanha
    # conta mais de uma vez. De propósito (decisão de 03/09): "Total" é o
    # bruto de verdade, sem tirar nada; só "Total Limpo" faz a dedup +
    # exclusão de admin. Ver histórico: entre 27/08 (e5ce4bf) e hoje isso
    # contava número único (com admins ainda dentro), o que deixava Total e
    # Total Limpo quase iguais — revertido porque não representava mais o
    # bruto real da campanha.
    total_bruto = len(leads)
    total_limpo = len(numeros)

    # Alarme de regressão: numa campanha real, gente em 2+ grupos + admins
    # sempre deixa Total (bruto) bem maior que Total Limpo. Se ficarem quase
    # iguais (<2% de diferença), é sinal de que total_bruto voltou a contar
    # pessoa única em vez de linha — exatamente o bug de 27/08 a 03/09 (ver
    # e5ce4bf) que passou direto sem ninguém perceber por dias. Isso pega na
    # hora, mesmo que aconteça nesse app de novo no futuro por qualquer motivo.
    if total_bruto > 0 and total_limpo >= total_bruto * 0.98:
        logger.warning(
            "%s: TOTAL (%s) e TOTAL LIMPO (%s) quase iguais (diferença <2%%) — "
            "parece que total_bruto voltou a contar pessoa única em vez de linha "
            "do export-leads. Confira app/logic.py::poll_total_limpo().",
            settings.service_label, total_bruto, total_limpo,
        )
        await notifications.notify_slack(
            f"🚨 {settings.service_label}: TOTAL ({total_bruto}) e TOTAL LIMPO "
            f"({total_limpo}) quase iguais — total_bruto pode ter voltado a contar "
            "pessoa única em vez de linha do export-leads (mesmo bug de 27/08-03/09). "
            "Confere se esse app está com o deploy mais recente do poller."
        )

    # Proteção contra leitura parcial do export-leads (o CSV vem de um download
    # separado do Firebase Storage — se a conexão cair no meio por causa do
    # rate limit da SendAPI, csv.DictReader processa só o que chegou, sem
    # erro nenhum, e total_limpo/total_bruto ficam artificialmente baixos).
    # Uma queda >10% de um ciclo pro outro é implausível pra uma campanha só
    # crescendo — nesse caso não sobrescreve, mantém o valor antigo e tenta
    # de novo no próximo ciclo.
    try:
        atual_g3 = sheets_client.get_value(settings.total_limpo_row, "TOTAL LEADS")
    except Exception:
        atual_g3 = None
    leitura_suspeita = (
        isinstance(atual_g3, (int, float)) and atual_g3 > 0 and total_limpo < atual_g3 * 0.9
    )

    try:
        grupos = await sendflow_client.list_groups()
        grupos_cheios = sum(1 for g in grupos if g.get("full"))
    except Exception as e:
        logger.exception("falha ao consultar grupos do SendFlow")
        await notifications.notify_slack(f"⚠️ poll_total_limpo: falha ao consultar /groups ({e})")
        return

    if leitura_suspeita:
        logger.warning(
            "TOTAL LIMPO calculado (%s) caiu mais de 10%% em relação ao valor atual "
            "(%s) — parece leitura parcial do export-leads (rate limit/timeout). "
            "NÃO vou sobrescrever G2/G3 neste ciclo, tentando de novo no próximo.",
            total_limpo,
            atual_g3,
        )
        await notifications.notify_slack(
            f"⚠️ poll_total_limpo: TOTAL LIMPO caiu de {atual_g3} pra {total_limpo} "
            "(>10%) — parece leitura parcial da API, não sobrescrevi"
        )
        return

    try:
        sheets_client.update_row(
            settings.summary_row,
            {"TOTAL GRUPOS CHEIOS": grupos_cheios, "TOTAL LEADS": total_bruto},
        )
        sheets_client.update_row(settings.total_limpo_row, {"TOTAL LEADS": total_limpo})
    except Exception:
        logger.exception("falha ao atualizar grupos cheios/total bruto/total limpo na planilha")
        return

    try:
        supabase_client.upsert_contagem_resumo(
            total_grupos_cheios=grupos_cheios, total_leads=total_bruto, total_limpo=total_limpo
        )
    except Exception:
        logger.exception("falha ao gravar whatsapp_sheets_resumo")

    # LEADS NO DIA é a MÁXIMA vista no dia, não o valor mais recente — nunca
    # diminui, mesmo que o cálculo ao vivo caia (gente saindo dos grupos entre
    # um ciclo e outro). Congela sozinho quando o daily_append cria a linha de
    # amanhã, porque os próximos ciclos passam a mirar nessa linha nova.
    try:
        row_index = sheets_client.find_row_index("DATA", today_str())
        if row_index is not None:
            atual = sheets_client.get_value(row_index, "LEADS NO DIA") or 0
            novo_maximo = max(int(atual), total_limpo)
            sheets_client.update_row(row_index, {"LEADS NO DIA": novo_maximo})
            try:
                supabase_client.upsert_contagem_diaria(today_iso(), leads_no_dia=novo_maximo)
            except Exception:
                logger.exception("falha ao gravar leads_no_dia em whatsapp_sheets_diario")
    except Exception:
        logger.exception("falha ao atualizar LEADS NO DIA na planilha")
        return

    logger.info(
        "F2=%s grupos cheios | G2=%s total bruto | G3=%s total limpo | LEADS NO "
        "DIA=%s (%s participantes brutos, admins e duplicados já excluídos)",
        grupos_cheios,
        total_bruto,
        total_limpo,
        novo_maximo if row_index is not None else "?",
        len(leads),
    )


async def sync_leads() -> None:
    # Fonte de verdade PARALELA e independente do webhook do
    # sendflow-leads-service: a cada ciclo, baixa a lista real e completa de
    # quem está nos grupos agora (export_leads, direto da API oficial) e
    # sincroniza com a tabela própria no Supabase (settings.supabase_table).
    # Cada sync é uma FOTO do estado atual, não um replay de eventos — por
    # isso não perde gente mesmo que o serviço fique fora do ar por um tempo
    # entre um ciclo e outro, ao contrário do webhook que perde o evento pra
    # sempre se cair na hora. Quem some da lista (saiu de todos os grupos)
    # vira LEAD ÚNICO=0; quem aparece pela primeira vez é inserido.
    try:
        leads = await sendflow_client.export_leads()
    except Exception as e:
        logger.exception("falha ao consultar export-leads do SendFlow")
        await notifications.notify_slack(
            f"⚠️ sync_leads: falha ao consultar /actions/export-leads ({e})"
        )
        return

    grupo_por_numero: dict[int, str] = {}
    ativos: set[int] = set()
    for lead in leads:
        numero_str = _numero_do_lead(lead)
        if not numero_str or numero_str in settings.admin_numbers_set:
            continue
        numero = int(numero_str)
        ativos.add(numero)
        grupo_por_numero[numero] = lead.get("Grupo", "")

    try:
        existentes = supabase_client.fetch_all_numeros()
    except Exception:
        logger.exception("falha ao ler tabela do Supabase")
        return

    hoje = today_str()
    novos = [
        {
            "NÚMERO": numero,
            "GRUPO DA CAMPANHA": grupo_por_numero.get(numero, ""),
            "LEAD ÚNICO": 1,
            "DATA1": hoje,
        }
        for numero in ativos
        if numero not in existentes
    ]
    virar_1 = [
        existentes[numero]["ID"]
        for numero in ativos
        if numero in existentes and existentes[numero]["LEAD ÚNICO"] != 1
    ]
    virar_0 = [
        row["ID"]
        for numero, row in existentes.items()
        if numero not in ativos and row["LEAD ÚNICO"] == 1
    ]

    # Proteção contra leitura parcial do export-leads: se de repente uma fatia
    # grande demais de quem já era ativo "sumiu" nesta leitura, é mais
    # provável que a conexão do CSV tenha sido cortada no meio (rate limit da
    # SendAPI) do que todas essas pessoas terem saído de verdade em 30 min.
    # Nesse caso NÃO marca ninguém como saiu (evita corromper o Supabase) —
    # ainda assim insere novos e reativa quem voltou, porque isso é seguro
    # mesmo com leitura parcial (só significaria menos gente capturada, nunca
    # gente errada).
    previous_ativos = sum(1 for row in existentes.values() if row["LEAD ÚNICO"] == 1)
    queda_suspeita = previous_ativos > 0 and len(virar_0) > previous_ativos * 0.05

    try:
        supabase_client.insert_novos(novos)
        supabase_client.marcar_lead_unico(virar_1, 1)
        if queda_suspeita:
            logger.warning(
                "sync_leads: %s leads seriam marcados como saíram de uma vez (%.1f%% "
                "do total ativo de %s) — parece leitura parcial do export-leads "
                "(rate limit/timeout). NÃO vou marcar ninguém como saiu neste ciclo, "
                "tentando de novo no próximo.",
                len(virar_0),
                100 * len(virar_0) / previous_ativos,
                previous_ativos,
            )
            await notifications.notify_slack(
                f"⚠️ sync_leads: {len(virar_0)} leads seriam marcados como saíram de "
                f"uma vez ({100 * len(virar_0) / previous_ativos:.1f}% do total ativo) "
                "— parece leitura parcial da API, abortei essa etapa"
            )
        else:
            supabase_client.marcar_lead_unico(virar_0, 0)
    except Exception:
        logger.exception("falha ao gravar sync de leads no Supabase")
        return

    logger.info(
        "sync_leads: %s ativos agora | %s novos | %s voltaram a 1 | %s foram pra 0%s | "
        "total único agora=%s",
        len(ativos),
        len(novos),
        len(virar_1),
        0 if queda_suspeita else len(virar_0),
        " (abortado por leitura suspeita)" if queda_suspeita else "",
        supabase_client.count_unique_leads(),
    )


async def daily_append() -> None:
    # Cria a linha do dia na planilha (meia-noite, timezone configurado) —
    # próprio deste serviço, não depende mais do daily_append do
    # sendflow-leads-service pra existir. Isso "congela" o LEADS NO DIA de
    # ontem, porque os próximos poll_total_limpo passam a mirar na linha nova.
    hoje = today_str()
    try:
        sheets_client.append_row({"DATA2": hoje, "DATA": hoje}, "DATA2")
    except Exception:
        logger.exception("falha ao criar linha do dia na planilha")
        return

    logger.info("linha do dia criada: %s", hoje)
