import asyncio
import logging

from app import notifications, sendflow_client, supabase_client

logger = logging.getLogger(__name__)

# GET /actions pede 10s entre listagens — se mais de uma conta for suspensa
# na mesma checagem, esperar esse tanto antes de cada chamada extra evita
# tomar 403 e perder o histórico das suspensões seguintes.
_INTERVALO_ENTRE_LISTAGENS_SEGUNDOS = 11


async def check_account_bans() -> None:
    # Só leitura (GET /accounts, GET /actions) — não toca nenhum número ao
    # vivo no WhatsApp, então pode rodar com frequência alta sem risco.
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

            try:
                if not primeira_listagem:
                    await asyncio.sleep(_INTERVALO_ENTRE_LISTAGENS_SEGUNDOS)
                primeira_listagem = False
                acoes = await sendflow_client.list_actions(account_id, limit=10)
                if acoes:
                    linhas = "\n".join(
                        f"  • {a.get('createdAt')} — {a.get('type')} (sucesso={a.get('success')})"
                        for a in acoes
                    )
                else:
                    linhas = "  (nenhuma ação recente encontrada)"
            except Exception:
                logger.exception("falha ao buscar histórico de ações da conta suspensa")
                linhas = "  (falha ao buscar histórico de ações)"

            await notifications.notify_slack(
                f"🚨 *Conta suspensa no WhatsApp*: {nome} ({jid})\n"
                f"Motivo: {motivo}\n"
                f"Últimas ações antes da suspensão:\n{linhas}"
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
