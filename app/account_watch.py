import asyncio
import logging

from app.config import settings
from app import notifications, sendflow_client, supabase_client

logger = logging.getLogger(__name__)

# Nomes técnicos que a SendFlow usa internamente pro campo "type" de cada
# ação -> texto em português, pra quem ler o alerta no Slack sem entender
# nada de API conseguir entender o que aconteceu.
_TIPOS_ACAO_PT = {
    "sendMessages": "Disparo de mensagens",
    "sendMessage": "Envio de mensagem",
    "payloadSharing": "Compartilhamento de conteúdo (parte do disparo)",
    "makeGroupAdmin": "Tornar admin de grupo",
    "groupMakeAdmin": "Tornar admin de grupo",
    "demoteGroupAdmin": "Rebaixar admin de grupo",
    "releaseGroupCreate": "Criação de grupo",
    "groupCreate": "Criação de grupo",
    "releaseGroupImport": "Importação de grupos",
    "groupSettingChange": "Alteração de configuração do grupo",
    "updateGroupSetting": "Alteração de configuração do grupo",
    "update-group-image": "Atualização de foto do grupo",
    "updateGroupPicture": "Atualização de foto do grupo",
    "updateGroupDescription": "Atualização de descrição do grupo",
    "updateGroupSubject": "Atualização de nome do grupo",
    "updateGroupInviteCode": "Atualização de link de convite",
    "revokeGroupInviteCode": "Revogação de link de convite",
    "closeGroup": "Encerramento de grupo",
    "openGroup": "Reabertura de grupo",
    "deactivateCommunity": "Desativação de comunidade",
    "moveGroups": "Movimentação de grupos entre campanhas",
    "removeFromRelease": "Remoção de participantes",
    "joinGroup": "Entrada em grupo via link de convite",
    "releaseExportLeads": "Exportação de participantes",
}


def _traduzir_tipo_acao(tipo: str | None) -> str:
    if not tipo:
        return "Ação desconhecida"
    return _TIPOS_ACAO_PT.get(tipo, tipo)


# GET /actions e GET /releases têm rate limit próprio — se mais de uma conta
# for suspensa na mesma checagem, esperar esse tanto antes de cada chamada
# extra evita tomar 403 e perder o histórico das suspensões seguintes.
_INTERVALO_ENTRE_LISTAGENS_SEGUNDOS = 11


async def _mapa_campanhas() -> dict[str, str]:
    """releaseId -> nome da campanha, pra identificar de qual campanha veio
    o banimento. Busca uma vez só por checagem (GET /releases pede 5min entre
    chamadas, então só vale a pena chamar quando realmente precisa)."""
    try:
        releases = await sendflow_client.list_releases()
        return {r["id"]: r.get("name", r["id"]) for r in releases}
    except Exception:
        logger.exception("falha ao buscar /releases pra identificar campanha do banimento")
        return {}


async def check_account_bans() -> None:
    # Só leitura (GET /accounts, GET /actions, GET /releases) — não toca
    # nenhum número ao vivo no WhatsApp, então pode rodar com frequência alta
    # sem risco.
    try:
        contas = await sendflow_client.list_accounts()
    except Exception as e:
        logger.exception("falha ao consultar /accounts")
        await notifications.notify_slack(f"⚠️ check_account_bans: falha ao consultar /accounts ({e})")
        return

    try:
        estado_anterior = supabase_client.fetch_account_ban_state()
    except Exception:
        logger.exception("falha ao ler estado anterior de contas no Supabase")
        return

    novas_suspensoes = 0
    primeira_listagem = True
    mapa_campanhas: dict[str, str] | None = None  # lazy, só busca se precisar
    for conta in contas:
        account_id = conta.get("id")
        if not account_id:
            continue
        suspensao = conta.get("whatsappSuspension") or {}
        suspenso_agora = bool(suspensao.get("suspended"))
        suspenso_antes = bool((estado_anterior.get(account_id) or {}).get("suspended"))

        if suspenso_agora and not suspenso_antes:
            novas_suspensoes += 1
            nome = conta.get("name", "?")
            jid = conta.get("jidPrefix") or conta.get("jid", "?")
            motivo = suspensao.get("reason") or "desconhecido"
            logger.warning("NOVA SUSPENSÃO: %s (%s) motivo=%s", nome, jid, motivo)

            if mapa_campanhas is None:
                mapa_campanhas = await _mapa_campanhas()
                await asyncio.sleep(_INTERVALO_ENTRE_LISTAGENS_SEGUNDOS)

            try:
                if not primeira_listagem:
                    await asyncio.sleep(_INTERVALO_ENTRE_LISTAGENS_SEGUNDOS)
                primeira_listagem = False
                acoes = await sendflow_client.list_actions(account_id, limit=10)
                if acoes:
                    campanhas_envolvidas = {
                        mapa_campanhas.get(a["releaseId"], a["releaseId"])
                        for a in acoes
                        if a.get("releaseId")
                    }
                    campanhas_txt = ", ".join(sorted(campanhas_envolvidas)) or "não identificada"
                    linhas = "\n".join(
                        f"  • {a.get('createdAt')} — {_traduzir_tipo_acao(a.get('type'))} "
                        f"({'✅ sucesso' if a.get('success') else '❌ falhou'})"
                        for a in acoes
                    )
                else:
                    campanhas_txt = "não identificada (sem ações recentes)"
                    linhas = "  (nenhuma ação recente encontrada)"
            except Exception:
                logger.exception("falha ao buscar histórico de ações da conta suspensa")
                campanhas_txt = "não identificada (falha ao buscar histórico)"
                linhas = "  (falha ao buscar histórico de ações)"

            await notifications.notify_slack(
                f"🚨 *Conta suspensa no WhatsApp*: {nome} ({jid})\n"
                f"Campanha(s): {campanhas_txt}\n"
                f"Motivo: {motivo}\n"
                f"Últimas ações antes da suspensão:\n{linhas}",
                webhook_url=settings.slack_webhook_url_bans,
            )

        try:
            supabase_client.upsert_account_ban_state(
                account_id=account_id,
                name=conta.get("name"),
                jid=conta.get("jidPrefix") or conta.get("jid"),
                suspended=suspenso_agora,
                reason=suspensao.get("reason"),
            )
        except Exception:
            logger.exception("falha ao salvar estado da conta %s no Supabase", account_id)

    logger.info(
        "check_account_bans: %s contas verificadas, %s suspensão(ões) nova(s)",
        len(contas),
        novas_suspensoes,
    )
