import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def notify_slack(message: str) -> None:
    """Manda uma mensagem pro Incoming Webhook do Slack configurado. Não faz
    nada se SLACK_WEBHOOK_URL estiver vazio (feature opcional). Nunca deixa
    uma falha ao notificar quebrar o chamador — só loga."""
    if not settings.slack_webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                settings.slack_webhook_url,
                json={"text": f"[{settings.service_label}] {message}"},
            )
            resp.raise_for_status()
    except Exception:
        logger.exception("falha ao notificar Slack")
