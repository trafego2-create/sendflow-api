from supabase import create_client, Client

from app.config import settings

_client: Client = create_client(settings.supabase_url, settings.supabase_service_key)
_table = settings.supabase_table

# Tabela fixa (não é por lançamento) — guarda o último estado conhecido de
# cada conta WhatsApp pra detectar transição não-suspensa -> suspensa.
_ban_watch_table = "account_ban_watch"


def fetch_all_numeros() -> dict[int, dict]:
    """Retorna {NÚMERO: {"ID":..., "LEAD ÚNICO":...}} pra toda a tabela.
    Buscado inteiro de uma vez (não linha a linha) porque a lista de
    participantes reais chega toda de uma vez também — mais rápido que
    consultar o Supabase uma vez por número."""
    page_size = 1000
    offset = 0
    result: dict[int, dict] = {}
    while True:
        resp = (
            _client.table(_table)
            .select('"ID","NÚMERO","LEAD ÚNICO"')
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            break
        for row in rows:
            result[row["NÚMERO"]] = row
        if len(rows) < page_size:
            break
        offset += page_size
    return result


def insert_novos(registros: list[dict]) -> None:
    if not registros:
        return
    batch_size = 500
    for i in range(0, len(registros), batch_size):
        _client.table(_table).insert(registros[i : i + batch_size]).execute()


def marcar_lead_unico(ids: list[int], valor: int) -> None:
    """Atualiza LEAD ÚNICO em lote pra um conjunto de IDs — todos recebem o
    mesmo valor (0 ou 1), então dá pra fazer 1 chamada em vez de uma por
    linha."""
    if not ids:
        return
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        batch = ids[i : i + batch_size]
        _client.table(_table).update({"LEAD ÚNICO": valor}).in_("ID", batch).execute()


def count_unique_leads() -> int:
    resp = (
        _client.table(_table)
        .select("NÚMERO", count="exact")
        .eq("LEAD ÚNICO", 1)
        .execute()
    )
    return resp.count or 0


def upsert_whatsapp_snapshot(**campos) -> None:
    """Grava só os campos passados (upsert parcial, merge-duplicates) na
    linha desse lançamento (chave = settings.supabase_table). Fonte de
    verdade pro Brabo Analytics ler os MESMOS números que vão pro Sheets,
    em vez de recalcular da tabela de leads acumulada (que cresce com o
    tempo por causa do LID do WhatsApp não ser estável entre syncs)."""
    _client.table("whatsapp_snapshot").upsert({"tabela": _table, **campos}).execute()


def fetch_account_ban_state() -> dict[str, dict]:
    """Retorna {account_id: {"suspended": bool, ...}} com o último estado
    salvo de cada conta. Tabela pequena (~40 linhas), busca tudo de uma vez."""
    resp = _client.table(_ban_watch_table).select("*").execute()
    return {row["account_id"]: row for row in (resp.data or [])}


def upsert_account_ban_state(
    account_id: str, name: str | None, jid: str | None, suspended: bool, reason: str | None
) -> None:
    _client.table(_ban_watch_table).upsert(
        {
            "account_id": account_id,
            "name": name,
            "jid": jid,
            "suspended": suspended,
            "reason": reason,
        }
    ).execute()
