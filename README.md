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
> separat. Modulul 1 e complet `live` — crawler (peste motorul de audit din
> `seo_geo_agent`), Search Console, Keyword Planner si Business Profile. Fish
> Speech/Flick (Modulul 5) si OpenAI Ads raman stub-uri.

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
| implementare `live` | `live/*.py` | Toate reale. Google/Meta/TikTok **Ads** (citire + scriere pe Meta), crawler (peste `seo_geo_agent.audit`), Search Console, Keyword Planner, Business Profile. Singurul stub ramas: OpenAI Ads |

Guardrails-urile din Modulul 4 raman active identic in modul `live`. `execute`
din **CLI** ramane **intotdeauna simulat** (`applied=False`), indiferent de mod
sau de `--confirm`. Scrierea reala pe conturi exista doar pe serverul
multi-tenant, in spatele aprobarii umane din contul clientului
(`POST /api/v1/proposals/{id}/approve`), si doar pentru Meta — vezi
"Ce se aplica efectiv la `/approve`" mai jos.

## Modulul 1 live: Search Console, Keyword Planner, Business Profile

| Furnizor | API | Ce trebuie |
|---|---|---|
| `LiveGscProvider` | Search Analytics | OAuth cu scope `webmasters.readonly` + proprietatea verificata (`PPC_GSC_SITE_URL`) |
| `LiveKeywordPlannerProvider` | `GenerateKeywordIdeas` (Google Ads) | Credentialele **Google Ads** (alt scope: `adwords`, plus developer token) |
| `LiveGbpProvider` | Business Information + My Business v4 | OAuth cu scope `business.manage` **si acces aprobat de Google** |

Trei lucruri care ar strica tacut rapoarte, si cum sunt tratate:

- **Constantele de limba si tara nu sunt scrise de mana.** Id-ul Google pentru
  romana nu se deduce din codul ISO, iar o constanta gresita intoarce volume
  pentru alta limba — fara nicio eroare, deci fara nicio sansa s-o observi din
  raport. Furnizorul le cere de la API (`language_constant`/`geo_target_constant`)
  si le tine in cache pe durata instantei: doua cereri in plus, o data.
- **Proprietatea Search Console nu se ghiceste din domeniu.** `sc-domain:exemplu.ro`
  si `https://exemplu.ro/` sunt proprietati diferite, si din "exemplu.ro" nu
  poti sti care e verificata pe cont. Se ia din `PPC_GSC_SITE_URL` (sau din
  `ClientAccount.gsc_site_url`), si abia daca lipseste se normalizeaza ce vine.
- **Volumele exacte cer cheltuiala activa.** Un cont Google Ads fara istoric
  primeste intervale (`100-1K`), nu numere. Nu compensam cu estimari proprii:
  cifra din raport e a Google sau nu exista. Cand API-ul da doar eticheta de
  competitie, folosim mijlocul galetii si o spunem in cod.

Business Profile e singurul din trei care **nu se activeaza singur**: cere
"Basic API Access" aprobat pentru proiect, cu raspuns in 7-10 zile lucratoare.
Pana atunci primeste 403, iar furnizorul spune exact asta, ca sa nu para o
setare gresita pe care ai putea-o repara. Daca lipseste doar contul (nu si
locatia), se intorc numele si categoriile cu `review_count=0` — un semnal
partial e mai util decat o eroare, si cifra zero o spune singura.

## Crawler live: un singur crawler in tot repo-ul

`LiveCrawlerProvider` (`ppc_agent/providers/live/crawler.py`) nu are crawler
propriu: importa din `seo_geo_agent.audit` validarea anti-SSRF a tintei
(`is_crawlable_url`), plafonul de octeti (`MAX_HTML_BYTES`), antetele si
clasificarea raspunsului (`classify_fetch`). Motivul e simplu — doua crawlere in
acelasi repo ar insemna doua politici de siguranta care diverg in timp, iar cea
care ramane in urma e cea care face rau.

Ce traduce adaptorul e doar forma: auditul intoarce o pagina deja analizata
(`CrawledPage`), pe cand Modulul 1 isi face singur parsarea si are nevoie de
HTML brut (`FetchResult`) — cauta alte lucruri (CTA-uri, elemente de navigatie,
candidati de USP), nu aceleasi.

Regula de onestitate a auditului trece si ea neschimbata: cand site-ul ne
opreste (403, 429, challenge anti-bot), adaptorul ridica `CrawlBlockedError`, nu
intoarce o pagina goala. Numele clasei ajunge in `PageContext.failure_reason`,
deci in raport se vede "n-am avut voie sa citesc", nu "pagina n-are continut" —
doua lucruri foarte diferite pentru Quality Score.

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
| `DATABASE_URL` | `sqlite:///./ppc_agent_server.db` | Postgres real: `postgresql+psycopg://user:pass@host/db` |
| `REDIS_URL` | necompletat -> `InlineJobQueue` | Seteaza pentru `ArqJobQueue` reala: `redis://localhost:6379/0` |
| `PUBLIC_API_URL` | `http://localhost:8000` | Din ea se construieste `redirect_uri`-ul OAuth Google (vezi Integrari Google) |
| `SITE_URL` | `http://localhost:3000` | Unde revine clientul dupa ecranul de consimtamant Google |
| `HUGGINGFACE_API_KEY` | necompletat -> mesaj din template | Vocea CMO a Reginei si a consiliului din chat, prin Hugging Face Inference Providers (faptele directivei si cifrele PPC parasesc masina) |
| `HUGGINGFACE_MODEL` | `meta-llama/Meta-Llama-3-8B-Instruct` | Modelul vocii CMO; trebuie servit de un furnizor Inference Providers |

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
| `POST /api/v1/proposals/{id}/execute` | Poarta HITL (agentie) — `confirm=true` obligatoriu, trece prin `AbsoluteSpendLimiter`; **simulat**, nu atinge nicio platforma |
| `GET /api/v1/proposals/pending` | Propunerile in asteptare ale clientului autentificat (JWT de client) |
| `POST /api/v1/proposals/{id}/approve` | Aproba **si aplica** pe platforma — vezi mai jos ce se aplica efectiv |
| `POST /api/v1/proposals/{id}/reject` | Respinge; nu atinge nicio platforma |
| `POST /api/v1/campaigns/propose_launch` | Propune lansarea unei campanii Meta noi; nu creeaza nimic pana la aprobare |
| `GET /api/v1/reports/weekly` | Istoricul rapoartelor saptamanale ale clientului |
| `GET /api/v1/reports/weekly/latest` | Cel mai recent raport (`WeeklyReportPayload`) |
| `GET /api/v1/reports/weekly/{week_start}` | Raportul unei saptamani (`YYYY-MM-DD`) |
| `POST /api/v1/reports/weekly/generate` | Genereaza/regenereaza raportul ultimei saptamani incheiate (`?week_end=` optional) |
| `PATCH /api/v1/me/site` | Site-ul clientului din Setari: `target_domain` (salvat ca `https://domeniu`) si `brand_name` |
| `GET /api/v1/integrations` | Starea Search Console si GA4: conectat (doar daca token-ul exista) + proprietatea aleasa |
| `GET /api/v1/integrations/{gsc\|ga4}/auth-url` | URL-ul ecranului de consimtamant Google, cu o stare semnata; 503 fara client OAuth |
| `GET /api/v1/integrations/{gsc\|ga4}/callback` | Unde revine Google: schimba codul pe refresh token (criptat) si redirectioneaza spre site |
| `GET /api/v1/integrations/{gsc\|ga4}/properties` | Proprietatile din contul Google conectat, ca lista de ales |
| `PATCH /api/v1/integrations/{gsc\|ga4}` | Proprietatea aleasa (`sc-domain:...`/URL, respectiv ID-ul numeric GA4) |
| `DELETE /api/v1/integrations/{gsc\|ga4}` | Deconectare: revoca token-ul la Google si il sterge |
| `GET /api/v1/seo/intelligence?days=7\|28\|90` | Trafic (GA4) + pozitii (Search Console) + volume (Keyword Planner) + recomandari, pentru pagina "Trafic & Pozitii" |
| `GET /api/v1/queen/client-message` | Agentul Regina explica clientului, ca un CMO, publicul ideal si ce a propus (vezi mai jos) |
| `POST /api/v1/queen/chat` | Chatul cu Regina: `{"message"}` -> `{"reply", ...}`, deliberat de consiliu (brand + CFO + Tehnician + Researcher) |
| `GET /api/v1/queen/market` | Contextul pietei al Researcher-ului: concurenta, trendul cererii, durerile noi (azi demonstrativ, vezi mai jos) |
| `GET /api/v1/queen/technician` | Raportul Tehnicianului: tracking verde/rosu, viteza pe mobil, veto si reparatii (vezi mai jos) |

#### Agentul Regina: `GET /api/v1/queen/client-message`

Regina (`ppc_agent_server/services/queen_agent.py`) calculeaza determinist
directiva de brand - clientul ideal, reclamele care nu ii vorbesc, unghiul de copy
si targetarea Meta - iar jobul de noapte o transforma in propuneri `UPDATE`
(`jobs/brand_alignment.py`), inainte de Kelly/Thompson. Ruta asta doar o
EXPLICA clientului:

- **LLM-ul doar formuleaza.** Primeste faptele directivei (niciodata acces la
  decizii) si un rol de "Senior AI Chief Marketing Officer". Raspunsul lui e
  respins daca aduce o cifra care nu e in fapte, vorbeste despre bugete sau
  licitari, contine linkuri ori e gol/prea lung.
- **Nu pica niciodata:** fara `HUGGINGFACE_API_KEY`, cand modelul nu raspunde
  sau cand raspunsul e respins, mesajul vine din template-ul intern
  (`source: "template"` + `fallback_reason`).
- Apelul merge prin `router.huggingface.co/v1/chat/completions` (compatibil
  OpenAI, `services/hf_client.py`, doar `httpx`); vechiul
  `api-inference.huggingface.co` nu mai functioneaza.

#### Chatul cu Regina: `POST /api/v1/queen/chat`

Pagina `/cont/regina` din site. Regina nu raspunde direct: isi consulta consiliul
(`services/council.py`, dupa fluxul din `gcpdev/llm-council-skill`, reimplementat):

1. **Faptele** - directiva de brand (clientul ideal) si instantaneul CFO-ului
   (`AdPerformanceRecord` + termenii Google Ads pe 30 de zile: cheltuieli,
   conversii, CPA fata de tinta sau ROAS, plafonul zilnic, propunerile in asteptare).
2. **Decizia, determinista** (`rule_on_question`): ce sustine consiliul si ce taie
   CFO-ul, cu motivul. O idee de brand care costa bani (interese noi, lookalike,
   un canal nou, buget in plus) trece doar pe un cont rentabil; o reclama rentabila
   pe care Regina vrea s-o rescrie devine test A/B, nu se inlocuieste.
3. **Parerile** - strategia de brand si CFO-ul, cerute in paralel, fiecare doar cu
   faptele rolului sau; apoi **sinteza Reginei**, care comunica decizia.

Fiecare text LLM trece prin `check_council_text`: nicio cifra in afara datelor (ale
clientului pot fi repetate, nu "calculate mai departe"), niciun link, nicio actiune
pretinsa ("am marit bugetul"), nicio cheltuiala promisa, nicio garantie. Un membru
respins sau picat e inlocuit cu pozitia lui determinista; fara `HUGGINGFACE_API_KEY`
raspunde consiliul determinist. Fara date (niciun client ideal si sub 5 conversii),
niciun LLM nu e apelat - raspunsul spune ce lipseste, nu da sfaturi generice.

**Psihologia cumparatorului** (`services/cognitive.py`, determinist, in
`BrandStrategyDirective.cognitive_profile`) da argumentului de brand un "de ce":

| Clasificare | Din ce date | Rezultat |
|-------------|-------------|----------|
| Modul de decizie (Kahneman) | cota profilurilor MiroFish deliberative (incredere, informare) in ce aduce contul | Sistemul 1 (<= 40%), Sistemul 2 (>= 60%), mixt |
| Bariera de conversie | profilul care converteste sub 60% din media contului, cu cel putin 20 de click-uri platite | valoare perceputa (pret), incredere, frictiune (urgenta, comoditate), niciuna sau date insuficiente |
| Ruta de persuasiune (ELM) | modul de decizie | centrala (argumente), periferica (imagine, brand, dovada sociala), ambele |

Fiecare reclama primeste si efortul pe care il cere (tehnica sau lunga = Sistemul 2);
nepotrivirea cu publicul ajunge in raspuns ("Publicul tau decide repede, pe intuitie
(Sistemul 1). Reclama X il pune sa gandeasca (Sistemul 2)..."), in faptele LLM-ului
si in brief-ul propunerilor de rescriere (`after.psychology`).

Toate textele LLM au un strat de voce (`services/humanizer.py`, dupa
`blader/humanizer`): consultant senior, fraze foarte scurte alternate cu fraze lungi,
diateza activa, fara scuze, fara formule de chatbot si fara cuvinte-tic (crucial,
esential, dinamic, "in concluzie"...). Stilul nu relaxeaza nicio garda.

#### Tehnicianul (CTO): tracking si viteza, cu drept de veto

Al treilea scaun din consiliu (`services/technician.py`, determinist). Raspunde
de infrastructura de conversie - daca cifrele pe care le judeca ceilalti sunt
adevarate si daca site-ul poate converti traficul platit:

| Verificare | Din ce date | Rosu cand |
|------------|-------------|-----------|
| Tracking-ul conversiilor | serii zilnice pe 30 de zile: conversiile Google Ads (`SearchTermConversion`, cu click-urile zilei) si comenzile/apelurile din webhook-uri (`ConversionEvent`, pe sursa) | conversiile tac de cel putin 3 zile, desi ritmul de dinainte cerea cel putin 3 (Poisson, ~5%) si click-urile au continuat; sau 300+ click-uri fara nicio conversie |
| Viteza pe mobil | ultima masuratoare PageSpeed Insights (strategia mobil), facuta noaptea de agentul SEO/GEO si salvata in `SiteSpeedSample` | LCP peste 4 s, CLS peste 0,25, TBT peste 600 ms sau scor sub 50 (pragurile Google); intre praguri: galben |

Cand si click-urile au scazut, vina nu e a tracking-ului (reclamele livreaza mai
putin) - starea ramane necunoscuta, nu rosie. Fara date, starea e `unknown`, nu
verde. Pixelul Meta si GA4 nu trimit inca serii zilnice in platforma, deci nu se
"verifica": raportul o spune intr-o nota.

**Veto-ul** e calculat inaintea oricarui LLM: tracking picat -> nicio idee care
citeste conversiile (buget, canal nou, teste platite, reclame "care pierd",
cuvinte negative - ar fi luate pe cifre false - si textele noi ale Reginei: un
test A/B fara conversii masurate n-are castigator); daca s-au oprit si comenzile
reale, problema e pe site si reclamele se opresc pana la reparatie. Site lent pe
mobil -> nicio cheltuiala in plus. Excluderile trec. Raspunsul Reginei spune
veto-ul si prima reparatie, oricare ar fi fost intrebarea.

Vocea lui (`ENGINEER_VOICE` din `humanizer.py`): inginer senior, extrem de scurt -
diagnosticul, cauza, reparatia - cu aceleasi interdictii anti-AI ca a consultantului.
Garda consiliului respinge si reparatiile pretinse ("am reparat tag-ul").

Masuratoarea de viteza e un pas al mentenantei de noapte (`speed_check` in
`run_client_maintenance_job`), doar pentru clientii cu domeniu in Setari.
`SEOGEO_PAGESPEED_API_KEY` e optionala (fara ea, cota Google e mica, dar ajunge
pentru o masuratoare pe client pe noapte).

#### Researcher-ul (CSO): contextul pietei

Al patrulea scaun (`services/researcher.py`, determinist): aduce piata, ca
deciziile sa nu se ia doar pe datele interne ale clientului.

| Semnal | Regula |
|--------|--------|
| Activitatea competitorilor | presiune in crestere cand CPC-ul licitatiei urca cu 10%+ SI au intrat concurenti noi sau unul si-a urcat cota de afisari cu 5+ puncte - explica un CPC mai mare care nu vine din cont; relaxare la -10% fara intrari |
| Trendul cererii | ultimele 4 saptamani fata de cele 4 dinainte (+/-10%), fata de anul trecut, plus sezonul (indicele lunar): sezon care porneste = fereastra de oportunitate, sezon care se stinge = fara teste noi |
| Ce cauta piata | temele (durerile) din cautari si recenzii care cresc cu 25%+, din cel putin 20 de mentiuni |

**Azi datele sunt demonstrative** (`services/market_demo.py`, acelasi tipar ca
`intelligence_demo.py`): nu exista inca surse de piata conectate. Sunt deterministe
(seed = brandul clientului + ziua), marcate `is_demo`, cu nume ilustrative
("Concurentul A"). Consiliul le arata in deliberare, cu eticheta "Demonstrativ",
dar nu le trimite la niciun LLM, nu le pune in decizie si nu le spune clientului ca
fapte despre piata lui. Cand se conecteaza o sursa reala (Auction Insights, Keyword
Planner, recenzii), aceleasi reguli dau `CouncilRuling.market_context` - contextul
pietei pentru intrebare, care explica decizia fara s-o schimbe. O intrebare despre
pretul click-ului ("de ce a crescut CPC-ul?") primeste raspunsul din licitatie; fara
date reale de licitatie, consiliul spune ca le lipsesc, nu ghiceste.

**Cautarea pe web (ca Perplexity), reala:** nisa si orasul se scot din cautarile
clientului (`market_focus`: cel mai lung grup de cuvinte repetat in cautari, fara
"pret"/"program"/brand; orasul recunoscut, altfel Romania), apoi doua interogari
DuckDuckGo (`ddgs`, fara cheie): "competitori <nisa> <oras>" si "trenduri <nisa>
Romania <an>". Primele 5 surse distincte (titlu, fragment, site) ajung la LLM-ul
Researcher-ului, care are voie sa formuleze EXCLUSIV din ele: garda respinge orice
cifra din afara lor, linkurile si sfaturile generice ("Silicon Valley", "growth
hacking", "startup"). Cautarile ruleaza in paralel (`asyncio.to_thread`), cu timeout de
8 s; un timeout sau o limita DuckDuckGo nu opreste chatul - Researcher-ul spune ca n-a
mers. Rezultatele se tin minte o zi, in proces. Datele demonstrative (licitatie,
cerere) tot nu ajung la niciun LLM.

Vocea lui (`ANALYST_VOICE` din `humanizer.py`): analist de intelligence comercial -
cota de piata, miscarile competitorilor, ferestrele de oportunitate - asertiv, scurt,
fiecare afirmatie cu cifra ei din fapte, fara speculatii despre intentiile concurentilor.

#### Integrari Google: Search Console si GA4

Clientul isi conecteaza singur conturile din site (`/cont/seo-geo/integrari`),
prin fluxul OAuth standard: site-ul cere `auth-url`, Google il intoarce pe
`callback` cu un cod, serverul il schimba pe un refresh token si il cripteaza pe
`ClientAccount` (`gsc_refresh_token_enc` / `ga4_refresh_token_enc`). Token-ul de
Search Console e acelasi pe care il citeste deja agentul PPC pentru datele
organice ale clientului (`_app_config_for`).

- **Callback-ul nu are sesiunea clientului** (e o redirectionare de browser),
  deci contul vine din starea semnata emisa la `auth-url`: valabila 10 minute,
  legata de cont si de integrare, semnata cu o cheie DERIVATA din
  `JWT_SECRET_KEY` - o stare nu poate trece niciodata drept token de sesiune.
- **Acelasi client OAuth ca agentul** (`PPC_GOOGLE_OAUTH_CLIENT_ID/SECRET`): un
  refresh token Google merge doar cu clientul care l-a emis.
- **Scope-uri minime, doar citire:** `webmasters.readonly` si
  `analytics.readonly`. Fara `business.manage` - acela e drept de administrare.
- Configurarea in Google Cloud e in `.env.example` (redirect URI-uri si API-urile
  de activat). Fara client OAuth, pagina de integrari spune exact ce lipseste.

#### Trafic & Pozitii: `GET /api/v1/seo/intelligence`

Triangularea celor trei surse Google, intr-un singur raspuns
(`SEOIntelligencePayload`): serie de timp zilnica pentru grafic, indicatorii
perioadei fata de cea anterioara, clasamentul cuvintelor si
`ai_recommendations`. Logica e pura, in `seo_geo_agent/services/intelligence.py`;
sursele se aleg in `ppc_agent_server/seo_intelligence.py`:

| Sursa | live cand | altfel |
|---|---|---|
| GA4 (`ppc_agent/search_data/analytics.py`, Data API `runReport`) | token GA4 + proprietate + client OAuth | demo |
| Search Console (`search_console.py`) | token GSC + proprietate + client OAuth | demo |
| Keyword Planner | GSC live **si** `PPC_PROVIDER_MODE=live` | demo langa GSC demo; altfel lipsa |

- **Demo doar pentru ce nu e conectat** (`intelligence_demo.py`: determinist,
  aceeasi zi da aceleasi cifre in orice perioada), marcat in raspuns
  (`is_demo`, `sources[].status`) si in interfata. O sursa conectata care pica
  ramane goala, cu motivul in `data_gaps` - nu e inlocuita cu cifre inventate.
- **Recomandarile sunt reguli, nu parerea unui model** (`recommendations_engine:
  "rules"`), fiecare cu cifrele care au declansat-o in `evidence`: CTR mic la o
  pozitie buna (rescrie title/meta description), cuvinte pe pozitiile 8-20,
  pagina care pierde trafic in GA4, cuvant din top 10 care coboara, engagement
  sub 40%, cerere din Keyword Planner fara nicio afisare, tendinta generala.
  Pragurile sunt pentru 28 de zile si se scaleaza cu perioada.
- Fereastra se termina acum 3 zile: Search Console publica datele finale cu
  intarziere, iar GA4 e aliniat la aceleasi zile.

> **Gap semnalat, nu construit:** niciun endpoint nu creeaza inca `ProposedChange`
> automat dintr-un plan — echivalentul comenzii `propose` din CLI. O extensie
> naturala, in afara listei de cerinte initiale.

#### Lansarea de campanii noi: `POST /api/v1/campaigns/propose_launch`

Nu creeaza nimic in Meta. Valideaza specificatia, verifica plafonul zilnic
(angajamentul TOTAL + bugetul nou) si depune o propunere `CREATE_CAMPAIGN`
`pending`, cu specificatia completa in `after` — exact ce vede omul care aproba.
Obiectivul (`OUTCOME_SALES`/`OUTCOME_LEADS`) si evenimentul implicit vin din
`ClientAccount.objective`, niciodata din cerere.

Payload-urile Meta (functii pure, `ppc_agent/providers/meta_campaign.py`) includ
campurile fara de care v23-v25 refuza crearea: `is_adset_budget_sharing_enabled`
si `special_ad_categories` pe campanie, `targeting_automation.advantage_audience`
pe ad set. Campania, ad set-ul si anuntul pornesc toate `PAUSED`.

La aprobare, `LiveMetaMarketingProvider.launch_campaign` descarca intai
imaginea (validare anti-SSRF, inainte de orice apel Meta), apoi creeaza pe
v25.0: campanie → ad set → imagine → creative → anunt. Daca un pas de
dupa campanie pica, campania se sterge (`DELETE`), iar propunerea ramane
`failed` cu pasul, eroarea exacta de la Meta si rezultatul rollback-ului.
Id-urile create ajung in `execution_result`; o campanie pe care rollback-ul
n-a putut-o sterge apare acolo ca `orphan_campaign_id`.

#### Brief-ul de lansare: agentii SEO/GEO si PPC, inainte de coada

Inainte ca o lansare sa intre in coada, `propose_launch` ii ataseaza un brief
(`ppc_agent/services/launch_brief.py`), salvat in `before` — contextul in care
se ia decizia, langa specificatia din `after`:

| Sectiune | Cine | Ce spune |
|---|---|---|
| Pagina de destinatie | agentul SEO/GEO | aceeasi analiza si verificari ca auditul (`page_from_html` + `run_page_reporters`), plus prezenta pixelului in HTML |
| Faza de invatare | agentul PPC | formula Modulului 3 (~50 evenimente in 7 zile): iese sau nu, CPA maxim pentru iesire, bugetul necesar; capacitatea bugetului (`budget_strategy`) |
| Pozitia in cont | agentul PPC | Kelly: plafonul pe care il justifica istoricul; Thompson: setul de reclame cel mai probabil bun — tinta de batut |
| Semnale pentru mesaj | Modulul 1 | interogarile GSC, ideile Keyword Planner, ratingul si sentimentul GBP |

Agentul PPC **interpreteaza** ce raporteaza agentul SEO/GEO: auditul e scris
pentru motoarele de cautare, iar o pagina de reclama e judecata de vizitator.
Doar pagina stricata, eroarea de server, raspunsul lent, lipsa H1 si continutul
subtire devin avertismente; restul (meta description, canonical, `noindex`...)
apare separat, ca semnal SEO. `noindex` e normal pe paginile de reclama.

**Blocheaza doar ce e obiectiv:** pagina 404/410 sau o adresa care nu e publica
— raspuns 422, propunerea nu se salveaza. Tot restul e avertisment: Learning
Limited, pagina lenta, pixel negasit, rating GBP slab. Un site care opreste
crawler-ul nostru nu dovedeste o pagina moarta, deci nici el nu blocheaza.

Ce NU face brief-ul, deliberat:

- **Campania noua nu intra ca brat in Thompson.** Fara date, priorul Beta(1,1)
  i-ar da o rata de conversie medie de 50%, deci ar "castiga" aproape mereu —
  un artefact statistic. Thompson ruleaza pe ce exista si da tinta de batut.
- **Markov nu intra in decizie.** Atribuie conversii pe parcursuri reale, iar o
  campanie care nu exista n-are niciunul. Brief-ul o spune explicit.
- **Fara istoric, Kelly si Thompson tac.** Prima campanie a unui cont e buget de
  explorare; cele doua intra in calcul dupa primele conversii.

O sursa indisponibila (GSC neconectat, Business Profile neaprobat inca) apare
ca atare si nu blocheaza.

#### Raportul saptamanal: "data asset as code", fara bruin sau dbt

`ppc_agent/services/reporting/` imprumuta arhitectura, nu uneltele: trei straturi,
fiecare o functie pura peste iesirea celui dinainte, testabil singur.

| Strat | Modul | Ce face |
|---|---|---|
| RAW | `extractors.py` | zilele de la Google Ads si Meta (saptamana raportata + cea dinainte) si deciziile executate |
| Agregat | `transformers.py` | Pandas: totaluri, CPA, ROAS, evolutia fata de saptamana anterioara |
| Serving | `serving.py` + `summary.py` | `WeeklyReportPayload`, gata de legat in Recharts/Tremor, plus rezumatul executiv |

Seriile zilnice vin din `daily_campaign_performance` — GAQL cu `segments.date`
la Google, Insights cu `time_increment=1` la Meta. Furnizorii **mock** nu o au,
deliberat: nu fabricam un trend zilnic dintr-un agregat. In modul mock raportul
are graficul gol si spune de ce, in `data_gaps`.

Reguli care tin raportul cinstit:

- **Banii se aduna in bani intregi**, nu in float; CPA si ROAS se calculeaza
  la final, din sume exacte.
- **`null`, nu zero, unde valoarea nu exista:** CPA fara conversii, ROAS la un
  obiectiv de lead-uri, evolutia fata de o saptamana cu zero. Recharts lasa un
  gol la `null` — nu deseneaza un zero care minte.
- **Zilele fara livrare apar cu zero**, ca graficul sa nu uneasca doua puncte
  departate; dar cand NICIO platforma n-a raspuns, graficul e gol, nu plin de zero.
- **Rezumatul AI e verificat:** modelul primeste faptele cu cifrele gata
  calculate, iar orice numar din textul lui trebuie sa existe in ele. Altfel
  ramane rezumatul din cifre (`summary_source: "template"`) si motivul apare in
  `data_gaps`. Limita: verificarea confirma ca un numar exista, nu ca sta langa
  eticheta corecta.
- **Deciziile simulate nu sunt prezentate ca aplicate.** `POST
  /api/v1/proposals/{id}/execute` (agentie) marcheaza acum `execution_result =
  {"simulated": true}`, iar jurnalul le arata cu `applied: false`.

Raportul se salveaza in `WeeklyReport` (un rand pe client si saptamana;
regenerarea il inlocuieste) si se genereaza automat lunea la 06:00, de cronul
ARQ `weekly_reports`, pentru clientii agentiilor active.

#### Ce se aplica efectiv la `/approve`

Doar **Meta**, si doar pe obiecte cu id real: `meta_campaign/{id}`,
`meta_ad_set/{id}`, `meta_ad/{id}` (`PAUSE`, plus `UPDATE` de buget pe campanie
si set). Se traduc in `POST https://graph.facebook.com/v25.0/{id}` cu
`status=PAUSED`, respectiv `daily_budget` in unitatea minima a monedei
(`PPC_META_CURRENCY`).

Restul primeste **409 si ramane `pending`**, fiecare cu motivul lui:

- **Google Ads / TikTok** — `GoogleAdsProvider` si `TikTokAdsProvider` sunt
  contracte de CITIRE, fara nicio metoda de mutatie. Aici cad si propunerile
  evaluatorului autonom (`ppc_keyword`) si cele din unealta MCP
  (`keyword_budget`): resursa lor e un **termen de cautare**, nu un id de
  obiect, si nu are ce cauta la Graph API.
- **`ad_set_group/...`** (consolidarile de lichiditate) — id sintetizat de noi,
  nu exista in contul Meta.
- **mod `mock`, sau cont Meta neconectat** — nu aplicam nimic si nu ne prefacem
  ca am aplicat.

Cand platforma e intrebata si refuza (token expirat, obiect sters, buget sub
minimul Meta), raspunsul e **502** si propunerea ramane `failed` cu mesajul
**exact** al Meta in `error_message`. Distinctia conteaza in interfata: un 409
se reincearca dupa ce se schimba ceva la noi, un 502 dupa ce se schimba ceva la
ei.

Mapare eroare -> HTTP (Starlette, pe `__mro__`): `SetupRequiredError`→503,
`SpendLimitExceeded`→409, `ApprovalRequiredError`→403, `CopywriterError`
(si subclase)→422, `PpcAgentError`→500 (fallback generic).

### De la SQLite la PostgreSQL

| | SQLite (implicit) | PostgreSQL |
|---|---|---|
| Instalare | niciuna | `docker compose -f docker-compose.dev.yml up -d` |
| `DATABASE_URL` | necompletat | `postgresql+psycopg://ppc_agent:ppc_agent_dev@localhost:5432/ppc_agent` |
| Migratii | `alembic upgrade head` | identic — acelasi Alembic, alt dialect |

### De la coada in proces la ARQ+Redis

| | `InlineJobQueue` (implicit) | `ArqJobQueue` |
|---|---|---|
| Instalare | niciuna | `docker compose -f docker-compose.dev.yml up -d` + `REDIS_URL=redis://:redis_dev@localhost:6379/0` |
| Executie | sincron, in procesul serverului | proces worker separat: `arq ppc_agent_server.jobs.worker.WorkerSettings` |
| Contract API | identic (`POST` -> `task_id`, `GET` -> stare) | identic — comutare fara nicio schimbare in router-e |

Comutarea e automata, dupa `REDIS_URL` — niciun cod de apelat diferit.

Mentenanta de noapte (cron ARQ la 03:00) face fan-out: programeaza cate un job
`run_client_maintenance_job` per client, fiecare cu timeout-ul lui (10 minute),
fara reincercari oarbe, cu `_job_id` pe zi - pornit de doua ori, cron-ul nu
dubleaza nimic. Un client lent nu-i mai intarzie pe ceilalti.

### Productie cu Docker

`docker-compose.yml` porneste toata stiva: `site` (Next.js standalone), `api`
(ppc_agent_server), `worker` (ARQ), `seo-geo`, `postgres`, `redis`, plus `migrate`
(`alembic upgrade head`, o data per pornire). Imaginile: `Dockerfile.backend`
(una singura pentru api/worker/seo-geo; Python slim, torch doar CPU, fara
Playwright) si `Dockerfile.frontend` (build `output: "standalone"`).

```bash
cp .env.example .env      # JWT_SECRET_KEY, SECRETS_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
docker compose up -d --build
# o singura data: agentia (tenant-ul), apoi AGENCY_TENANT_ID=<id> in .env si
# docker compose up -d api
docker compose run --rm api python -c "from sqlmodel import Session; from ppc_agent_server.db import get_engine; from ppc_agent_server.auth import create_tenant; s = Session(get_engine()); t, k = create_tenant(s, 'Agentia Mea SRL'); print(t.id, k)"
```

Securitate:

- Postgres si Redis **nu au porturi publicate**; traiesc pe reteaua `data`
  (`internal: true`, fara iesire in internet), impreuna doar cu `api` si `worker`.
  Redis cere parola. Parolele lipsa opresc pornirea (`${VAR:?}`).
- Containerele aplicatiei ruleaza ca utilizator fara privilegii, cu radacina
  read-only, fara capabilitati Linux si `no-new-privileges`.
- Porturile 3000/8000/8001 asculta implicit doar pe `127.0.0.1` (`BIND_ADDRESS`):
  in productie, in fata lor sta un reverse proxy cu TLS. Seteaza atunci
  `FORWARDED_ALLOW_IPS` la IP-ul proxy-ului, ca limitarea de login sa vada IP-ul
  real al clientului.
- `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_SEO_GEO_API_URL` intra in build-ul site-ului
  (sunt publice, ajung in browser) - adresele API-urilor asa cum le vede clientul.

### Scutul SSRF si limitarea cererilor

- **SSRF.** Orice crawl (auditul SEO si crawler-ul PPC care citeste noaptea
  domeniul clientului) trece prin `seo_geo_agent/audit/safe_transport.py`: DNS-ul
  il rezolva transportul, la FIECARE cerere (inclusiv fiecare redirect, sitemap si
  link); daca DNS-ul pica sau oricare adresa nu e publica (privata, loopback,
  link-local si metadata cloud `169.254.169.254`, CGNAT `100.64.0.0/10`, rezervata,
  IPv4 ascuns in IPv6), cererea se refuza; altfel conexiunea merge la IP-ul
  verificat (antetul `Host` si TLS pastreaza numele), deci nu mai exista o a doua
  rezolvare de otravit (DNS rebinding). Setarile refuza si un `target_domain` intern.
- **Aprobari.** `POST /proposals/{id}/approve` rezerva propunerea atomic
  (`UPDATE ... WHERE status='pending'`) inainte de apelul catre Meta: un dublu
  click nu mai aplica de doua ori. Plafonul de cheltuiala numara si propunerile
  aflate in curs de aplicare (`approved`).
- **Limitari** (`ppc_agent_server/rate_limit.py`, in memorie): login - 30 de
  incercari/minut pe IP si 5 parole gresite/15 minute pe email (numarate inainte
  de Argon2); chatul Reginei - 6 mesaje/minut si 60/ora per client. Peste: 429 cu
  `Retry-After`. Memoria e per proces: cu mai multi workeri uvicorn, limita se
  inmulteste cu numarul lor.

### Teste server

```powershell
.venv\Scripts\python.exe -m pytest tests_server
.venv\Scripts\python.exe -m mypy --strict ppc_agent_server
```

100% offline — SQLite in-memory, `InlineJobQueue`, zero Redis/Postgres reale
(la fel ca restul proiectului). `ruff check` (fara argument de cale) acopera
deja tot, inclusiv `ppc_agent_server/` si `tests_server/`.

## Date de cautare organica (`ppc_agent/search_data/`)

Partea organica a platformei, pe surse gratuite si oficiale. **Niciun API
platit in tot lantul de date** — nu exista cheie de cumparat si niciun vendor
care sa schimbe preturile sub noi.

| sursa | ce da | cost |
| --- | --- | --- |
| Google Search Console | pozitii, afisari si click-uri REALE, doar site propriu | gratuit |
| Google Ads API | volume de cautare + termenii reali care au convertit | gratuit, contul clientului |
| OpenSERP (self-hosted) | pozitii pe cuvinte arbitrare si pentru concurenti | gratuit, local |
| Common Crawl | autoritate de domeniu pentru orice site | gratuit |

Peste ele stau cele doua analize care nu se pot face intr-un tool de SEO pur —
el are index, dar nu stie cat platesti si ce converteste (`insights.py`):
**canibalizare** (platim pentru termeni pe care ii detinem deja in top 3
organic) si **oportunitati** (termeni care convertesc platit, unde organic
lipsim). Sortate dupa bani, nu dupa volum estimat.

### OpenSERP: necesar pentru urmarirea pozitiilor

Verificarea pozitiilor pe cuvinte pe care **inca nu le ranchezi** e singurul
lucru pe care Search Console nu-l poate da (el arata doar interogari pentru
care site-ul a fost deja afisat). Pentru asta ruleaza o instanta locala de
[OpenSERP](https://github.com/karust/openserp):

```powershell
docker run --rm -p 127.0.0.1:7000:7000 karust/openserp:latest serve -a 0.0.0.0 -p 7000
```

Fara ea, verificarile raporteaza `unavailable` cu un mesaj explicit, iar restul
platformei merge neschimbat — nimic nu crapa, doar lipseste acea functie.

**De stiut inainte sa te bazezi pe ea:** OpenSERP conduce un browser headless
impotriva Google. E acelasi scraping pe care un serviciu platit il face in
locul tau, mutat pe infrastructura ta — deci CAPTCHA-urile, blocarile de IP si
stricaciunile la schimbarile de layout devin problema noastra. Codul trateaza
asta explicit: `blocked` e o stare separata de `error` (raspunsul corect la o
provocare anti-bot e oprirea, nu reincercarea), iar concurenta e plafonata
deliberat la 2 cereri simultane. Pentru volume mari, alternativa onesta ramane
un furnizor platit de SERP — interfata `SerpProvider` e un `Protocol` exact ca
sa poata fi schimbat fara modificari mai sus.

## Agent SEO+GEO (separat)

`seo_geo_agent/` e un al doilea agent, complet separat de `ppc_agent`/
`ppc_agent_server` — propriul FastAPI app, propriul port, propriile dependinte
(`requirements-seo-geo.txt`, fara SQLModel/Alembic/Redis — nu are baza de date
proprie). Doua moduri de lucru, deliberat separate:

**1. Audit determinist (`seo_geo_agent/audit/`) — sursa de adevar.** Un crawl
real al domeniului, din care functii pure calculeaza probleme verificabile,
fiecare cu dovada ei: URL-ul afectat si valorile masurate. Nu e o parere a unui
model de limbaj.

Arhitectura si regulile sunt o portare fidela a
[`every-app/open-seo`](https://github.com/every-app/open-seo) (TypeScript pe
Cloudflare Workers) in Python/asyncio: **aceleasi id-uri de probleme**
(kebab-case, engleza — `missing-title`, `broken-internal-link`,
`duplicate-content`…), **aceleasi severitati** si **aceleasi praguri numerice**
(titlu 10–60 caractere, meta description 70–160, continut subtire sub 150 de
cuvinte, raspuns lent peste 1500 ms, pagina adanca de la 5 clickuri). Textele
sunt in romana, ca restul produsului. Vezi `seo_geo_agent/audit/issues.py`
pentru registrul complet si `audit/page_reporters.py` pentru praguri.

| modul | ce face |
| --- | --- |
| `url_policy.py` | validarea URL-ului de start, anti-SSRF (refuza IP-uri private/interne) |
| `robots.py` | robots.txt cu wildcard-uri `*`/`$` si grupuri pe user-agent |
| `discovery.py` | sitemap.xml + index-uri imbricate |
| `crawler.py` | descarcarea paginilor, clasificare oneasta: `ok`/`blocked`/`rate_limited`/`error` |
| `page_analyzer.py` | extragerea datelor SEO din HTML (tokenizer in flux, nu DOM) |
| `page_reporters.py` | verificari pure per pagina |
| `multipage.py` | duplicate, lanturi/bucle de redirect, linkuri rupte, pagini orfane |
| `geo_reporters.py` | citabilitate in motoare generative (vezi mai jos) |
| `scoring.py` | scorurile SEO/GEO, ca rata de trecere ponderata peste verificari |

Partea **GEO** e adaugirea fata de `open-seo` (care masoara vizibilitatea AI din
afara site-ului, prin DataForSEO). Aici masuram ce controleaza site-ul si se
poate verifica din crawl, cu aceeasi disciplina: crawler-e AI blocate din
robots.txt (GPTBot, ClaudeBot, PerplexityBot, Google-Extended), continut care
apare doar dupa rularea JavaScript, JSON-LD lipsa, schema `Organization`, cat de
des apare brandul explicit in text, subtitluri formulate ca intrebari, lungimea
medie a propozitiilor, semnale de autor/data, `/llms.txt`.

Trei endpoint-uri, ca in original (start / status / results) — un crawl nu
incape intr-un request sincron:

```
POST /api/v1/seo-geo/audit                  -> 202 {audit_id}
GET  /api/v1/seo-geo/audit/{id}             -> stare + progres
GET  /api/v1/seo-geo/audit/{id}/results     -> raportul complet
GET  /api/v1/seo-geo/audit/latest           -> ultimul raport terminat (pagina de ansamblu)
```

Auditul traieste in memoria procesului (`audit/store.py`) — agentul trebuie
rulat cu **un singur worker uvicorn**, altfel cererea de stare poate ajunge in
alt proces decat cel care ruleaza auditul.

**2. Analiza prin LLM (`POST /api/v1/seo-geo/analyze`)** — ramane disponibila,
ca strat optional PESTE datele masurate: primeste un domeniu (+ optional
rapoarte brute Ahrefs/Semrush/GSC) si returneaza `seo_score`/`geo_score` plus
sugestii actionabile (vezi `prompts.py`). In UI e al treilea tab, marcat
explicit ca interpretare, nu ca masuratoare.

Autentificare (pentru ambele): **acelasi token JWT** emis de
`POST /api/v1/login` din `ppc_agent_server` (secret comun — `JWT_SECRET_KEY`,
fara prefix, in acelasi `.env`) — un client deja autentificat pe site nu are
nevoie de un al doilea login. Fara acces la baza de date a `ppc_agent_server`:
doar semnatura + expirarea token-ului sunt verificate.

```powershell
pip install -r requirements-seo-geo.txt
.venv\Scripts\python.exe -m uvicorn seo_geo_agent.app:app --reload --port 8001
```

Auditul functioneaza imediat, fara nicio configurare (nu foloseste LLM).
Pentru analiza LLM: implicit (`SEOGEO_PROVIDER_MODE=mock`) raspunde determinist,
fara Ollama pornit; pentru raspunsuri reale, `SEOGEO_PROVIDER_MODE=live` +
Ollama local (vezi [client LLM (Ollama local)](#client-llm-live-ollama-local) —
acelasi principiu, alt model implicit, vezi `.env.example`).

### Teste seo_geo_agent

```powershell
.venv\Scripts\python.exe -m pytest tests_seo_geo
.venv\Scripts\python.exe -m mypy --strict seo_geo_agent
```

100% offline — `MockLLMClient` pentru analiza si `httpx.MockTransport` pentru
audit (`test_audit_service.py` ruleaza intreg motorul pe un site fals: robots,
sitemap, linkuri, pagini rupte), zero retea reala. `ruff check` acopera deja
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
docker-compose.yml      stiva de productie (site, api, worker, seo-geo, Postgres, Redis)
docker-compose.dev.yml  Postgres+Redis pentru dezvoltare locala (doar pe 127.0.0.1)
Dockerfile.backend      imaginea api/worker/seo-geo (slim, fara Playwright)
Dockerfile.frontend     imaginea site-ului (Next.js standalone)
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
