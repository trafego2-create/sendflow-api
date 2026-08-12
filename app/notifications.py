import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def notify_slack(message: str, webhook_url: str | None = None) -> None:
    """Manda uma mensagem pro Incoming Webhook do Slack. Usa
    SLACK_WEBHOOK_URL por padrão, ou uma URL específica via `webhook_url`
    (ex: canal dedicado de alertas de banimento). Não faz nada se a URL
    resolvida estiver vazia (feature opcional). Nunca deixa uma falha ao
    notificar quebrar o chamador — só loga."""
    url = webhook_url or settings.slack_webhook_url
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={"text": f"[{settings.service_label}] {message}"},
            )
            resp.raise_for_status()
    except Exception:
        logger.exception("falha ao notificar Slack")
