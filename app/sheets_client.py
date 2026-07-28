import json

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.config import settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_creds = Credentials.from_service_account_info(
    json.loads(settings.google_service_account_json), scopes=_SCOPES
)
_service = build("sheets", "v4", credentials=_creds)
_sheet_id = settings.google_sheet_id
_sheet_name = settings.google_sheet_name


def _col_letter(n: int) -> str:
    letters = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _get_headers() -> list[str]:
    result = (
        _service.spreadsheets()
        .values()
        .get(spreadsheetId=_sheet_id, range=f"'{_sheet_name}'!1:1")
        .execute()
    )
    return result.get("values", [[]])[0]


def find_row_index(match_column: str, match_value: str) -> int | None:
    headers = _get_headers()
    if match_column not in headers:
        raise ValueError(f"Coluna '{match_column}' não existe na planilha")
    col_letter = _col_letter(headers.index(match_column) + 1)
    result = (
        _service.spreadsheets()
        .values()
        .get(spreadsheetId=_sheet_id, range=f"'{_sheet_name}'!{col_letter}2:{col_letter}")
        .execute()
    )
    values = result.get("values", [])
    for i, row in enumerate(values):
        if row and str(row[0]) == str(match_value):
            return i + 2  # +1 pelo header, +1 porque é 1-based
    return None


def update_row(row_index: int, values: dict) -> None:
    headers = _get_headers()
    data = []
    for key, val in values.items():
        if key not in headers:
            continue
        col_letter = _col_letter(headers.index(key) + 1)
        data.append({"range": f"'{_sheet_name}'!{col_letter}{row_index}", "values": [[val]]})
    if not data:
        return
    body = {"valueInputOption": "USER_ENTERED", "data": data}
    _service.spreadsheets().values().batchUpdate(spreadsheetId=_sheet_id, body=body).execute()


def upsert_row(match_column: str, match_value: str, values: dict) -> None:
    # Este serviço só corrige linhas que já existem (criadas pelo daily_append
    # do sendflow-leads-service) — não cria linha nova pra não brigar com o
    # cron diário do serviço principal.
    row_index = find_row_index(match_column, match_value)
    if row_index is None:
        raise ValueError(
            f"Linha com {match_column}={match_value} não encontrada — o daily_append "
            "do sendflow-leads-service ainda não criou a linha de hoje?"
        )
    update_row(row_index, values)
