# SendFlow Analytics Poller

Serviço Python (FastAPI) **separado e paralelo** ao `sendflow-leads-service`. Não recebe
webhook e não mexe no Supabase. Faz duas coisas, cada uma com seu próprio ciclo:

1. **ENTRADAS/SAÍDAS do dia** (`poll_analytics`, a cada `POLL_INTERVAL_MINUTES`) — consulta
   `GET /releases/{id}/analytics` e corrige essas duas colunas na linha de **hoje** com o
   total oficial do SendFlow.
2. **Total Limpo (API)** (`poll_total_limpo`, a cada `TOTAL_LIMPO_POLL_INTERVAL_MINUTES`) —
   consulta `POST /actions/export-leads` (lista real de participantes), deduplica por
   número e exclui `ADMIN_NUMBERS`, e escreve o resultado numa coluna nova
   (`TOTAL_LIMPO_COLUMN`) na linha de hoje, só pra comparação — **não substitui** o `TOTAL
   LIMPO` (G3) que já existe na planilha.

## Por que esse serviço existe

O `sendflow-leads-service` incrementa `ENTRADAS`/`SAÍDAS` em tempo real a cada evento de
webhook (`group.updated.members.added`/`removed`), e o `TOTAL LIMPO` (G3) é uma fórmula que
lê `count_unique_leads()` do Supabase — que só é alimentado por esse mesmo webhook. Sob
volume alto, esse webhook já parou de entregar `member.added` silenciosamente por horas
seguidas (23/07, 27/07, 28/07/2026) — sem erro visível em lugar nenhum, só reconciliação
manual detectou. Os dois pontos acima buscam os mesmos números direto na SendAPI (fonte
oficial, independente do webhook), como forma de detectar/corrigir esse gap sem depender de
reconciliação manual.

Essa mesma ideia (poll de `/analytics`) já existiu no `sendflow-leads-service` (função
`poll_analytics`, commit `c43dcee`), mas foi removida em 16/07 porque o endpoint dava 403
com o token disponível na época. Isso mudou: agora existe uma SendAPI documentada
oficialmente (`https://sendapi.sendflow.pro`, OAS 3.0) com API Key própria.

## O que ele NÃO resolve

O Supabase em si (a tabela de leads individuais que o `sendflow-leads-service` mantém) nunca
é escrito por este serviço. Se o webhook `member.added` perder um evento, aquele lead
continua faltando lá até uma reconciliação manual de verdade (checklist no `HANDOFF.md` do
`sendflow-leads-service`, com INSERT/UPDATE no banco). O `Total Limpo (API)` deste serviço
serve pra **detectar** que há divergência (comparando as duas colunas), não pra corrigir o
Supabase sozinho — corrigir o banco automaticamente é mais arriscado (risco de duplicata,
já aconteceu um bug de tipo `str`/`int` que gerou 8.349 linhas duplicadas) e não está nesse
serviço de propósito.

## Testado de verdade em 28/07/2026

Rodado contra a API e a planilha real (numa cópia de teste, ver abaixo):

- `GET /releases/{id}/analytics` retorna exatamente o formato assumido
  (`{"add": {"total", "dates": {"ddmmyyyy": n}}, "remove": {...}, "clicks": {...}}`).
- `POST /actions/export-leads` **não** devolve a lista direto — devolve
  `{"success", "actionId", "url"}`, onde `url` é um link do Firebase Storage pra um CSV
  (`;`-delimitado, colunas `Posição;Grupo;Nome;Número`, ~53 mil linhas pro PI-AGO-26 hoje).
  `export_leads()` já baixa e parseia esse CSV.
- `poll_analytics()` e `poll_total_limpo()` escreveram corretamente na planilha de teste:
  `ENTRADAS`/`SAÍDAS` corrigidos, `TOTAL LIMPO (API)` calculado em 46.534 (contra
  `LEADS NO DIA` do Supabase em 42.563 — divergência real detectada, provavelmente gap de
  webhook desde a última reconciliação manual).

## Ambiente de teste atual

O `.env` local está apontando pra uma **cópia de teste** da planilha "Captação [PI-AGO-26]"
(`GOOGLE_SHEET_ID=1IlHs3Z88h6k33ZT2kIRILswGK_g6JyQJh7lOgmI7ezE`), não a de produção — feita
via "Arquivo → Fazer uma cópia" manualmente (a service account não tem cota de Drive própria
pra criar arquivo sozinha, tentei via API e deu `storageQuotaExceeded`) e compartilhada com
`sendflow-leads-bot@n8n-trigrrer.iam.gserviceaccount.com` como Editor. A coluna
`TOTAL LIMPO (API)` já foi criada nela. Antes de apontar pra planilha real de produção,
trocar `GOOGLE_SHEET_ID` no `.env`.

## Setup

1. Pegar o **API Key** da SendAPI: painel SendFlow → aba "API Keys" → copiar o token Bearer.
2. Copiar `.env.example` pra `.env` e preencher `SENDFLOW_API_TOKEN`.
3. Descobrir o `SENDFLOW_RELEASE_ID` da campanha (ex: PI-AGO-26):
   ```
   pip install -r requirements.txt
   python -m app.list_releases
   ```
   Copia o `id` da campanha certa pro `.env`.
4. Preencher `GOOGLE_SERVICE_ACCOUNT_JSON`/`GOOGLE_SHEET_ID`/`GOOGLE_SHEET_NAME` — mesma
   planilha e mesma service account que o `sendflow-leads-service` já usa (valores estão no
   `.env` daquele projeto).
5. Preencher `ADMIN_NUMBERS` — mesma lista do `sendflow-leads-service`.
6. **Adicionar a coluna `TOTAL LIMPO (API)` na planilha** (aba `LEAD TOTAL`) antes de
   ativar — o serviço não cria coluna sozinho, só escreve numa que já existe (silenciosamente
   não escreve nada se o header não existir).
7. Rodar local: `uvicorn app.main:app --reload`
8. Testar sem esperar o ciclo: `POST /poll-now` (ENTRADAS/SAÍDAS) e
   `POST /poll-total-limpo-now` (Total Limpo API) — no segundo, olhe o log pra confirmar que
   o número de participantes bateu com o esperado antes de confiar no valor.

## Deploy (EasyPanel)

Mesmo padrão do `sendflow-leads-service`: novo app no EasyPanel, Source = este repo/pasta,
Build = Dockerfile, mapear a porta 8000, colar as env vars do `.env`. Roda em paralelo ao
app `contagem-leads` — nenhum dos dois precisa ser desligado pro outro funcionar.

## Repetir para outro lançamento (ex: PBB_AGO_26)

Mesmo código, outro app no EasyPanel, trocando `SENDFLOW_RELEASE_ID` e `GOOGLE_SHEET_ID`
pelos da campanha correspondente.
