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


def upsert_contagem_resumo(*, total_grupos_cheios: int, total_leads: int, total_limpo: int) -> None:
    """Grava Total Grupos Cheios/Total Leads/Total Limpo (os mesmos valores
    já escritos no Sheets neste ciclo) em whatsapp_sheets_resumo — tabela do
    banco do Brabo Analytics, alimentada direto por aqui (sem passar pelo
    Sheets). launch_code/bloco vêm de settings.supabase_table, sem precisar
    de config extra por app."""
    _client.table("whatsapp_sheets_resumo").upsert(
        {
            "launch_code": settings.launch_code,
            "bloco": settings.bloco,
            "total_grupos_cheios": total_grupos_cheios,
            "total_leads": total_leads,
            "total_limpo": total_limpo,
        },
        on_conflict="launch_code,bloco",
    ).execute()


def upsert_contagem_diaria(data_iso: str, **campos) -> None:
    """Grava só os campos passados (upsert parcial) na linha do dia `data_iso`
    (YYYY-MM-DD) em whatsapp_sheets_diario — campos possíveis: entradas,
    saidas, leads_no_dia. poll_analytics() e poll_total_limpo() escrevem
    campos diferentes da mesma linha em ciclos separados; upsert parcial
    garante que um não apaga o que o outro já gravou."""
    _client.table("whatsapp_sheets_diario").upsert(
        {"date": data_iso, "launch_code": settings.launch_code, "bloco": settings.bloco, **campos},
        on_conflict="date,launch_code,bloco",
    ).execute()


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
