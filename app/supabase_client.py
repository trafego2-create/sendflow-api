from supabase import create_client, Client

from app.config import settings

_client: Client = create_client(settings.supabase_url, settings.supabase_service_key)
_table = settings.supabase_table


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
