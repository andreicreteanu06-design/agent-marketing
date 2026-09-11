# Agent PPC

Unealta Python, controlata prin configuratie, care ajuta marketerii sa planifice
si sa gestioneze campanii **Google Ads**, **Meta Ads** si **TikTok Ads**,
folosind modele matematice pentru alocarea bugetului si atribuire, in spatele
unor **guardrails stricte cu om in bucla (HITL)**. Doua moduri de rulare:
**CLI local** (`ppc_agent`, un singur marketer/agentie) si **server B2B
multi-tenant** (`ppc_agent_server/`, mai multe agentii — [detalii mai jos](#server-backend-multi-tenant)),
al doilea fiind un wrapper subtire peste exact aceleasi pipeline-uri pure.

> **Versiunea 1 nu face niciun apel real** catre platformele de reclame. Fiecare
> integrare externa sta in spatele unui adaptor cu implementare `mock`, deci
> intreaga logica este testabila acum. Clientii `live` se adauga intr-o faza
> ulterioara — singura exceptie e clientul LLM de copywriting, care poate
> rula deja `live` impotriva unui [Ollama](https://ollama.com) local (loopback,
> gratuit — [detalii mai jos](#client-llm-live-ollama-local)).

## Stare

| Faza | Continut | Stare |
|------|----------|-------|
| 0 | Schela proiectului, configurare, CLI, adaptoare | ✅ |
| 1 | Modulul 1 — context si ingestie (crawler, GSC, GBP, keyword planner, negative) | ✅ |
| 2 | Modulul 2 — alocare buget (Thompson Sampling) + atribuire Markov | ✅ |
| 3 | Modulul 3 — optimizare Quality Score + lichiditate Meta | ✅ |
| 4 | Modulul 4 — poarta de aprobare + limitator absolut de cheltuiala | ✅ |
| + | Modul copywriter — copy direct-response emotional (RAG local pe swipe file) | ✅ |
| + | Kelly Criterion — dimensionarea plafonului zilnic absolut in functie de ROAS | ✅ |
| 5 | Modul creative — voce (Fish Speech) + video (Flick) -> `.mp4`, mock-first | ✅ |
| + | Client LLM live — Ollama local (gratuit, loopback, `copy` + `build-creative`) | ✅ |
| A | RAG creativ TikTok — script UGC 9:16, RAG pe nisa/keyword + ingestie CSV/JSON | ✅ |
| B | Provider TikTok Ads — performanta + parcursuri de conversie, mock-first | ✅ |
| C | TikTok ca brate Thompson + touchpoint-uri Markov (combinat cu Google Ads) | ✅ |
| D | `ppc_agent_server/` — schela FastAPI + SQLModel + Alembic, multi-tenant | ✅ |
| E | Rute REST (clienti, joburi, propuneri) + poarta HITL DB-backed | ✅ |
| F | Coada de joburi ARQ+Redis (opt-in) — `InlineJobQueue` ramane implicita | ✅ |
| + | RAG omnicanal (Google/Meta/TikTok) — swipe unificat, proxy de performanta, ingestie CSV universala | ✅ |
| — | Integrare `live` (Google Ads / GSC / GBP / Meta / TikTok Ads / Fish Speech / Flick / OAuth) | ⏳ |

## Cerinte

- Python 3.11+ (testat pe 3.13)
- Windows / macOS / Linux

## Instalare

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Pe macOS / Linux, calea este `.venv/bin/python`.

## Configurare

1. Copiaza `.env.example` in `.env` si completeaza cheile (doar pentru modul `live`).
   `.env` este in `.gitignore` — nu il comite.
2. Copiaza `config.example.yaml` in `config.yaml` si ajusteaza domeniul, piata,
   limitele de buget si brandurile concurente.

### `PPC_PROVIDER_MODE`

| Valoare | Efect |
|---------|-------|
| `mock` (implicit) | Foloseste date de test deterministice. Niciun apel de retea. |
| `live` | Clientul LLM (Ollama, vezi mai jos) e functional. Google Ads / GSC / GBP / Meta / TikTok Ads / Fish Speech / Flick raman stub-uri care ridica `SetupRequiredError`. |

## Utilizare

```powershell
.venv\Scripts\python.exe -m ppc_agent.cli --help
```

| Comanda | Rol |
|---------|-----|
| `ingest --url <domeniu>` | Modulul 1: crawling + date organice + expansiune cuvinte cheie |
| `plan` | Kelly (plafon zilnic) + Thompson (Google Ads + TikTok Ads combinate) + Markov + Quality Score + lichiditate Meta |
| `copy --keyword <kw> --usp <text> --trigger <pas\|status\|fomo\|aida>` | Genereaza copy emotional (Google); il adauga in `proposed_ads_queue.json` (HITL). `--dry-run` disponibil |
| `build-creative --keyword <kw> --broll <video> [--platform google\|tiktok]` | Modulul 5: copy -> voce (Fish Speech) -> video (Flick) -> `.mp4` in `creative_output/`. `tiktok` = script UGC, video 9:16 |
| `ingest-tiktok --input <csv\|json>` | Valideaza anunturi TikTok dovedite si le adauga in `tiktok_swipe_library.json` (fara LLM — alimenteaza RAG-ul de mai sus) |
| `ingest-swipes --csv <fisier> --platform <google\|meta\|tiktok>` | Valideaza anunturi dovedite si le adauga in `omnichannel_swipe_library` din `swipe_file.json` (fara LLM) |
| `copy-omnichannel --niche <text> --usp <text> [--target-platform google\|meta\|tiktok]` | Genereaza copy omnicanal (RAG pe nisa+platforma); doar afiseaza, fara coada HITL proprie |
| `propose` | Modulul 4: scrie `proposed_changes_*.json` (nu aplica nimic) |
| `status` | Arata setul de modificari in asteptare si modul furnizorilor |
| `execute --changeset <fisier> --confirm` | Modulul 4: executa un set confirmat (simulat in v1) |

### TikTok — doua lucruri separate

- **Date de cont** (`providers/mock/tiktok.py`, Faza B): performanta grupurilor de
  anunturi + parcursuri de conversie, aceeasi forma ca Google Ads — brate Thompson
  (`platform="tiktok_ads"`, prefix `tt_`) si touchpoint-uri Markov, combinate cu
  Google Ads intr-un singur plafon/alocare in `plan` (vezi Faza C mai jos).
- **Creatie** (`copywriter/` + `creative/`, Faza A): script video UGC (hook +
  body + CTA + `text_overlay`), RAG pe **nisa/cuvant cheie** (nu emotion_trigger
  ca la Google) peste `tiktok_swipe_library` din `swipe_file.json`, cu
  `days_active_proxy` ca semnal de departajare (reclama activa mai mult timp =
  dovedita). `ingest-tiktok` construieste biblioteca proprie din anunturi reale.

### RAG omnicanal (Google + Meta + TikTok, `copy-omnichannel`)

Separat de `copy`/`ingest-tiktok` de mai sus (care raman neschimbate): o a doua
cale de generare, `generate_omnichannel_copy`, care acopera toate cele trei
platforme printr-o singura schema unificata (`OmniSwipeRecord`, cheia
`omnichannel_swipe_library` din `swipe_file.json`). Diferente cheie fata de
fluxul original:

- **Recuperare**: filtrare stricta dupa `platform`, apoi RAG pe **nisa**
  (nu declansator emotional/cuvant cheie exact-match); la egalitate castiga
  semnalele proxy de performanta — `longevity_days` si `variation_count` — nu
  un ROI auto-raportat, usor de umflat.
- **Prompt dinamic per canal**: Google (limite stricte, intentie de cautare,
  text-only), Meta (formate cu longevitate dovedita, ton advertorial, text mai
  lung), TikTok (hook 0-3s, pattern interrupt, ritm UGC) — vezi
  `build_omnichannel_system_prompt` in `copywriter/engine.py`.
- **Ingestie**: `ingest-swipes --csv <fisier> --platform <x>` scrie direct in
  `swipe_file.json` (spre deosebire de `ingest-tiktok`, care acumuleaza
  intr-un fisier separat, generat) — un instrument de curatare a bibliotecii
  sursa, nu de acumulare bruta.

`copy`/`build-creative`/`ingest-tiktok` raman 100% neschimbate — cele doua
cai coexista, folosesc acelasi client LLM injectat (mock sau Ollama live).

## Modelul de siguranta

### Poarta de aprobare (`ApprovalGate`, Modulul 4)

Nicio operatie de scriere (POST / PUT / DELETE catre platformele de reclame) nu
poate ocoli fluxul:

```
propose(change)  ->  flush()  ->  proposed_changes_*.json  ->  revizuire umana  ->  execute(--confirm)
```

- `flush()` trece intai cheltuiala zilnica totala prin `AbsoluteSpendLimiter`.
  Un set care depaseste limita **nu se scrie deloc** pe disc.
- `execute` fara `--confirm` ridica `ApprovalRequiredError` (iesire non-zero din CLI).
- In v1, `execute --confirm` doar **logheaza** apelurile pe care le-ar face
  (`[SIMULAT] ar apela API-ul de reclame: ...`) si returneaza `applied=False`.
  Nu se atinge niciun API real.

### Limite de cheltuiala

| Nivel | Sursa | Rol |
|-------|-------|-----|
| `budget.max_daily_spend` | `config.yaml` | Plafonul zilnic **de baza**. Kelly poate scala peste el cand ROAS-ul contului e bun. |
| plafon dimensionat Kelly | `decision/kelly_sizing.py` | `min(HARD_CEILING, max_daily_spend * multiplicator Half-Kelly)`; devine limita efectiva a `AbsoluteSpendLimiter` in `propose`. |
| `HARD_CEILING = 500.00` | hardcodat in `ppc_agent/guardrails/spend_limiter.py` | Plafon absolut inviolabil. Nimic (nici Kelly) nu il poate depasi. |

### Kelly Criterion — dimensionarea plafonului zilnic

Thompson Sampling decide *cum se imparte* bugetul intre campanii; Kelly decide
*cat de mare* e plafonul zilnic total, in functie de avantajul matematic al
contului:

- **`calculate_kelly_fraction(win_prob, roas_odds, fraction=0.5)`** — Half-Kelly:
  `f = fraction * (p*b - q) / b`, taiat la `[-1, 1]`.
- **`size_daily_budget(arms, baseline_cap, hard_ceiling, ...)`** — foloseste ROAS-ul
  contului: `win_prob = ROAS/(ROAS+1)`, `roas_odds = ROAS - 1`. Multiplicatorul
  `clamp(1 + f, 0.5, 2.0)` se aplica pe `baseline_cap`, apoi se taie la `HARD_CEILING`.
  - ROAS > 1 (EV pozitiv) → plafon **peste** `max_daily_spend`, catre `HARD_CEILING`
  - ROAS ≈ 1 → plafon **mentinut** la `max_daily_spend`
  - ROAS < 1 (EV negativ) → plafon **redus** (pastrare de capital)
  - fara click-uri / fara cost → `date_insuficiente`, plafon mentinut (fail-safe)
- Rationamentul Kelly se adauga la `rationale` fiecarei modificari de buget din
  `proposed_changes_*.json`. Umanul aproba tot inainte de `execute`.

`run_plan(..., kelly_fraction=0.0)` dezactiveaza scalarea (plafon = `max_daily_spend`).

### Schema `proposed_changes_*.json`

```json
{
  "created_at": "2026-09-10T12:25:16.902510Z",
  "account": "mock:mock-account",
  "spend_limit": "50.00",
  "hard_ceiling": "500.00",
  "total_projected_daily_spend": "50.00",
  "changes": [
    {
      "op": "UPDATE",                       // CREATE | UPDATE | PAUSE
      "resource": "campaign/c_brand",
      "resource_type": "campaign",
      "before": {},
      "after": { "daily_budget": "30.00" },
      "projected_daily_spend": "30.00",
      "rationale": "Thompson Sampling: P(cel mai bun)=1.000",
      "source_module": "budget"             // budget | negatives | meta_liquidity
    }
  ]
}
```

### Alte garantii

- **Fara credentiale in cod sau in git.** Doar `.env` local, ignorat de git.
- **`proposed_changes*.json`, `config.yaml` si `*.db` sunt in `.gitignore`.**
- **Toate testele ruleaza fara retea** (furnizori `mock` + fixture-uri locale +
  SQLite in-memory pentru server — nici `tests/`, nici `tests_server/` nu ating
  vreodata Ollama, Redis sau Postgres reale).

## De la `mock` la `live`

Fiecare furnizor extern are trei parti in `ppc_agent/providers/`:

| Parte | Fisier | Stare |
|-------|--------|-------|
| interfata (ABC) | `base.py` | completa |
| implementare `mock` | `mock/*.py` | completa, deterministica, fara retea |
| stub `live` | `live/__init__.py` | ridica `SetupRequiredError` |

Pentru a activa un client real:

1. Obtine credentialele (Google Ads developer token + OAuth2, Meta app, TikTok
   Ads `PPC_TIKTOK_ACCESS_TOKEN`/`PPC_TIKTOK_ADVERTISER_ID`) si pune-le in `.env`.
2. Implementeaza metodele din clasa `Live*Provider` corespunzatoare, folosind
   SDK-ul oficial.
3. Seteaza `PPC_PROVIDER_MODE=live`. `ProviderFactory` va comuta automat.

Guardrails-urile din Modulul 4 raman active identic in modul `live`; in plus,
executorul din `ApprovalGate.execute` trebuie schimbat din "simuleaza" in
"apeleaza SDK-ul" — un singur loc in cod.

## Client LLM live: Ollama local

Spre deosebire de Google Ads / Meta / Fish Speech / Flick, clientul LLM folosit
de `copy` si `build-creative` (`LiveLLMClient`, in `copywriter/llm.py`) **este
functional in modul `live`** — nu un stub. Ruleaza impotriva unui server
[Ollama](https://ollama.com) local:

- **Gratis** — fara cheie API, fara cost per-token.
- **Datele nu parasesc masina** — e singurul apel de retea din tot agentul, dar
  ramane strict loopback (`http://localhost:11434` implicit).
- **Testele raman offline** — suita foloseste `httpx.MockTransport` (vezi
  `tests/test_llm_live.py`); niciun test nu atinge un Ollama real.

### Setup

```powershell
# 1) instaleaza Ollama (https://ollama.com/download), apoi:
ollama serve
ollama pull llama3        # sau orice alt model instalat local
```

```ini
# .env
PPC_PROVIDER_MODE=live
PPC_LLM_MODEL=llama3      # sau "ollama/llama3" — prefixul se elimina automat
PPC_LLM_ENDPOINT=         # gol => http://localhost:11434
```

### Erori clare, nu traceback-uri

`LiveLLMClient` distinge explicit intre cauze, cu mesaje actionabile:

| Situatie | Eroare | Mesaj |
|----------|--------|-------|
| Ollama nu ruleaza | `SetupRequiredError` | indica `ollama serve` |
| timeout (model prea mare / hardware lent) | `SetupRequiredError` | sugereaza un model mai mic |
| modelul cerut nu e descarcat | `SetupRequiredError` | listeaza modelele instalate local + `ollama pull <model>` |
| raspuns intrerupt (`"done": false"`) | `CopywriterError` | model corupt / incarcare esuata — verifica `ollama ps` |
| JSON invalid / campuri lipsa | `CopywriterError` | raspunsul modelului nu respecta schema ceruta |

> **Nota din testare reala:** modelele mici/quantizate pot produce ocazional
> raspunsuri incomplete sau incoerente (vazut cu un model de 1.5B pe hardware
> modest). Daca se intampla des, incearca un model diferit sau redescarca-l cu
> `ollama pull`.

## Server (backend multi-tenant)

`ppc_agent_server/` e un backend B2B FastAPI separat de CLI — mai multe
agentii, fiecare cu clientii ei gestionati, autentificare prin cheie API.
Import intr-o singura directie: serverul foloseste pipeline-urile pure din
`ppc_agent` (nu le duplica); `ppc_agent`/CLI nu stie ca serverul exista.

### Instalare si pornire

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-server.txt
.venv\Scripts\python.exe -m alembic upgrade head   # SQLite implicit - fara nimic de instalat
.venv\Scripts\python.exe -m uvicorn ppc_agent_server.app:app --reload
```

Server-only — un utilizator doar-CLI nu instaleaza `requirements-server.txt`
(FastAPI/SQLModel/Alembic/ARQ/Redis raman straine de `ppc_agent`).

### Autentificare

O agentie (`Tenant`) primeste o cheie API la creare — **operatie administrativa**,
in afara API-ului (fara auto-inregistrare):

```python
from sqlmodel import Session
from ppc_agent_server.db import get_engine
from ppc_agent_server.auth import create_tenant

with Session(get_engine()) as session:
    tenant, raw_key = create_tenant(session, "Agentia Mea SRL")
    print(raw_key)  # aratat o singura data - doar hash-ul SHA-256 se stocheaza
```

Fiecare cerere: antetul `Authorization: Bearer <cheie>`.

### Variabile de mediu (acelasi `.env`, fara conflict cu `PPC_*`)

| Variabila | Implicit | Efect |
|-----------|----------|-------|
| `DATABASE_URL` | `sqlite:///./ppc_agent_server.db` | Postgres real: `postgresql://user:pass@host/db` |
| `REDIS_URL` | necompletat -> `InlineJobQueue` | Seteaza pentru `ArqJobQueue` reala: `redis://localhost:6379/0` |

### Endpoint-uri

| Ruta | Rol |
|------|-----|
| `POST /api/v1/auth/mcc-connect` | Stub (ca toate integrarile live) — ridica `SetupRequiredError` -> 503 |
| `POST /api/v1/clients` | Inregistreaza un cont gestionat pentru agentia autentificata |
| `POST /api/v1/jobs/plan` | Dispecerizeaza Kelly + Thompson (Google+TikTok) + Markov pentru un client |
| `POST /api/v1/jobs/copy` | Dispecerizeaza copy emotional (`platform: google\|tiktok`) -> `AdQueueItem` |
| `POST /api/v1/jobs/creative` | Dispecerizeaza Modulul 5 (voce+video) -> `CreativeArtifact` |
| `GET /api/v1/jobs/{task_id}` | Starea unui job (`queued`/`running`/`success`/`failed` + rezultat) |
| `GET /api/v1/proposals/{client_id}` | Modificarile in asteptare (`status=pending`) ale unui client |
| `POST /api/v1/proposals/{id}/execute` | Poarta HITL — `confirm=true` obligatoriu, trece prin `AbsoluteSpendLimiter` |

> **Gap semnalat, nu construit:** niciun endpoint nu creeaza inca `ProposedChange`
> automat dintr-un plan — echivalentul comenzii `propose` din CLI. O extensie
> naturala, in afara listei de cerinte initiale.

Mapare eroare -> HTTP (Starlette, pe `__mro__`): `SetupRequiredError`→503,
`SpendLimitExceeded`→409, `ApprovalRequiredError`→403, `CopywriterError`
(si subclase)→422, `PpcAgentError`→500 (fallback generic).

### De la SQLite la PostgreSQL

| | SQLite (implicit) | PostgreSQL |
|---|---|---|
| Instalare | niciuna | `docker compose up -d` (vezi `docker-compose.yml`) |
| `DATABASE_URL` | necompletat | `postgresql://ppc_agent:ppc_agent@localhost:5432/ppc_agent` |
| Migratii | `alembic upgrade head` | identic — acelasi Alembic, alt dialect |

### De la coada in proces la ARQ+Redis

| | `InlineJobQueue` (implicit) | `ArqJobQueue` |
|---|---|---|
| Instalare | niciuna | `docker compose up -d` + `REDIS_URL=redis://localhost:6379/0` |
| Executie | sincron, in procesul serverului | proces worker separat: `arq ppc_agent_server.jobs.worker.WorkerSettings` |
| Contract API | identic (`POST` -> `task_id`, `GET` -> stare) | identic — comutare fara nicio schimbare in router-e |

Comutarea e automata, dupa `REDIS_URL` — niciun cod de apelat diferit.

### Teste server

```powershell
.venv\Scripts\python.exe -m pytest tests_server
.venv\Scripts\python.exe -m mypy --strict ppc_agent_server
```

100% offline — SQLite in-memory, `InlineJobQueue`, zero Redis/Postgres reale
(la fel ca restul proiectului). `ruff check` (fara argument de cale) acopera
deja tot, inclusiv `ppc_agent_server/` si `tests_server/`.

## Dezvoltare

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m mypy --strict ppc_agent
.venv\Scripts\python.exe -m ruff check
```

## Structura

```
swipe_file.json        formule Google + tiktok_swipe_library (RAG local, editabil)
docker-compose.yml      Postgres+Redis optionale (productie-like, niciodata necesar)
alembic.ini              configurare Alembic (script_location -> ppc_agent_server/migrations)
requirements.txt          dependinte CLI
requirements-server.txt    dependinte server (include requirements.txt)

ppc_agent/                # CLI, un singur marketer/agentie
  config.py       configuratie (pydantic-settings + YAML)
  errors.py       tipuri de exceptii partajate
  cli.py          interfata linie de comanda (typer) — ingest/plan/copy/build-creative/ingest-tiktok/ingest-swipes/copy-omnichannel/propose/status/execute
  texttools.py    normalizare / tokenizare / sentiment (modul frunza)
  providers/      adaptoare externe: base (ABC), factory, mock/ (incl. tiktok.py), live/
  ingestion/      Modulul 1 — context, ingestie, tiktok_ingestion.py + swipe_ingestion.py (bibliotecile RAG)
  decision/       Modulul 2 — Thompson Sampling (Google+TikTok) + Markov + Kelly (kelly_sizing.py)
  alignment/      Modulul 3 — Quality Score + lichiditate Meta
  guardrails/     Modulul 4 — ApprovalGate + AbsoluteSpendLimiter
  copywriter/     copy emotional Google + script UGC TikTok + RAG omnicanal (engine, llm, swipe, pipeline)
  creative/       Modulul 5 — audio_engine (Fish Speech) + video_engine (Flick, 16:9/9:16) + factory
tests/
  fixtures/       date de test locale

ppc_agent_server/          # backend B2B multi-tenant (FastAPI)
  app.py          fabrica aplicatiei + handler-e de eroare globale
  settings.py     configurare server (DATABASE_URL, REDIS_URL)
  db.py           engine + sesiuni SQLModel
  models.py       schema: Tenant -> ClientAccount -> (ProposedChange, AdQueueItem, CreativeArtifact)
  auth.py         chei API (generare, hash, create_tenant, get_current_tenant)
  deps.py         dependinte partajate (apartenenta client -> tenant)
  schemas.py      scheme Pydantic request/response
  routers/        auth, clients, jobs, proposals
  jobs/           queue.py (Protocol + InlineJobQueue), arq_queue.py, worker.py, tasks.py
  migrations/      Alembic — o singura migratie initiala
tests_server/
  conftest.py     SQLite in-memory + client FastAPI, izolate per test
```
