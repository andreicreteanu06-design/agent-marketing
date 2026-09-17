# Agent PPC

Unealta Python, controlata prin configuratie, care ajuta marketerii sa planifice
si sa gestioneze campanii **Google Ads**, **Meta Ads** si **TikTok Ads**,
folosind modele matematice pentru alocarea bugetului si atribuire, in spatele
unor **guardrails stricte cu om in bucla (HITL)**. Doua moduri de rulare:
**CLI local** (`ppc_agent`, un singur marketer/agentie) si **server B2B
multi-tenant** (`ppc_agent_server/`, mai multe agentii — [detalii mai jos](#server-backend-multi-tenant)),
al doilea fiind un wrapper subtire peste exact aceleasi pipeline-uri pure.

> Implicit (`mock`), niciun apel real nu paraseste procesul — fiecare integrare
> externa sta in spatele unui adaptor cu implementare `mock`, deci intreaga
> logica e testabila offline. **Google Ads / Meta Ads / TikTok Ads au acum si
> clienti `live` reali** (doar citire — vezi [Integrare live](#integrare-live-googlemetatiktok-ads)
> mai jos), la fel ca [clientul LLM (Ollama local)](#client-llm-live-ollama-local).
> `execute` ramane **intotdeauna simulat** (`applied=False`), indiferent de
> `--confirm` — scrierea reala pe conturi ramane un pas viitor, deliberat
> separat. Crawler/GSC/GBP/Keyword Planner (Modulul 1) si Fish Speech/Flick
> (Modulul 5) raman stub-uri `live`.

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
| + | Meta ca brate Thompson + touchpoint-uri Markov (combinat cu Google Ads + TikTok Ads) | ✅ |
| + | Clienti live reali — Google/Meta/TikTok **Ads** (citire: performanta + lichiditate Meta) | ✅ |
| — | Integrare `live` ramasa (GSC / GBP / Keyword Planner / Fish Speech / Flick / `execute` real) | ⏳ |

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
| `live` | Clientul LLM (Ollama) si Google/Meta/TikTok **Ads** (citire) sunt functionale — vezi [Integrare live](#integrare-live-googlemetatiktok-ads). GSC/GBP/Keyword Planner/Fish Speech/Flick raman stub-uri care ridica `SetupRequiredError`. |

## Utilizare

```powershell
.venv\Scripts\python.exe -m ppc_agent.cli --help
```

| Comanda | Rol |
|---------|-----|
| `ingest --url <domeniu>` | Modulul 1: crawling + date organice + expansiune cuvinte cheie |
| `plan` | Kelly (plafon zilnic) + Thompson (Google + TikTok + Meta Ads combinate) + Markov + Quality Score + lichiditate Meta |
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
  Google Ads intr-un singur plafon/alocare in `plan` (vezi Faza C mai jos). Meta
  Ads participa acum la fel (`platform="meta_ads"`, `providers/mock/meta.py`,
  `campaign_performance()`/`conversion_paths()` pe aceleasi seturi de reclame
  folosite si de lichiditatea Meta) — trei platforme intr-un singur bandit.
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

### Forecasting (opt-in) — proiectie inaintea Kelly/Thompson

`decision/forecasting.py` adauga o etapa NOUA, opt-in, care se conecteaza
*inaintea* lui Kelly/Thompson, nu in locul lor: `run_plan(..., forecaster=...,
histories=...)` proiecteaza fiecare brat pe urmatoarele `forecast_horizon_days`
zile si trece proiectia (nu istoricul brut) mai departe. `kelly_sizing.py` si
`budget.py` raman **complet neschimbate** — primesc un `ArmStats` ca oricare
altul, indiferent daca vine dintr-un raport brut sau dintr-o proiectie.
Implicit (`forecaster=None`) comportamentul e identic cu inainte.

- **`MockForecaster`** — regresie liniara determinista pe fiecare metrica, fara
  retea si fara ML. Implicit (mock-first, ca peste tot in proiect).
- **`LiveTimesFmForecaster`** — [TimesFM 2.5](https://github.com/google-research/timesfm)
  (Google Research): model fundament de serii de timp, pre-antrenat, zero-shot
  (nu are nevoie sa fie (re)antrenat pe contul clientului). Opt-in:

  ```bash
  pip install -r requirements-timesfm.txt
  ```

  **Licenta:** foloseste explicit checkpoint-ul `google/timesfm-2.5-200m-pytorch`
  (greutati Apache-2.0, sigur comercial) — NU `3.0` (licenta non-comerciala a
  greutatilor). Constant de cod (`_TIMESFM_CHECKPOINT`), deliberat neexpus ca
  variabila de mediu, ca sa nu poata fi schimbat din greseala.
  Prima folosire descarca checkpoint-ul de pe Hugging Face (retea necesara);
  ruleaza pe CPU (torch instalat aici e build CPU-only, fara CUDA).

**CLI**: `ppc-agent plan --forecast` (si `propose --forecast`), optional
`--forecast-engine mock|timesfm` (implicit `mock`). Activ **DOAR in mod live**
(`PPC_PROVIDER_MODE=live`) **si doar** daca cel putin un furnizor conectat
implementeaza `pipeline.SupportsDailyPerformance` (un `Protocol`
`runtime_checkable`, verificat cu `isinstance` — nicio modificare la ABC-urile
din `providers/base.py`, niciun furnizor live existent nu se strica). Fara
asta, `--forecast` afiseaza un mesaj clar si continua identic cu comportamentul
de azi — nu esueaza, nu se blocheaza.

- **Gap onest**: niciun furnizor (mock SAU live) nu implementeaza inca
  `SupportsDailyPerformance` azi — deci `--forecast` e deocamdata mereu un
  no-op informativ, in orice mod. Deliberat: mock-ul nu fabrica un trend zilnic
  dintr-un agregat static caruia nu i se cunoaste distributia reala (ar fi date
  inventate, prezentate ca semnal). Pasul ramas: implementarea reala per
  platforma (Google Ads GAQL cu `segments.date`, Meta Insights API cu
  `time_increment=1`, TikTok Reporting API cu `stat_time_day`) pe unul din
  `providers/live/*.py` — in clipa in care exista, `--forecast` il foloseste
  automat, fara nicio alta modificare de cod.

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
| implementare `live` | `live/*.py` | Google/Meta/TikTok **Ads**: reala (citire — vezi mai jos). Crawler/GSC/GBP/Keyword Planner (Modulul 1): stub, ridica `SetupRequiredError` |

Guardrails-urile din Modulul 4 raman active identic in modul `live`. `execute`
ramane **intotdeauna simulat** (`applied=False`), indiferent de mod sau de
`--confirm` — scrierea reala pe conturi e un pas viitor, deliberat separat.

## Integrare live: Google/Meta/TikTok Ads

`LiveGoogleAdsProvider`/`LiveMetaMarketingProvider`/`LiveTikTokAdsProvider`
(`ppc_agent/providers/live/{google_ads,meta,tiktok}.py`) citesc date reale de
performanta direct prin REST (`httpx`), acelasi pattern ca `LiveLLMClient` mai
jos — fara SDK-uri oficiale (`google-ads` gRPC, `facebook-business`, SDK
TikTok): dependinte grele, inconsistente cu restul codebase-ului (100%
httpx), greu de instalat pe Windows. Testabile determinist cu
`httpx.MockTransport` (`tests/test_live_google_ads.py` / `test_live_meta.py` /
`test_live_tiktok.py`) — zero dependinte noi.

### Setup

```ini
# .env
PPC_PROVIDER_MODE=live

# Google Ads - developer token (aprobare Google) + OAuth2 (client + refresh token)
PPC_GOOGLE_ADS_DEVELOPER_TOKEN=
PPC_GOOGLE_ADS_CLIENT_ID=
PPC_GOOGLE_ADS_CLIENT_SECRET=
PPC_GOOGLE_ADS_REFRESH_TOKEN=
PPC_GOOGLE_ADS_CUSTOMER_ID=         # contul ale carui campanii sunt citite
PPC_GOOGLE_ADS_LOGIN_CUSTOMER_ID=   # doar daca accesezi contul de mai sus printr-un cont manager/MCC

# Meta - token System User recomandat (nu expira ca un token de utilizator normal)
PPC_META_ACCESS_TOKEN=
PPC_META_AD_ACCOUNT_ID=

# TikTok - token din TikTok for Business developer portal
PPC_TIKTOK_ACCESS_TOKEN=
PPC_TIKTOK_ADVERTISER_ID=
```

Obtinerea fiecarui credential e un proces extern la platforma respectiva, in
afara scopului acestui README — vezi documentatia oficiala: [Google Ads API —
get started](https://developers.google.com/google-ads/api/docs/get-started/introduction),
[Meta Marketing API — access tokens](https://developers.facebook.com/docs/marketing-apis/overview/authentication),
[TikTok for Business — authentication](https://business-api.tiktok.com/portal/docs).

### Gap-uri oneste — citeste inainte sa te bazezi pe date live

- **Parcursuri de conversie (`conversion_paths`)**: niciuna dintre cele trei
  API-uri nu mai expune simplu parcursuri multi-touch (Google a depreciat
  Multi-Channel Funnels; Meta le tine intr-un produs Attribution separat;
  TikTok nu le expune in raportarea de baza). Fallback documentat in cod: un
  singur touchpoint (numele campaniei/grupului/setului) per conversie si per
  non-conversie, plafonat la 500/brat — pastreaza atribuirea Markov matematic
  valida, dar **fara semnal multi-touch real**.
- **Venitul TikTok**: raportul de baza nu are un camp de valoare/venit per
  conversie confirmat (depinde de evenimentul de pixel configurat de agentie)
  — `LiveTikTokAdsProvider.campaign_performance()` intoarce `revenue=0.0`, cu
  comentariu explicit in cod. Pana la verificare manuala, bratele TikTok vor
  arata ROAS 0 in Kelly/bandit.
- **Venitul Google fara value tracking**: daca contul Google Ads nu are
  urmarirea valorii conversiilor activata, `metrics.conversions_value` e 0 —
  acelasi simptom (ROAS 0). Solutie: activeaza value tracking pe cont, sau
  foloseste `target_cpa`/`budget-advice` (deja existent), care nu depinde de
  venit.
- **Netestat impotriva unui API real**: fara credentiale reale, verificarea
  ramane `httpx.MockTransport` (deterministic, ca la `LiveLLMClient`) —
  acelasi statut epistemic ca `ArqJobQueue` (netestat impotriva unui Redis
  real). Testeaza cu credentialele tale inainte sa te bazezi pe rezultate.

## Generative Engine Ads (ChatGPT) — fundatie, inca stub

Cercetat explicit (nu presupus) inainte de a scrie cod — vezi si
[developers.openai.com/ads](https://developers.openai.com/ads):

- **OpenAI Ads e real**: self-serve din mai 2026 (`ads.openai.com`), campanii
  cu buget minim 25 USD/zi, targetare **contextuala pe conversatie** (nu pe
  cuvinte cheie, spre deosebire de Google). Exista si un API programatic real
  (`api.ads.openai.com/v1`, obiecte `Campaign`/`AdGroup`), dar **accesul e
  limitat la parteneri aprobati de OpenAI** — fara cont de agentie aprobat,
  nu exista nimic de conectat azi.
- **Perplexity NU are niciun produs de reclame** — a testat "sponsored
  questions" in 2024-2025, dar a abandonat reclamele in februarie 2026
  (subscription-only). Nu exista niciun provider/stub Perplexity in cod, ca sa
  nu sugereze o integrare posibila care pur si simplu nu exista azi.

**Ce exista in cod:**

- `providers/base.py::BaseMarketingProvider` — contract generic
  (`get_campaign_metrics`/`scale_budget`/`pause_ad`) pentru platforme NOI care
  nu au inca un loc in Modulul 2. Google/Meta/TikTok **nu** mostenesc aceasta
  clasa — au deja un contract stabilit si cablat (`campaign_performance`/
  `conversion_paths`), schimbarea lui ar fi invaziva pentru zero beneficiu.
- `providers.live.LiveGenerativeEngineProvider` — stub (ca celelalte 4
  furnizori live neconectati inca): fiecare metoda ridica
  `SetupRequiredError` cu detalii reale (API-ul exista, accesul cere
  aprobare de partener), niciun apel de retea.
- `ClientAccount.chatgpt_ads_account_id`/`chatgpt_ads_api_key_enc` (server) —
  campurile de conectare exista din azi (aceeasi forma ca Google/Meta/TikTok),
  dar neexpuse inca in nicio ruta — nimic nu le citeste/scrie pana la
  implementarea reala a providerului.
- `AdPlatform` (server, `models.py`) — al treilea enum de platforma
  (`META`/`CHATGPT`/`PERPLEXITY`), scopat la `BaseMarketingProvider` — distinct
  de `Platform` (creatie de copy) si `AdFatiguePlatform` (monitorul de
  oboseala), acelasi principiu ca de ce exista deja doua enum-uri separate.

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
| `POST /api/v1/jobs/plan` | Dispecerizeaza Kelly + Thompson (Google+TikTok+Meta) + Markov pentru un client |
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

## Agent SEO+GEO (separat)

`seo_geo_agent/` e un al doilea agent AI, complet separat de `ppc_agent`/
`ppc_agent_server` — propriul FastAPI app, propriul port, propriile dependinte
(`requirements-seo-geo.txt`, fara SQLModel/Alembic/Redis — nu are baza de date
proprie). Un singur endpoint: `POST /api/v1/seo-geo/analyze` — primeste un
domeniu + rapoarte brute ale clientului (Ahrefs/Semrush/GSC, text lipit ca
atare) si returneaza `seo_score`/`geo_score` (0-100) plus liste de sugestii
actionabile (cod JSON-LD exact, nu sfaturi generice — vezi `prompts.py`).

Autentificare: **acelasi token JWT** emis de `POST /api/v1/login` din
`ppc_agent_server` (secret comun — `JWT_SECRET_KEY`, fara prefix, in acelasi
`.env`) — un client deja autentificat pe site nu are nevoie de un al doilea
login pentru acest feature premium. Fara acces la baza de date a
`ppc_agent_server`: doar semnatura + expirarea token-ului sunt verificate.

```powershell
pip install -r requirements-seo-geo.txt
.venv\Scripts\python.exe -m uvicorn seo_geo_agent.app:app --reload --port 8001
```

Implicit (`SEOGEO_PROVIDER_MODE=mock`), raspunde determinist, fara Ollama
pornit — la fel ca restul proiectului. Pentru analiza reala:
`SEOGEO_PROVIDER_MODE=live` + Ollama local (vezi
[client LLM (Ollama local)](#client-llm-live-ollama-local) — acelasi principiu,
alt model implicit, vezi `.env.example`).

### Teste seo_geo_agent

```powershell
.venv\Scripts\python.exe -m pytest tests_seo_geo
.venv\Scripts\python.exe -m mypy --strict seo_geo_agent
```

100% offline — `MockLLMClient` + `httpx.MockTransport` pentru testele
`LiveLLMClient`, zero retea reala. `ruff check` acopera deja
`seo_geo_agent/` si `tests_seo_geo/`.

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
  decision/       Modulul 2 — Thompson Sampling (Google+TikTok+Meta) + Markov + Kelly (kelly_sizing.py)
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
