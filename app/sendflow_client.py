import csv
import io

import httpx

from app.config import settings


def _headers() -> dict:
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.sendflow_api_token}",
    }


async def get_analytics(release_id: str | None = None) -> dict:
    """Métricas oficiais da campanha (ENTRADAS/SAÍDAS por dia), via SendAPI.
    Retorna algo como {"add": {"total": N, "dates": {"ddmmyyyy": count}},
    "remove": {...}, "clicks": ...}. Fonte de verdade oficial do SendFlow para
    ENTRADAS/SAÍDAS — não depende do webhook member.added/removed do serviço
    principal (sendflow-leads-service), que às vezes perde eventos
    silenciosamente sob volume alto."""
    rid = release_id or settings.sendflow_release_id
    url = f"{settings.sendflow_base_url}/releases/{rid}/analytics"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        # a API pode retornar uma lista com um único objeto
        if isinstance(data, list):
            data = data[0] if data else {}
        return data


async def export_leads(release_id: str | None = None) -> list[dict]:
    """Lista atual de participantes (leads) dos grupos da campanha.

    Confirmado contra a API real em 28/07/2026: POST /actions/export-leads NÃO
    devolve a lista direto — devolve {"success", "actionId", "url"}, onde "url"
    é um link do Firebase Storage pra um CSV (";"-delimitado, colunas
    "Posição;Grupo;Nome;Número", codificado com BOM utf-8) com um participante
    por linha. Baixa esse CSV e devolve a lista de dicts (um por linha)."""
    rid = release_id or settings.sendflow_release_id
    url = f"{settings.sendflow_base_url}/actions/export-leads"
    # Campanha grande (~55 mil participantes e crescendo) pode levar bem mais
    # que 120s pra gerar o CSV do lado do SendFlow — já vimos timeout com 120s.
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(url, headers=_headers(), json={"releaseId": rid})
        resp.raise_for_status()
        data = resp.json()
        csv_url = data.get("url")
        if not csv_url:
            return []
        csv_resp = await client.get(csv_url)
        csv_resp.raise_for_status()
        content = csv_resp.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        return list(reader)


async def list_groups(release_id: str | None = None) -> list[dict]:
    """Grupos da campanha, via GET /releases/{id}/groups. Cada item tem um
    campo "full" (bool) — usado pra contar TOTAL GRUPOS CHEIOS direto da API,
    sem depender do push campaign.metrics do webhook."""
    rid = release_id or settings.sendflow_release_id
    url = f"{settings.sendflow_base_url}/releases/{rid}/groups"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])


async def list_releases() -> list[dict]:
    """Lista todas as campanhas do usuário — usado só para descobrir o
    releaseId certo (ver app/list_releases.py)."""
    url = f"{settings.sendflow_base_url}/releases"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
