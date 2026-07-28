from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SendFlow SendAPI
    sendflow_base_url: str = "https://sendapi.sendflow.pro"
    sendflow_api_token: str
    # Vazio até você rodar `python -m app.list_releases` e descobrir o ID certo.
    sendflow_release_id: str = ""

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

    # Nome da coluna onde este serviço escreve o Total Limpo calculado direto
    # pela API (lista real de participantes, deduplicada, sem admin) — coluna
    # nova, só pra comparação, não substitui o TOTAL LIMPO (G3) que já existe.
    # Precisa existir como header na planilha antes de ativar; o serviço não
    # cria coluna sozinho.
    total_limpo_column: str = "TOTAL LIMPO (API)"
    total_limpo_poll_interval_minutes: int = 30

    # Scheduler
    poll_interval_minutes: int = 15
    timezone: str = "America/Sao_Paulo"

    port: int = 8000


settings = Settings()
