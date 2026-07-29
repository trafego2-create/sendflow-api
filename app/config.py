from pydantic_settings import BaseSettings, SettingsConfigDict

# Todos os números de admin/staff da empresa (não só de um lançamento) —
# sempre excluídos do cálculo de leads, em todo lançamento, independente do
# que vier em ADMIN_NUMBERS. Atualizar aqui direto se alguém sair/entrar da
# equipe, em vez de repetir a lista em cada app/lançamento novo.
ADMIN_NUMBERS_BASE = {
    "5516991876538",
    "5516991320600",
    "5516992314699",
    "5516991525260",
    "5516997353630",
    "5516993910017",
    "5516992352349",
    "5516991081133",
    "5516992345997",
    "5516993966587",
    "5516996544873",
    "5516997384603",
    "5516992359626",
    "5516994054610",
    "5516992712899",
    "5516993678375",
    "5516991268108",
    "5516992342427",
    "5516991880994",
    "5516992162853",
    "5516993230455",
    "5516992580599",
    "5516994109165",
    "5516991262116",
    "5516992243112",
    "5516994330869",
    "5516992932850",
    "5516993643159",
    "5516994602791",
    "5516991628640",
}


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

    # Números de admin/staff EXTRAS além da lista base (ADMIN_NUMBERS_BASE
    # acima), caso um lançamento específico precise excluir algum número que
    # não é staff da empresa toda. Opcional — pode deixar vazio.
    admin_numbers: str = ""

    @property
    def admin_numbers_set(self) -> set[str]:
        extras = {n.strip() for n in self.admin_numbers.split(",") if n.strip()}
        return ADMIN_NUMBERS_BASE | extras

    # A cada quantos minutos recalcular TOTAL GRUPOS CHEIOS/TOTAL LEADS/TOTAL
    # LIMPO direto pela API.
    total_limpo_poll_interval_minutes: int = 30

    # Linha onde ficam TOTAL GRUPOS CHEIOS/TOTAL LEADS (padrão: linha 2) e linha
    # onde fica TOTAL LIMPO (padrão: linha 3) — nem toda aba segue esse layout
    # exato (ex: "LEAD TOTAL VIPS" do PI-AGO-26 tem TOTAL LIMPO na linha 4, é um
    # layout mais antigo que nunca foi atualizado). Configurável por lançamento
    # em vez de fixo no código.
    summary_row: int = 2
    total_limpo_row: int = 3

    # Scheduler
    poll_interval_minutes: int = 15
    timezone: str = "America/Sao_Paulo"

    port: int = 8000


settings = Settings()
