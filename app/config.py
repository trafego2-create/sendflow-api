from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SendFlow SendAPI
    sendflow_base_url: str = "https://sendapi.sendflow.pro"
    sendflow_api_token: str
    # Vazio até você rodar `python -m app.list_releases` e descobrir o ID certo.
    sendflow_release_id: str = ""

    # Supabase — mesmo projeto do sendflow-leads-service, tabela PRÓPRIA e
    # nova (não mexe na tabela do serviço principal). Fonte de verdade
    # independente: a cada sync, baixa a lista real de participantes direto
    # da API (não depende de webhook) e grava aqui.
    supabase_url: str
    supabase_service_key: str
    supabase_table: str = "PI_AGO_26_API"
    leads_sync_interval_minutes: int = 30

    # Google Sheets (Service Account) — mesma planilha do sendflow-leads-service
    google_service_account_json: str
    google_sheet_id: str
    google_sheet_name: str = "LEAD TOTAL"

    # Números de telefone de admin/staff (mesma lista do sendflow-leads-service,
    # separados por vírgula) — excluídos do cálculo de Total Limpo (API).
    admin_numbers: str = ""

    @property
    def admin_numbers_set(self) -> set[str]:
        return {n.strip() for n in self.admin_numbers.split(",") if n.strip()}

    # A cada quantos minutos recalcular F2 (TOTAL GRUPOS CHEIOS), G2 (TOTAL
    # LEADS bruto) e G3 (TOTAL LIMPO) direto pela API.
    total_limpo_poll_interval_minutes: int = 30

    # Scheduler
    poll_interval_minutes: int = 15
    timezone: str = "America/Sao_Paulo"

    port: int = 8000


settings = Settings()
