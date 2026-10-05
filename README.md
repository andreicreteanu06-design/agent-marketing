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
> logica e testabila offline. **Google Ads, Meta Ads, TikTok Ads si OpenAI Ads
> (ChatGPT) au clienti `live` reali** - citire, iar prin server si schimbarile
> aprobate de om (vezi [Integrare live](#integrare-live-googlemetatiktok-ads)),
> la fel ca [clientul LLM (Ollama local)](#client-llm-live-ollama-local).
> `execute` din CLI ramane **intotdeauna simulat** (`applied=False`); scrierea
> reala trece doar prin poarta de aprobare a serverului. Modulul 1 e complet `live`
> — crawler (peste motorul de audit din `seo_geo_agent`), Search Console, Keyword
> Planner si Business Profile. Fish Speech/Flick (Modulul 5) raman stub-uri.

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
| `live` | Clientul LLM (Ollama) si Google/Meta/TikTok/ChatGPT **Ads** sunt functionale — vezi [Integrare live](#integrare-live-googlemetatiktok-ads). GSC/GBP/Keyword Planner/Fish Speech/Flick raman stub-uri care ridica `SetupRequiredError`. |

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
  contului fata de pragul de rentabilitate: `win_prob = r/(r+1)`, `roas_odds = r - 1`.
  Venitul nu trece de comenzile reale ale magazinului (`revenue_cap`), iar fara ele,
  cu vanzari pe mai multe platforme, plafonul nu creste (`allow_growth=False`). Multiplicatorul
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
| implementare `live` | `live/*.py` | Toate reale. Google/Meta/TikTok/ChatGPT **Ads** (citire + scriere prin server), crawler (peste `seo_geo_agent.audit`), Search Console, Keyword Planner, Business Profile. |

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

`LiveGoogleAdsProvider`/`LiveMetaMarketingProvider`/`LiveTikTokAdsProvider`/
`LiveChatGptAdsProvider` (`ppc_agent/providers/live/{google_ads,meta,tiktok,chatgpt_ads}.py`)
citesc date reale de performanta si aplica schimbarile aprobate direct prin REST (`httpx`), acelasi pattern ca `LiveLLMClient` mai
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

# TikTok - token din TikTok for Business developer portal (cu drept si pe Events API)
PPC_TIKTOK_ACCESS_TOKEN=
PPC_TIKTOK_ADVERTISER_ID=

# ChatGPT - cheia Ads API a unui cont OpenAI Ads (acces de partener)
PPC_CHATGPT_ADS_API_KEY=
```

Per client, din setari (agentia, `PATCH /api/v1/clients/{id}`): `google_ads_customer_id`,
`google_ads_conversion_action_id` (o actiune de tip "import din click-uri"),
`tiktok_advertiser_id`, `tiktok_pixel_code`, `chatgpt_pixel_id`. Cheile, criptate, din
contul clientului (`PATCH /api/v1/me/credentials`).

**Ce trebuie sa trimita site-ul cu fiecare comanda** (webhook-ul `custom_web`, sau
campuri personalizate in comanda Gomag): id-urile de click prinse din URL la intrare
si pastrate in cookie - `gclid`/`gbraid`/`wbraid` (Google), `ttclid` si cookie-ul
`_ttp` (TikTok), `oppref` (ChatGPT), `fbc`/`fbp` (Meta) - si `marketing_consent`
din bannerul de cookie-uri (`false` = conversia nu pleaca nicaieri). Pixelii din
browser trimit acelasi id de eveniment ca serverul (`event_id`), ca platformele sa nu
numere comanda de doua ori. Testare: `TIKTOK_EVENTS_TEST_CODE` (Events Manager),
`CHATGPT_CONVERSIONS_VALIDATE_ONLY=true` (OpenAI verifica, nu salveaza).

Obtinerea fiecarui credential e un proces extern la platforma respectiva, in
afara scopului acestui README — vezi documentatia oficiala: [Google Ads API —
get started](https://developers.google.com/google-ads/api/docs/get-started/introduction),
[Meta Marketing API — access tokens](https://developers.facebook.com/docs/marketing-apis/overview/authentication),
[TikTok for Business — authentication](https://business-api.tiktok.com/portal/docs).

### Ce citeste si ce aplica fiecare platforma

| platforma | citeste noaptea | aplica la `/approve` | conversii de pe server |
| --- | --- | --- | --- |
| Meta | seturi, bugete, invatare, anunturi | buget, pauza, lansare | Conversions API (`meta_pixel_id`) |
| Google Ads | campanii, bugetul campaniei, invatare | buget, pauza, cuvinte negative | import din click-uri (`google_ads_conversion_action_id`) |
| TikTok | grupuri, bugetul grupului, valoarea comenzilor | buget, pauza grup, pauza anunt | Events API (`tiktok_pixel_code`) |
| ChatGPT (OpenAI Ads) | campanii, bugetul campaniei, vanzari atribuite | buget, pauza | Conversions API (`chatgpt_pixel_id` + cheia de conversii) |

- **Pasii de buget** sunt aceiasi peste tot: cel mult 20% pe noapte de la bugetul
  de acum (un salt mare reporneste invatarea algoritmului). Nu se ating: un buget
  Google **partajat** cu alte campanii, unul pe o perioada, o campanie Google in
  invatare, un grup TikTok cu buget pe campanie sau pe viata, o campanie ChatGPT cu
  buget pe viata. Daca TikTok nu da bugetele, nimic din TikTok nu se muta in noaptea
  aceea.
- **Cuvintele negative** Google merg intr-o lista a contului (`AC Media - cuvinte
  negative`), atasata tuturor campaniilor de cautare active - o data, fara dubluri.
- **Moneda**: inainte de orice schimbare pe Google, TikTok sau ChatGPT, moneda
  contului se citeste din platforma; alta decat leul = 409, nimic nu pleaca.
- **Venitul lipsa**: TikTok da valoarea comenzilor dintr-un raport separat
  (`complete_payment` x `value_per_complete_payment`); daca il refuza, ca si la
  Google fara urmarirea valorii, vanzarile valoreaza cosul mediu al comenzilor
  raportate cu valoare (de la 5 comenzi), altfel `default_lead_value` - nu 0. Cu
  venit 0, Kelly ar fi taiat bugetul intregului cont.
- **Vanzari numarate de doua ori**: fiecare platforma isi atribuie vanzarile ei.
  Cand webhook-ul magazinului acopera ultimele 30 de zile, venitul platformelor e
  plafonat la comenzile reale (si la Kelly, si la CFO). Fara el, cand mai multe
  platforme raporteaza vanzari, Kelly poate taia, dar nu creste plafonul, iar CFO-ul
  o spune in nota lui.
- **Parcursuri de conversie (`conversion_paths`)**: niciuna dintre platforme nu
  expune simplu parcursuri multi-touch. Fallback: un singur touchpoint per conversie,
  plafonat la 500/brat - atribuirea Markov ramane valida, dar fara semnal multi-touch.
- **Netestat pe conturi reale**: Google, TikTok si ChatGPT sunt verificate pe
  raspunsuri simulate (`httpx.MockTransport`), scrise dupa documentatia oficiala.
  Prima rulare cu chei reale: doar citire, ca la pilotul Meta.

## ChatGPT (OpenAI Ads)

`ppc_agent/providers/live/chatgpt_ads.py`, scris dupa documentatia publica
([developers.openai.com/ads](https://developers.openai.com/ads)). Accesul la API il
dau partenerii aprobati de OpenAI; o cheie Ads API e legata de **un** cont de reclame
(`chatgpt_ads_api_key` in setarile clientului, sau `PPC_CHATGPT_ADS_API_KEY`).

- Bratele planului sunt **campaniile** (bugetul sta pe campanie,
  `daily_spend_limit_micros`). Cheltuiala si click-urile vin din
  `/ad_account/insights`, conversiile si vanzarile atribuite din
  `/conversions/insights`.
- Conversiile pleaca prin Conversions API (`bzr.openai.com/v1/events`) cu o cheie
  **separata** (`chatgpt_conversions_key`, criptata), pixelul `chatgpt_pixel_id` si
  `oppref`-ul de pe site. Doar comenzi (`order_created`) si lead-uri
  (`lead_created`): OpenAI nu are evenimente pentru apeluri.
- In modul `mock` ChatGPT nu exista (n-are date simulate): planul de test ramane pe
  Google, TikTok si Meta.
- De verificat pe primul cont: documentatia nu spune in ce unitate e `spend` din
  insights - aici e citit in moneda contului.
- Perplexity nu are reclame (a renuntat in februarie 2026).

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
| `OLLAMA_HOST` | `http://localhost:11434` | Sistemul 2: modelul LOCAL care scrie tot textul Reginei si al consiliului (datele nu parasesc masina); gol -> template-uri |
| `OLLAMA_MODEL` | `llama3` | Modelul Ollama (acelasi ca `PPC_LLM_MODEL`: un singur `ollama pull`); accepta si `ollama/<tag>` |
| `JEV_API_KEY` | necompletat -> reguli fixe (CCO: 503) | Sistemul 1: Jev (TypeSafe AI) noteaza RICE-ul CPO-ului, filtreaza fragmentele web ale Researcher-ului si judeca textul si vocea creativelor (CCO) |
| `JEV_URL` / `JEV_MODEL` | necompletat -> TypeSafe, `jev-latest` | Un gateway cu acelasi protocol, ex. OpenCode Zen: `https://opencode.ai/zen/v1/systemone` cu `jev-1.13-free` (gratuit temporar) si cheia OpenCode in `JEV_API_KEY`; doar `https://` |

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
| `GET /api/v1/proposals/blocked` | Propunerile oprite de consiliu in tura de noapte, cu motivul (`error_message`) |
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
| `POST /api/v1/queen/chat` | Chatul cu Regina: `{"message"}` -> `{"reply", ...}`, deliberat de consiliu (brand + CFO + Tehnician + Researcher + CPO); cu `Accept: text/event-stream`, in flux (SSE, vezi mai jos) |
| `GET /api/v1/queen/market` | Contextul pietei al Researcher-ului: trendul cererii din Google Trends si cautarea pe web, reale (vezi mai jos) |
| `GET /api/v1/queen/technician` | Raportul Tehnicianului: tracking verde/rosu, viteza pe mobil (cu CrUX), auditul tehnic SEO/GEO, veto si reparatii (vezi mai jos) |

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
- **Nu pica niciodata:** fara Ollama (`OLLAMA_HOST` gol), cand modelul nu
  raspunde sau cand raspunsul e respins, mesajul vine din template-ul intern
  (`source: "template"` + `fallback_reason`). Un server Ollama oprit se tine minte
  30 de secunde: apelurile urmatoare cad direct pe template, fara sa astepte.
- Modelul e local (`POST {OLLAMA_HOST}/api/chat`, `services/llm_client.py`, doar
  `httpx`): faptele clientului nu parasesc masina.
- **Traficul (GA4) si pozitiile organice** (`services/organic_context.py`), cand
  GA4/Search Console sunt conectate: sesiunile pe canal, ultimele 28 de zile fata de
  cele 28 dinainte (*Paid Social* = Meta, *Organic Search* = Google), click-urile si
  pozitia medie din Search Console si pozitiile urmarite in SERP. Corelarea e
  determinista: Meta -10% si organic +10% -> "o parte din cerere pare sa vina acum pe
  organic"; scad amandoua -> cererea/sezonul; scade doar Meta -> campaniile. Sub 50 de
  sesiuni pe canal nu se judeca. Regina o spune ca pe o corelare, nu ca pe o cauza.

#### Arhitectura hibrida: Sistemul 1 (Jev) si Sistemul 2 (Ollama)

`services/llm_client.py` - `LLMRouter` trimite fiecare sarcina la sistemul ei:

| Sarcina | Sistem | Unde se foloseste |
|---------|--------|-------------------|
| `generate` -> `generate_text_local()` / `stream_text_local()` | Ollama, local | Mesajul CMO si sinteza Reginei (in flux, in chat) - singurul text al consiliului scris de model |
| `score` -> `jev_score()` | Jev | CPO-ul: impactul si efortul fiecarei mutari RICE (o cerere pentru toate) |
| `verify` -> `jev_verify()` | Jev | Researcher-ul: "e fragmentul web despre nisa clientului?" (o cerere pe fragment, in paralel) |
| `classify` -> `jev_classify()` | Jev | Disponibil (Choice); rutarea intrebarilor ramane deocamdata pe reguli |

Jev (`POST https://api.typesafe.ai/v1/systemone`) nu genereaza text: intoarce
raspunsuri tipizate (Choice/Score/Noul) cu probabilitati si `confidence`. Dupa
documentatia lui: intrebarile sunt in engleza (continutul clientului sta in
`state`, in romana), aritmetica ramane in cod (un Score alege un NIVEL, valoarea si
formula RICE le da codul), iar sub `confidence` 0,5 raspunsul nu se foloseste.
Fara `JEV_API_KEY`, cand Jev pica sau nu e sigur, raman regulile fixe: estimarile
RICE din tabel, toate fragmentele web. Decizia consiliului nu depinde de niciun model.

In Docker, doar containerul `api` ajunge la Ollama de pe host
(`host.docker.internal`, vezi comentariile din `docker-compose.yml`).

**Ollama in flux, cu circuit-breaker pe primul token.** Toate generarile merg cu
`"stream": true`: cat timp vin tokeni, generarea nu mai are termen de raspuns (pe CPU,
450 de tokeni pot dura minute; plasa e de 300 s). Circuit-breaker-ul sare doar cand
Ollama nu accepta conexiunea sau nu trimite niciun token in
`OLLAMA_FIRST_TOKEN_TIMEOUT` secunde (180) - atunci serverul intra 30 s in pauza si
raspunde varianta determinista. Pe CPU, sinteza consiliului (~2-3k tokeni de prompt)
porneste abia dupa ce modelul citeste tot promptul: ~45 s cu
Qwen2.5-1.5B pe 8 nuclee (180 s lasa loc pentru un CPU ocupat si prompturi mai lungi);
in chat, fluxul SSE arata intre timp etapele si secundele
scurse. Generarile catre acelasi server trec pe rand (`OLLAMA_MAX_PARALLEL`, 1 pe CPU),
deci termenul primului token masoara modelul, nu coada. `OLLAMA_KEEP_ALIVE` (30m) tine
modelul incarcat intre conversatii: reincarcarea lui pe CPU mai adauga ~10 s.

**Modele mici pentru CPU** (`python -m ppc_agent_server.hf_manager`): aduce de pe
Hugging Face un GGUF cuantizat Q4_K_M (`huggingface_hub`, din cache intai - a doua
rulare nu descarca nimic), il urca in Ollama ca blob si creeaza modelul
(`/api/create`) doar pe CPU (`num_gpu 0` - pe un GPU integrat, backend-ul GPU al
Ollama a scos text fara sens cu Qwen2.5; `--allow-gpu` il lasa sa decida) si cu
context de 8192 de tokeni (loc larg pentru sinteza consiliului), apoi il masoara pe un
prompt de marimea celor din consiliu:

```
python -m ppc_agent_server.hf_manager models      # presetari, licente, marimi
python -m ppc_agent_server.hf_manager install     # implicit qwen2.5-1.5b (Apache-2.0, 1,1 GB)
python -m ppc_agent_server.hf_manager benchmark   # primul token si durata, pe masina ta
python -m ppc_agent_server.hf_manager cache       # ce e in cache-ul Hugging Face
```

Apoi `OLLAMA_MODEL=qwen2.5-1.5b-q4km` in `.env`. Pe CPU, primul token depinde mai
ales de lungimea promptului (sinteza consiliului, ~2-3k tokeni), nu de raspuns: de
aceea `benchmark` masoara, nu promite - implicit pe un prompt de marimea sintezei
(7000 de caractere), cu termenul circuit-breaker-ului (180 s). Masurat pe masina de
dezvoltare (8 nuclee, doar CPU): primul token in ~42-47 s, raspunsul intreg in ~70-90 s.
Qwen2.5-3B are licenta de cercetare (fara uz
comercial) si se instaleaza doar cu `--allow-noncommercial`; Gemma 3 4B scrie cea
mai buna romana dintre cele mici, dar e de ~2,5 ori mai lent decat 1.5B.
TimesFM (prognoza din CLI) se incarca acum din cache fara nicio cerere in retea,
cand greutatile exista deja; embeddings-urile agentului SEO/GEO sunt apeluri la
Inference API (nimic descarcat local).

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
3. **Pozitiile membrilor** (Data-to-Text) - Strategul, CFO-ul, Tehnicianul,
   Researcher-ul si CPO-ul NU scriu cu un model: fiecare pozitie e un text scurt calculat
   din datele rolului (garzile Python; Jev pentru mutarile CPO-ului si fragmentele web),
   gata in cateva milisecunde. Pe CPU, cinci pareri LLM ar fi adaugat minute de asteptare
   fara nicio informatie in plus fata de date.
4. **Runda de replici** - disputele pe care decizia le-a transat (`CouncilRuling.conflicts`):
   CFO-ul taie o idee de brand care cere bani, veto-ul Tehnicianului opreste ce ar fi
   trecut, Researcher-ul vede o fereastra in piata cand CFO-ul taie bugetul, CPO-ul da
   vina pe oferta, nu pe mesaj. Cine a pierdut ii raspunde o data celui care a castigat,
   tot din date (replica vine din regula care a transat disputa): ce ramane valabil si
   **cand se rediscuta** - o conditie masurabila
   ("CPA-ul contului coboara sub tinta de 80 RON", "testul E2E confirma tracking-ul"),
   care ajunge si in raspunsul catre client. Decizia nu se negociaza: o dau regulile.
5. **Sinteza Reginei** - **singurul apel LLM** al consiliului, doar cu
   `USE_LLM_SYNTHESIS=true` (implicit `false`: pe CPU, raspunsul determinist pleaca in
   milisecunde, fara niciun apel la Ollama; pornit, cu un model mare pe GPU). Primeste DOAR pozitiile
   membrilor, replicile si decizia (plus amintirea despre acelasi subiect) - nu si
   faptele brute, pe care membrii le-au judecat deja - si le leaga in mesajul pentru
   client. Promptul a scazut de la ~15k la ~6-8k caractere, iar primul token pe CPU de
   la 144 s la ~45 s. O garda de limbaj scurta (`LANGUAGE_GUARD`) ii cere modelului
   mic doar cuvintele si cifrele primite, fara poveste, fara salut, fara sa i se
   adreseze Reginei; `_tidy` taie oricum un "Regina," de la inceput si o semnatura.

**In flux (Server-Sent Events).** Cu `Accept: text/event-stream`, aceeasi deliberare
vine pe masura ce se intampla - pagina `/cont/regina` o foloseste:

| Eveniment | Cand | `data` |
|-----------|------|--------|
| `stage` | incepe o etapa | `{"stage": "context" \| "deliberation" \| "rebuttals" \| "synthesis"}` |
| `opinion` / `rebuttal` | un membru a vorbit | `CouncilOpinion` / `CouncilRebuttal` |
| `token` | un fragment din sinteza Reginei | `{"text"}` - o CIORNA |
| `reply` | la final | `CouncilReply`, acelasi ca varianta JSON |
| `error`, apoi `done` | deliberarea a picat / fluxul s-a terminat | `{"detail"}` / `{}` |

Tokenii sunt ciorna: garda (`check_council_text`) se aplica pe textul intreg, iar
`reply` il inlocuieste - cu varianta determinista, daca sinteza a picat sau a adus
cifre care nu sunt in date. Pozitiile membrilor sosesc imediat; singura asteptare e
sinteza. Fara niciun token in `OLLAMA_FIRST_TOKEN_TIMEOUT` secunde (180),
circuit-breaker-ul trimite direct raspunsul determinist. Cat delibereaza consiliul, un comentariu SSE la
15 s tine conexiunea deschisa prin proxy-uri; limitarea (429) se verifica inainte sa
inceapa fluxul. Fara antetul `Accept`, ruta raspunde JSON, ca inainte.

Sinteza trece prin `check_council_text`: nicio cifra in afara datelor (ale clientului
pot fi repetate, nu "calculate mai departe"), niciun link, nicio actiune pretinsa ("am
marit bugetul"), nicio cheltuiala promisa, nicio garantie, niciun sfat generic
("Silicon Valley", "growth hacking"). O sinteza respinsa sau picata e inlocuita cu
raspunsul determinist; fara Ollama raspunde consiliul determinist. Fara date (niciun client ideal si sub 5 conversii),
niciun LLM nu e apelat - raspunsul spune ce lipseste, nu da sfaturi generice.

**Consiliul in tura de noapte** (`services/council_guard.py`): deciziile din chat se
aplica in campanii. Jobul de propuneri citeste memoria consiliului (`MemoryStream`,
ultimele 7 zile, dupa codul deciziei) si raportul Tehnicianului de acum:

| Restrictie | Cand | Ce face jobul de noapte |
|------------|------|-------------------------|
| Veto pe bani | Tehnicianul: tracking picat, site cazut, drum de conversie rupt | Opreste (`blocked`) bugetele Thompson si consolidarile Meta - toate pe conversii; opreste lansarile si planurile de buget din asteptare. Negativele (pe intentie) merg mai departe |
| Bugetul nu creste | CFO-ul a taiat o idee care cere bani, sau site lent pe mobil | Kelly nu mai urca peste `max_daily_spend`: bugetele se reduc proportional; lansarile din asteptare se opresc |
| Bugetul nu creste (CFO-ul de noapte) | Contul nu mai e rentabil (CPA peste tinta sau ROAS sub 1) si nicio restrictie a CFO-ului nu e activa - fara chat | La fel; decizia se scrie in memorie ("Azi, CFO-ul a oprit automat cresterea bugetului..."), o vede consiliul in chat. Nu judeca sub un veto pe bani (cifre false) si nici sub 5 conversii |

**Ridicarea automata**: fiecare restrictie are conditia ei de rediscutare (aceeasi pe care
o spune consiliul in chat, `CouncilRuling.reopen_when`), verificata noaptea in datele de
azi. Veto pe bani: testul E2E trece dupa veto. Site lent: un LCP sub 4 s dupa veto.
Taietura CFO-ului: contul trece din nou testul lui de rentabilitate (CPA sub tinta sau
ROAS peste 1). Cand conditia e indeplinita, restrictia se ridica pe loc - algoritmul
propune din nou bugete in aceeasi noapte - si se invalideaza in memorie printr-o intrare
`lifted:<cod>`, pe care o vede si consiliul ("Azi, CFO-ul a ridicat restrictia pe buget:
CPA-ul contului a coborat la 68,89 RON, sub tinta de 80 RON"). O restrictie ridicata nu
revine singura; o repune doar o decizie noua a consiliului sau un veto pe care Tehnicianul
il vede din nou. Fara ridicare, o decizie din memorie tine 7 zile. Un veto pe care
Tehnicianul il vede acum se aplica si fara memorie. De aceea viteza si testul E2E ruleaza,
noaptea, inaintea propunerilor. Ce se opreste ramane in DB, cu motivul,
`decided_by="consiliu"`.

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
| Viteza pe mobil | mediana a 3 rulari PageSpeed Insights (strategia mobil, in paralel), facute noaptea si salvate in `SiteSpeedSample`, plus datele de teren CrUX (p75) cand Google le are | LCP peste 4 s, CLS peste 0,25, TBT peste 600 ms sau scor sub 50 (pragurile Google); intre praguri: galben |
| Testul sintetic E2E | un Chromium real (Playwright, doar in worker) parcurge site-ul: consimtamant, CTA, evenimentele GA4/Meta din contract - `TrackingEvidence` | site-ul nu da 2xx, CTA-ul lipseste sau nu e interactiv, ori un eveniment din contract nu primeste 2xx de la platforma |
| Auditul tehnic SEO/GEO | motorul de audit al agentului SEO/GEO, noaptea (`run_site_audit_job`, 25 de pagini, 120 s): scorurile SEO/GEO, problemele pe severitate si cele mai grave cu reparatia - `SiteAuditSnapshot` | niciodata: e context in faptele lui (o problema de continut nu dovedeste ca se pierd bani); peste 14 zile se spune ca e vechi |

Cand si click-urile au scazut, vina nu e a tracking-ului (reclamele livreaza mai
putin) - starea ramane necunoscuta, nu rosie. Fara date, starea e `unknown`, nu
verde. Pixelul Meta si GA4 nu trimit inca serii zilnice in platforma, deci nu se
"verifica": raportul o spune intr-o nota.

**Veto-ul (Smart Veto Engine)** e calculat inaintea oricarui LLM si se sprijina
DOAR pe dovezi - un fals pozitiv ar opri reclamele unui client sanatos:

| Cod | Cand | Ce opreste |
|-----|------|------------|
| `SITE_UNAVAILABLE` | testul sintetic n-a primit 2xx la navigarea initiala | orice decizie pe bani; reclamele se opresc |
| `CRITICAL_JOURNEY_BROKEN` | CTA-ul din contract lipseste sau nu e interactiv | orice decizie pe bani; reclamele se opresc |
| `ATTRIBUTION_BROKEN` | un eveniment din contract n-a ajuns la GA4/Meta cu 2xx | orice decizie pe bani (inclusiv textele noi: un test A/B fara conversii n-are castigator); reclamele se opresc doar daca s-au oprit si comenzile reale |
| `MOBILE_LCP_CRITICAL` | mediana LCP peste 4 s la DOUA verificari la rand | orice cheltuiala in plus |

Tacerea brusca din seriile de conversii, o singura masuratoare lenta, CLS/TBT slab
sau consimtamantul care a blocat testul raman **avertismente** (`warnings`): se spun,
nu opresc nimic. Un test E2E mai vechi de 3 zile nu mai sprijina niciun veto.
Raspunsul Reginei spune veto-ul si prima reparatie, oricare ar fi fost intrebarea.

In consiliu, pozitia lui e calculata din raport (`technician_position`): diagnosticul,
veto-ul, prima reparatie - fara LLM. Garda sintezei respinge si reparatiile pretinse
("am reparat tag-ul").

Masuratoarea de viteza si testul E2E sunt pasi ai mentenantei de noapte
(`speed_check` si `tracking_contract` in `run_client_maintenance_job`, jobul ARQ per
client), doar pentru clientii cu domeniu in Setari. `SEOGEO_PAGESPEED_API_KEY` e
optionala (fara ea, cota Google e mica, dar ajunge pentru 3 rulari pe client pe noapte).

**Monitorizarea sintetica** (`jobs/synthetic.py` + `services/tracking_contract.py`):
Chromium mobil (390x844, service workers blocati), `domcontentloaded` (nu
`networkidle`), click pe consimtamant (OneTrust, Cookiebot, Complianz, CookieYes sau
selectorul clientului), click pe CTA, apoi pana la 8 s de asteptare a evenimentelor.
`request`/`response`/`requestfailed` prind `*.google-analytics.com/g/collect` (`en`/`_en`,
`tid`; si loturile POST) si `*.facebook.com/tr` (`ev`, `id`). Un eveniment trece NUMAI
daca cererea a fost prinsa, e cel din contract si platforma a raspuns 2xx (204 e
valid); altfel, motivul exact: `NETWORK_FAILURE`, `DATALAYER_MISSING`, `EVENT_MISMATCH`,
`CONSENT_BLOCKED`. Pachetul de dovezi (`TrackingEvidence`): URL, momentul, statusul
navigarii, CTA, `ga4_transport_ok`/`meta_transport_ok`, motivul si toate cererile prinse.

Contractul se completeaza din Setari (`PATCH /api/v1/me/site`): `journey_path` (doar o
cale din site, ca `/contact`), `journey_cta_selector`, `journey_consent_selector`,
`ga4_expected_events` si `meta_expected_events` (cel mult 5, separate prin virgula).
Fara evenimente scrise, o platforma conectata (GA4, cont Meta) se testeaza pe
`page_view` / `PageView`.

Doar worker-ul are browser: stadiul `worker` din `Dockerfile.backend`
(`requirements-worker.txt` + `playwright install --with-deps --only-shell chromium`);
API-ul si agentul SEO/GEO raman fara Playwright. Local: `pip install -r
requirements-worker.txt` si `python -m playwright install --only-shell chromium`.

Scutul SSRF al browserului (site-ul e al clientului, deci neincrezut): URL-ul de start
se urmeaza intai prin transportul SSRF-safe (fiecare redirect verificat); in Chromium,
fiecare cerere trece printr-o ruta care refuza IP-urile interne si numele care se
rezolva intern (fail-closed); numele stivei (`postgres`, `redis`, `api`...) si ale
metadatelor cloud nu se rezolva deloc (`--host-resolver-rules`); pagina finala se
verifica si ea. Limita cunoscuta: redirect-urile HTTP din interiorul Chromium nu trec
prin ruta (Playwright vede doar prima cerere a lantului) - un redirect spre un IP
intern scris literal ar ajunge la el orb (nu i se pastreaza continutul). Urmatorul pas,
cand conteaza: un proxy de iesire sau o politica de retea care blocheaza RFC1918 si
link-local pentru containerul worker.

#### Memoria consiliului (fara amnezie intre sesiuni)

`services/memory.py`, dupa conceptele din `thedotmack/claude-mem` (Apache-2.0,
reimplementat, fara cod copiat):

- **Captura**: dupa fiecare raspuns, deciziile majore - ce a taiat CFO-ul, veto-ul
  Tehnicianului, ce a notat Researcher-ul (doar date reale), verdictul CPO-ului pe
  oferta ("a propus pivotarea ofertei spre ..."), decizia Reginei pe bani - intra in
  `MemoryStream` (`client_account_id`, `timestamp`, `agent_role`, `topic`,
  `observation`, `decision`). O intrebare care nu decide nimic (publicul, fara nicio
  taietura) nu lasa urme. Propunerile respinse de client sau esuate la aplicare nu se
  copiaza: se citesc direct din `ProposedChange` (ultimele 30 de zile).
- **Compresie** determinista: prima fraza, cel mult 220 de caractere; aceeasi decizie a
  aceluiasi rol, in ultimele 7 zile, nu se rescrie.
- **Progressive disclosure**: consiliul primeste doar indexul - ultimele 5 intrari, cate
  un rand ("Acum 2 saptamani, CFO-ul a taiat cresterea bugetului...") - in faptele
  fiecarui agent si ale sintezei; istoricul complet e la `GET /api/v1/queen/memory`.

Toate prompturile au regula: verifica Contextul Istoric, nu repeta o decizie respinsa
sau esuata, iar daca o reiei spui ce s-a schimbat. Raspunsul determinist citeaza cea mai
recenta decizie pe acelasi subiect dintr-o sesiune trecuta. O memorie indisponibila nu
opreste chatul: consiliul raspunde fara ea.

#### Researcher-ul (CSO): contextul pietei

Al patrulea scaun (`services/researcher.py`, determinist): aduce piata, ca
deciziile sa nu se ia doar pe datele interne ale clientului.

| Semnal | Regula |
|--------|--------|
| Activitatea competitorilor | presiune in crestere cand CPC-ul licitatiei urca cu 10%+ SI au intrat concurenti noi sau unul si-a urcat cota de afisari cu 5+ puncte - explica un CPC mai mare care nu vine din cont; relaxare la -10% fara intrari |
| Trendul cererii | ultimele 4 saptamani fata de cele 4 dinainte (+/-10%), fata de anul trecut, plus sezonul (indicele lunar): sezon care porneste = fereastra de oportunitate, sezon care se stinge = fara teste noi |
| Ce cauta piata | temele (durerile) din cautari si recenzii care cresc cu 25%+, din cel putin 20 de mentiuni |

**Datele sunt doar reale.** Cererea vine din **Google Trends** (`services/market_trends.py`,
prin `pytrends`, fara cheie): interesul saptamanal pe 5 ani pentru nisa clientului, in
tara lui - indice 0-100, nu cautari, iar textele spun asta. Din aceeasi serie: ultimele 4
saptamani fata de cele 4 dinainte, aceleasi saptamani de anul trecut si sezonul (media
fiecarei luni pe toti anii). O cerere per nisa si tara pe zi (cache pe proces); un refuz
al Google (429) se tine minte 15 minute, ca sa nu fie repetat la fiecare intrebare; un
Google Trends blocat nu tine Researcher-ul pe loc mai mult de 20 s. Licitatia si durerile
din recenzii nu au inca sursa (Google Ads nu expune Auction Insights prin API): raman
necunoscute si se spune asta. Cand exista trendul, aceleasi reguli dau
`CouncilRuling.market_context` - contextul pietei pentru intrebare, care explica decizia
fara s-o schimbe. O intrebare despre pretul click-ului ("de ce a crescut CPC-ul?")
primeste raspunsul din licitatie; fara date de licitatie, consiliul spune ca le lipsesc,
nu ghiceste. Fara nimic masurat, Researcher-ul spune ce lipseste.

**Cautarea pe web (ca Perplexity), reala:** nisa si orasul se scot din cautarile
clientului (`market_focus`: cel mai lung grup de cuvinte repetat in cautari, fara
"pret"/"program"/brand; orasul recunoscut, altfel Romania), apoi doua interogari
DuckDuckGo (`ddgs`, fara cheie): "competitori <nisa> <oras>" si "trenduri <nisa>
Romania <an>". Researcher-ul nu stie cum se cauta: cere abilitatea `web_search` din
registrul de abilitati (vezi mai jos). Primele 5 surse distincte (titlu, fragment,
site) intra, citate, in pozitia Researcher-ului si in faptele sintezei Reginei, care
are voie sa formuleze EXCLUSIV din ele: garda respinge orice cifra din afara lor,
linkurile si sfaturile generice ("Silicon Valley", "growth hacking", "startup"). Cautarile ruleaza in paralel (fire separate), cu timeout de
8 s; un timeout sau o limita DuckDuckGo nu opreste chatul - Researcher-ul spune ca n-a
mers. Rezultatele se tin minte o zi, in proces. Cautarea pe web si Google Trends
ruleaza in paralel.

In consiliu, pozitia lui e calculata (`researcher_position`): concurenta, cererea,
fereastra si sursele de pe web, citate - fara LLM.

#### CPO-ul (Chief Product Officer): oferta si pozitionarea

Al cincilea scaun (`services/cpo.py`, determinist, idei din `menkesu/awesome-pm-skills`):
apara oferta. Nu are surse proprii - judeca pe concluziile celorlalti (clientul ideal
al Reginei, verdictul CFO-ului, piata Researcher-ului) si vorbeste ultimul.

| Situatie | Verdictul CPO-ului |
|----------|--------------------|
| CPA peste tinta, reclamele nu ii vorbesc clientului ideal | `message_gap`: oferta nu e problema, mesajul e - intai rescrierea |
| CPA peste tinta, reclamele ii vorbesc deja si tot pierd bani + un semnal real | `pivot`: spre durerea care creste in piata (Researcher, niciodata demo) sau spre segmentul best-fit |
| La fel, fara semnal | `offer_gap`: oferta se testeaza, nu se schimba |
| Un segment cumpara mult mai usor decat cauta (conversii/cautari >= 1,25, >= 20% din conversii) | `positioning_gap`: pozitionarea se poate ascuti (April Dunford) |

Cu tracking-ul picat (veto-ul Tehnicianului), CPA-ul e fals: nu declanseaza nicio
pivotare. Verdictul intra in `CouncilRuling.offer` (mereu la un CPA peste tinta, iar o
pozitionare de ascutit la intrebarile despre public si texte), nu muta nicio idee si se
scrie in memorie. Directiva (`CouncilReply.product`) mai are pozitionarea, povestea
ofertei (problema, promisiunea, dovada) si mutarile ordonate dupa **RICE** (Reach =
procentul din conversii atins, Impact 0,5-3, Confidence din cat de solide sunt datele,
Effort in saptamani; estimarile de impact si efort sunt fixe pe tip de mutare).

#### Registrul de abilitati (skills, pregatit pentru MCP)

`ppc_agent_server/skills/`: uneltele cu retea nu mai stau in modulele agentilor. O
abilitate e un `BaseAgentSkill` - `name`, `description`, `async execute(**kwargs)` - iar
agentii o cer dupa nume: `await registry.execute("web_search", query="...")`. Numele si
descrierea sunt exact ce cere un `tools/list` MCP. Azi e inregistrata `web_search`
(DuckDuckGo, mutata din Researcher); PageSpeed si testul E2E cu Playwright raman in
job-urile worker-ului pana cand un agent trebuie sa le ceara direct.

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

#### Inaintea primei campanii: costurile clientului si zona reclamelor

Nicio campanie nu se propune pana consiliul nu stie cat castiga clientul dintr-o vanzare
si unde sunt clientii lui (`propose_launch` raspunde 409 cu prima intrebare). Le cere
in chat, pe rand (`services/client_intake.py`), sau le primeste din formular
(`PUT /api/v1/me/economics`; agentia: `PUT /api/v1/clients/{id}/economics`;
`GET` pe aceleasi rute arata pragurile si urmatoarea intrebare):

- **Magazin**: cosul mediu, costul produselor, transportul platit de magazin, comisionul
  de incasare (%), retururile (%). Contributia unei comenzi - ce ramane inainte de
  reclame - e **CAC-ul maxim**; ROAS-ul minim e `cos / contributie` (devine
  `min_roas`, deci il folosesc Kelly, CFO-ul si oprirea reclamelor fara vanzari).
- **Lead-uri**: profitul unui client nou si cate cereri devin clienti. Un lead valoreaza
  `profit x rata` (CPL-ul maxim, devine `default_lead_value`).
- **Zona**: in toata tara, sau local - adresa exacta (OpenStreetMap / Nominatim, gratuit),
  tipul afacerii si pana unde vrea clientul sa ajunga. **Raza o alege consiliul** din tipul
  afacerii si marimea localitatii: o cafenea intr-un oras mare - 3 km, un service auto -
  6 km, o mobila - 20 km; intr-un sat, mai mult, ca reclama sa aiba cui sa se arate.
  Limita clientului e plafonul; una mai larga incepe de la raza logica, iar consiliul
  spune de ce. "raza 8 km" o schimba, "schimba zona" / "actualizeaza costurile" reiau
  intrebarile, "anuleaza" opreste interviul (raspunsurile raman salvate).

Raspunsurile se inteleg fara model ("1.250 lei", "40%", "3 din 10", "nu stiu"); ce nu se
intelege primeste intrebarea din nou, cu un exemplu, iar "de ce?" primeste motivul. Cat
timp o intrebare asteapta, mesajele din chat nu ajung la consiliu si nu consuma limita de
rafala (doar plafonul pe ora). Lansarea care urmeaza merge pe raza aleasa (Meta
`custom_locations`), iar avizul consiliului si rationamentul spun pragul: "profitabila
cat timp un client costa sub X lei; la B lei pe zi, cel putin N vanzari pe zi".

#### Clientul ideal (Jobs to Be Done) si psihologia cumparatorului

Dupa cifre si zona, acelasi interviu intreaba cine sunt clientii (`services/avatar_builder.py`):
situatia in care ajung sa caute, treaba concreta, progresul dorit, cum vor sa se simta si
sa fie vazuti, ce ii face sa ezite, ce ii costa sa schimbe - plus cate pachete vad si ce
garantie primesc. "nu stiu" e un raspuns (campul ramane gol); "actualizeaza profilul"
reia intrebarile. Lansarea asteapta si profilul (409 cu prima intrebare), iar clientii
vechi raspund la urmatoarea lansare.

Profilul (`CustomerAvatar`, in `clientaccount.avatar_answers`) intra in directiva Reginei,
deci il vad toti cei care o primesc:

- **CMO-ul** (`services/propensity.py`): `P(actiune) = (Relevanta + Valoare + Incredere) -
  (Risc + Frictiune)`, fiecare factor 0-10 din dovezi (alinierea reclamelor, bariera
  masurata in cont, grijile spuse de client, garantia, pachetele). Bariera dominanta
  (`lack_of_trust`, `price_uncertainty`, `perceived_risk`, `friction`, `low_relevance`)
  primeste un **experiment** cu ipoteza falsificabila: varianta, control, metrica, +15% la
  conversie, 100 de click-uri pe varianta si 14 zile, si ce o infirma. Rescrierile propuse
  il poarta in brief, langa profil.
- **Garda `fear_manipulation_risk`**: in sanatate, financiar si recrutare (din brand,
  cautari si raspunsuri), declansatorii de frica nu ajung la copywriter, parghia nu mai e
  aversiunea la pierdere, iar textele scrise de model cu ton alarmist sunt respinse.
- **CPO-ul**: peste 3 pachete = choice overload (mutare RICE: cel mult 3, clare); fara
  garantie, propune inversarea riscului potrivita barierei (garantie, audit sau
  consultatie gratuita, pret fix). Povestea ofertei foloseste cuvintele clientului.
- **CCO-ul**: Jev vede clientul ideal cand judeca personajul si mizele; urgenta falsa
  ("doar azi" fara data) scade increderea, iar stock-ul prezentat drept clienti reali e
  autoritate neverificata.

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

Obiectele cu id real, pe fiecare platforma:

- **Meta**: `meta_campaign/{id}`, `meta_ad_set/{id}`, `meta_ad/{id}` (`PAUSE`, plus
  `UPDATE` de buget pe campanie si set) - `POST graph.facebook.com/v25.0/{id}`, cu
  `daily_budget` in unitatea minima a monedei (`PPC_META_CURRENCY`).
- **Google Ads**: `campaign/{id}` (buget zilnic al campaniei, pauza) si
  `negative_keyword/{termen}` (lista de negative a contului).
- **TikTok**: `tiktok_ad_group/{id}` (buget zilnic, pauza), `tiktok_ad/{id}` (pauza).
- **ChatGPT**: `chatgpt_campaign/{id}` (buget zilnic, pauza).

Restul primeste **409 si ramane `pending`**, fiecare cu motivul lui:

- **Termenii motorului hibrid** (`ppc_keyword`, `keyword_budget` din unealta MCP):
  resursa lor e un **termen de cautare**, iar buget pe un cuvant nu exista in
  Google Ads. Si anunturile Google (`ad/{id}`): oprirea cere si grupul lor.
- **Moneda contului alta decat leul** (citita din platforma la Google, TikTok si
  ChatGPT) - plafonul de siguranta e in lei.
- **`ad_set_group/...`** (consolidarile de lichiditate) — id sintetizat de noi,
  nu exista in contul Meta.
- **mod `mock`, sau cont neconectat** — nu aplicam nimic si nu ne prefacem
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
(`alembic upgrade head` si rolul limitat al bazei, o data per pornire) si `backup`
(un `pg_dump` pe zi). Imaginile: `Dockerfile.backend`
(una singura pentru api/worker/seo-geo; Python slim, torch doar CPU, fara
Playwright) si `Dockerfile.frontend` (build `output: "standalone"`).

```bash
cp .env.example .env      # JWT_SECRET_KEY, SECRETS_KEY, POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD, REDIS_PASSWORD
docker compose up -d --build
# o singura data: agentia (tenant-ul), apoi AGENCY_TENANT_ID=<id> in .env si
# docker compose up -d api
docker compose run --rm api python -c "from sqlmodel import Session; from ppc_agent_server.db import get_engine; from ppc_agent_server.auth import create_tenant; s = Session(get_engine()); t, k = create_tenant(s, 'Agentia Mea SRL'); print(t.id, k)"
```

Securitate:

- Postgres si Redis **nu au porturi publicate**; traiesc pe reteaua `data`
  (`internal: true`, fara iesire in internet), impreuna doar cu `api` si `worker`.
  Redis cere parola. Parolele lipsa opresc pornirea (`${VAR:?}`).
- API-ul si worker-ul se conecteaza cu **rolul limitat `ppc_app`**
  (`ppc_agent_server/app_role.py`): citesc si scriu randuri, atat - nu pot crea,
  sterge sau modifica tabele, nu pot citi fisiere sau rula comenzi pe server, nu pot
  crea utilizatori. Proprietarul bazei (`ppc_agent`) il folosesc doar `migrate`
  (care, dupa migratii, aduce rolul la drepturile lui, si pe tabelele noi) si
  `backup`; parola lui nu ajunge in containerele care primesc cereri din internet.
- Corpul unei cereri: maximum 2 MB (60 MB la uploadul de creative), refuzat cu 413
  inainte sa ajunga in memorie - si cand e trimis in bucati, fara `Content-Length`.
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
  de Argon2); conturi noi - 3/ora pe IP, numarate si cele cu email deja folosit
  (409-ul nu poate fi folosit la ghicit in masa ce adrese au cont), emailul validat
  si salvat cu litere mici, lungimi maxime pe nume, email si parola; chatul Reginei - 6 mesaje/minut si 60/ora per client. Peste: 429 cu
  `Retry-After`. Memoria e per proces: cu mai multi workeri uvicorn, limita se
  inmulteste cu numarul lor.

### Agenti AI externi prin MCP

Platforma e un server MCP: orice agent AI care vorbeste MCP (Claude, ChatGPT prin
API, Cursor, n8n, agenti scrisi cu OpenAI Agents SDK sau LangChain) ii poate folosi
datele. Unelte: `get_budget_summary`, `get_cannibalization_insights`,
`get_seo_opportunities` si `propose_budget_change` - aceasta din urma doar CREEAZA o
propunere care asteapta aprobarea omului.

**Cheia.** Clientul isi face cate o cheie per agent - `POST /api/v1/me/mcp-keys`
`{"name": "ChatGPT agentie"}` - si primeste, o singura data, cheia `mcp_...` si adresa
serverului. Cheia merge DOAR pe MCP (nu poate aproba nimic, deci nu poate cheltui),
vede un singur client si se revoca oricand: `DELETE /api/v1/me/mcp-keys/{id}`.
Token-ul de login nu se da unui agent: deschide tot contul.

**Agenti de la distanta - Streamable HTTP** (serverul trebuie sa fie public, HTTPS):
`POST {PUBLIC_API_URL}/api/v1/mcp/stream`, cu `Authorization: Bearer mcp_...`.

```powershell
# Claude Code
claude mcp add --transport http agentie https://api.domeniu.ro/api/v1/mcp/stream --header "Authorization: Bearer mcp_..."
```

```python
# OpenAI Responses API: modelul cheama singur uneltele
client.responses.create(
    model="<modelul tau>",
    tools=[{
        "type": "mcp",
        "server_label": "agentie",
        "server_url": "https://api.domeniu.ro/api/v1/mcp/stream",
        "headers": {"Authorization": "Bearer mcp_..."},
    }],
    input="Cat buget zilnic mai am disponibil?",
)
```

**Aplicatii locale - stdio** (Claude Desktop): serverul porneste ca proces, pe un
singur client, ales prin `MCP_CLIENT_ACCOUNT_ID`.

```json
{
  "mcpServers": {
    "agentie": {
      "command": "C:\\...\\Agent marketing\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ppc_agent_server.mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\...\\Agent marketing",
        "DATABASE_URL": "sqlite:///C:/.../Agent marketing/ppc_agent_server.db",
        "MCP_CLIENT_ACCOUNT_ID": "3"
      }
    }
  }
}
```

Inca nu: conectorii din interfata web Claude.ai si ChatGPT cer OAuth 2.1 - urmatorul
pas. Endpoint-ul SSE (`/api/v1/mcp/sse`) ramane pentru clientii vechi.

### CCO: evaluarea creativelor

`POST /api/v1/creative/upload` (imagine JPEG/PNG pana la 5 MB sau video MP4/MOV/WebM
pana la 50 MB, token de client) intoarce verdictul unui Senior Media Buyer, INAINTE de
bani: `decision` (`ELIGIBLE_FOR_TEST` / `REVISE_BEFORE_TEST` / `HUMAN_REVIEW_REQUIRED`),
`scores` (`trust`, `hook_power`, `cognitive_load_and_hierarchy`, `format_suitability`,
0-10; la video si `audio`, `retention`, `virality`), `detected_risks`, top 3 `priority_fixes` si, la
video, `video_facts` (durata, cadre vazute, taieturi, voce, muzica/efecte, LUFS,
transcrierea).

Cine aduna faptele (`services/creative_evaluator.py`):

| Fapt | Sursa |
|------|-------|
| cadre, pauze, taieturi, sunet | ffmpeg |
| vocea | ElevenLabs Scribe / whisper.cpp |
| textul de pe creativa, marimea si blocul fiecarui rand | Tesseract (`ron`) |
| domeniul, firma, conditiile, greselile, beneficiul, intro-ul, subtitrarile, CTA-ul; la video povestea (mizele, Marea Intrebare, fenta, re-agatarile) | Jev (`JEV_API_KEY`), o singura cerere |
| poza stock, impactul vizual, riscurile si remedierile scrise | modelul cu vision (`OLLAMA_VISION_MODEL`), pe UN cadru |

Jev nu vede imagini (doar text), dar costa ~$0,04 pe milion de tokeni si raspunde in
secunde; modelul cu vision vede un singur cadru (pe CPU, ~90 s pe cadru cu gemma3:4b).
Firma conteaza doar cand Jev e sigur (>= 0,7): e plasa de siguranta a domeniilor
sensibile. Scorurile si decizia le calculeaza codul:

- **Trust**, prioritatea 0: in recrutare, financiar si sanatate, fara firma
  identificabila (un telefon nu e o identitate) -> sub 4 -> `HUMAN_REVIEW_REQUIRED`;
  conditiile lipsa, 3+ greseli de scriere si stock-ul prezentat drept "echipa reala" scad;
- **Ierarhie**: peste 3 blocuri de text concurente sau hook-ul ingropat = incarcare mare;
- **Hook**: la video, primele 3 secunde - timpul mort (cadru inghetat sau negru peste
  1 s) il masoara ffmpeg, iar un intro de logo il prabuseste;
- **Format**: din dimensiunile fisierului (4:5 si 9:16 sunt nativele);
- **Audio** (video): cand porneste sunetul, loudness EBU R128 (sub -24 LUFS = prea
  incet), distorsiunea si - cu transcrierea - vocea fara subtitrari (-3: feed-ul se
  priveste des mut). Video mut = risc, nu blocaj (scor 5);
- **Retentie** (video, tot clipul, max 3 minute): peste 60 s, pauzele moarte de dupa
  hook (negru >= 1 s, cadru static >= 4 s), ritmul lent cand nu vorbeste nimeni si
  lipsa CTA-ului de la final. OCR-ul si Jev vad 2 cadre din deschidere + 3 pana la final;
- **Povestea** (video, "bucla dopaminei"): **mizele** (un personaj in care publicul se
  recunoaste, ce risca privitorul fara oferta, urgenta), **Marea Intrebare** (primele
  secunde lasa o bucla deschisa), **fenta** (pare ca duce spre banal, apoi intoarce) si
  **re-agatarile** (peste 10 s: cel mult 5 s fara un cadru nou - masurat de ffmpeg - sau o
  intrebare, o dezvaluire noua). Fara mize sau fara Marea Intrebare, `hook_power` nu trece
  de 5, oricat de bun ar fi vizualul. `virality` = Marea Intrebare 2 + mizele 3 (cate 1) +
  fenta 3 + re-agatarile 2; e un potential, nu opreste testul. Cu sunet netranscris,
  povestea nu se judeca (`virality` = null, hook-ul neplafonat): ar putea sta in voce.

#### CCO-ul in consiliu: context, feedback din piata, GEO, trends_db

Inainte de evaluare, CCO-ul afla de la ceilalti agenti (`services/creative_memory.py`,
interfetele in `services/creative_context.py`): `CreativeEvaluationContext` = avatarul JTBD,
ipoteza CMO-ului (publicata de directiva de noapte pe `clientaccount.cmo_hypothesis`; fara
ea, calculata din interviu), lectiile din piata ale contului si trendurile. Raspunsul spune
pe ce s-a sprijinit (`context_notes`) si poarta `evaluation_id`.

- **Message Match** (`message_match`): Jev spune la ce grija a clientului ideal raspunde
  reclama si daca face varianta ceruta de ipoteza CMO-ului. O nealiniere = 4, doua = 1:
  reclama se respinge (`REVISE_BEFORE_TEST`, deci si lansarea), oricat de frumoasa ar fi.
- **Feedback-ul PPC** (`PerformanceFeedback`): verdictele se pastreaza
  (`creativeevaluation`); noaptea, dupa sincronizare, PPC-ul trimite cifrele anunturilor in
  care au ajuns (lansate de platforma sau legate de client cu
  `POST /api/v1/creative/evaluations/{id}/ad`). Intern: `POST /api/v1/creative/feedback`
  (cheia agentiei) sau unealta MCP `report_creative_performance`. Hook 8+ cu hook rate sub
  20% (video; CTR sub 0,8% la imagini) sau aliniere 8+ cu ROAS sub prag = supraestimare;
  invers, subestimare - cate o corectie (`performancecalibration`), din 1.000 de afisari /
  100 de click-uri. La urmatoarea evaluare pe cont, lectiile din 90 de zile muta hook-ul si
  alinierea cu pana la 3 puncte (`get_creative_lessons` le arata).
- **GEO** (`purpose=page`, cu `alt_text` din pagina): o imagine pentru landing page/blog se
  judeca dupa cat de usor o citeaza un AI - cifre cu unitate (3), text lizibil (2),
  diagrama/tabel (2), alt descriptiv (2), firma (1) = `geo_citability`; hook-ul si formatul
  de feed nu conteaza acolo.
- **trends_db** (RAG-ul CCO-ului): note "ce merge acum" pe Meta/TikTok, pe industrie. Doua
  surse: agentia (`POST`/`GET /api/v1/creative/trends`) si automatizarea saptamanala
  (`POST /api/v1/trends/ingest`, mai jos). Fiecare trend are vectorul lui
  (`services/embeddings.py`): cu `OLLAMA_EMBED_MODEL` (ex. `nomic-embed-text`), embeddings
  semantice din Ollama; fara, vectori lexicali locali (n-grame de litere, fara model).
  Vectorii stau ca JSON langa trend, iar cosinusul se calculeaza in Python - sute de
  trenduri, nu milioane (pgvector ar cere alta imagine de Postgres). CCO-ul ia trendurile
  apropiate de industria clientului si le pune in promptul modelului cu vision, ca date.
- **Concepte esuate**: fiecare verdict pastreaza conceptul (hook-ul principal) si fisierul
  (SHA-256); daca acelasi fisier sau acelasi hook, spus putin altfel, a esuat deja pe cont,
  scorul lui nu trece de 5.
- **Contextul e obligatoriu** la orice evaluare; fara profilul JTBD sau fara ipoteza CMO,
  `context_notes` spune ce nu s-a putut verifica.

#### Trendurile saptamanii: GitHub Actions, fara n8n

`.github/workflows/trend_ingestion.yml` ruleaza `scripts/trend_scraper.py` in fiecare luni
la 04:00 UTC (si manual, din tab-ul Actions). Scriptul e Python pur (doar biblioteca
standard): scrie trendurile in `trends.json` (deocamdata date de proba, in forma
`TrendPayload`), apoi le trimite la `POST /api/v1/trends/ingest` cu antetul `X-Cron-Secret`.
Ruta sterge intai ce e mai vechi de 30 de zile, apoi salveaza trendurile cu vectori
(acelasi titlu pe aceeasi platforma se actualizeaza). Fara `CRON_SECRET_KEY` (minimum 32 de
caractere) ruta e oprita - 503.

Secretele din GitHub (Settings > Secrets and variables > Actions): `API_URL` - adresa
publica HTTPS a API-ului (GitHub nu vede `localhost`) - si `CRON_SECRET_KEY`, aceeasi
valoare ca in `.env`.

Vocea se transcrie cu ElevenLabs Scribe cand e setat `ELEVENLABS_API_KEY` (romana cea mai
buna; pleaca doar sunetul, dar pleaca la ElevenLabs si costa pe minut), altfel local cu
whisper.cpp din ffmpeg (`WHISPER_MODEL`, ex. `ggml-small-q5_1.bin`, ~190 MB de pe
huggingface.co/ggerganov/whisper.cpp; ~1 min pe CPU pentru 15 s). Fara niciuna, sunetul
se masoara oricum, dar vocea ramane neverificata (apare ca risc).

Fara model de vision sau fara `JEV_API_KEY`: 503. Mai trebuie `tesseract` cu limba
romana (`tesseract-ocr-ron`) si, pentru video, `ffmpeg`/`ffprobe` in PATH - imaginea
Docker le are pe toate. Transcrierea locala cere un ffmpeg 8+ cu filtrul `whisper` (ex.
gyan.dev full pe Windows); cel din Debian (Docker) nu-l are, deci acolo vocea o
transcrie ElevenLabs.

### Teste server

```powershell
.venv\Scripts\python.exe -m pytest tests_server
.venv\Scripts\python.exe -m mypy --strict ppc_agent_server
```

100% offline — SQLite in-memory, `InlineJobQueue`, zero Redis/Postgres reale
(la fel ca restul proiectului). `ruff check` (fara argument de cale) acopera
deja tot, inclusiv `ppc_agent_server/` si `tests_server/`.

### Inainte de pilotul Meta (si de orice lansare majora)

**1. Pilotul simulat.** Ruleaza tot lantul pe date fictive, in mod `live` real, dar
cu Meta interceptata local (nicio cerere nu pleaca): CAPI cu `event_id`,
deduplicarea, aprobarile, lansarea OPRITA, plafonul `MAX_DAILY_SPEND_RON` (409 +
alerta CRITICAL), refuzul unui cont in alta moneda. Sare implicit in suita:

```powershell
$env:PILOT_E2E = "1"; .venv\Scripts\python.exe -m pytest tests_server/test_e2e_pilot_simulation.py -v
```

**Consiliul inainte de orice lansare.** `POST /campaigns/propose_launch` delibereaza
consiliul pe lansare, cu toate datele clientului, si ataseaza avizul in
`before.council_review`; fara consiliu (sursele pica) - 503, nu se depune nimic. Un veto al
Tehnicianului sau CFO-ul pe un cont care pierde bani dovedit scriu lansarea `blocked`;
rezerva CFO-ului pe un cont fara date ramane doar in aviz (un prim test, in plafon, e
felul in care se strang datele). La aprobare se verifica din nou. Tot atunci CCO-ul
evalueaza imaginea reclamei (`before.creative_review`): "de revizuit" scrie lansarea
`blocked`, cu reparatiile lui; "verificare umana" ramane de aprobat, cu avertisment (aprobarea
e acea verificare); un CCO care nu poate rula (Ollama oprit) lasa doar o nota in aviz.
Pe procesor, evaluarea tine 1-4 minute.

**Oprirea de urgenta (admin, din chat).** Emailurile din `ADMIN_EMAILS` pot scrie in
chatul consiliului, exact: «oprește campaniile» / «oprește tot» / «stop campanii».
Efect: campaniile lansate de platforma trec pe pauza in Meta, propunerile in asteptare
care ar cheltui devin `blocked`, nimic nou nu se depune, aproba sau executa (423), iar
jobul de noapte nu mai propune. «repornește agentul» ridica blocajul; campaniile raman pe
pauza pana le pornesti din Ads Manager. Ce nu s-a putut opri apare in raspuns - de oprit
manual.

**Bugetele de noapte (Kelly + Thompson).** Din Meta, fiecare conversie se numara o data
(`omni_purchase`, altfel `purchase`; la fel lead-urile) si doar in 7 zile dupa click,
fara view-through. Bugetul se imparte dupa valoarea adusa pe leu cheltuit, nu dupa rata
de conversie pe click. Un set Meta se misca cel mult 20% pe noapte, de la bugetul lui de
acum; seturile aflate in invatare (`LEARNING` - cele cu invatarea limitata primesc pasi)
si cele cu bugetul pe campanie (CBO) nu se ating. Planul nou
inlocuieste propunerile de ieri inca neaprobate, iar plafonul numara bugetul de acum al
fiecarui set (nu suma tuturor ajustarilor). Platformele fara chei sunt sarite. CFO-ul
judeca aceleasi cifre: sincronizarea de noapte le scrie in `PlatformArmSnapshot` (doar
in `live` - in `mock` sunt inventate). Bugetul se imparte doar intre seturile care ruleaza
acum; cele oprite raman in cifrele CFO-ului (banii lor s-au cheltuit), dar nu primesc buget.

**Monitorul de oboseala.** Tot in `live`, sincronizarea de noapte citeste din Meta fiecare
anunt activ - si pe cele fara nicio vanzare, care altfel nu ajungeau niciodata la oprire:
cheltuiala, afisarile si conversiile de la lansare, frecventa pe 7 zile, CTR/CPA pe 3 zile
fata de 14 si zilele proaste (CPA-ul zilei peste tinta). Starea se recalculeaza noaptea:
`profitable` (vanzari la un CPA de cel mult tinta - se judeca pe oboseala), `new` (se
judeca pe cheltuiala fara vanzari), `paused` (nu ruleaza - nu se judeca). Conversiile vin
din sursa care a vazut mai multe, webhook sau Meta. Propunerea de oprire e `meta_ad/<id>`:
se executa in Meta la aprobare.

**2. Cele 5 lucruri din afara codului** (testul nu le poate verifica):

1. **Account Spending Limit in Ads Manager.** Singura oprire garantata: Meta poate
   cheltui intr-o zi pana la +75% peste bugetul zilnic, iar plafonul nostru vede
   doar ce trece prin aplicatie.
2. **Token real de System User** (nu personal), cu `ads_management` si acces la pixel;
   aplicatia Meta in modul Live, Business Verification facuta. In `.env`:
   `PPC_PROVIDER_MODE=live`, `PPC_META_CURRENCY=RON`.
3. **`eventID` in pixelul din Gomag.** Purchase-ul din browser trebuie sa poarte
   exact `gomag_order_{id}`, altfel fiecare vanzare apare de doua ori. Verifica in
   Events Manager -> Test Events (cu `META_CAPI_TEST_EVENT_CODE`), apoi goleste codul.
4. **Server public, HTTPS, pornit permanent.** Webhook-ul Gomag trebuie sa ajunga la
   `/api/v1/tracking/conversion/{id}` (cu `Authorization: Bearer <cheia agentiei>` -
   verifica daca Gomag permite antete pe webhook). Si imaginea reclamei: un URL
   public, direct (fara redirect), altfel lansarea pica la primul pas.
5. **Obiectivul, valoarea unei conversii si pragul de rentabilitate, pe client**
   (`PATCH /clients/{id}`). Magazin: `objective=sales`, `default_lead_value` = cosul
   mediu asteptat (pana sunt destule vanzari, apoi se ia cel real din Meta) si
   `min_roas` = 1 / marja (marja 40% -> 2.5; nesetat: 2, adica marja 50%). Kelly
   creste bugetul doar peste prag, CFO-ul judeca fata de el, iar monitorul opreste o
   reclama fara vanzari la de 2 ori cosul / prag (150 / 2,5 = 60 -> 120 de lei). Lead-uri:
   `objective=lead_generation`, `default_lead_value` = cat valoreaza REAL un lead
   (implicit 300 lei), prag 1. O valoare umflata face orice cont sa para rentabil.

### Backup-uri

Serviciul `backup` scrie un `pg_dump` pe zi in `BACKUP_DIR` (implicit `./backups`,
ignorat de git): `ppc_agent-AAAA-LL-ZZ.dump`, format custom (comprimat), pastrat 14
zile. Il face la prima ora in care stiva e pornita in ziua respectiva, deci si dupa
o noapte cu calculatorul oprit. Backup-urile de pe acelasi disc nu te apara de
discul care cedeaza: pune `BACKUP_DIR` pe un folder sincronizat (OneDrive, Google
Drive) sau copiaza-le periodic in alta parte. Contin datele clientilor (tokenurile
lor raman criptate cu `SECRETS_KEY`, care nu e in backup) - tine-le private.

Restaurarea (opreste intai procesele care scriu in baza):

```bash
docker compose stop api worker
docker compose exec -T postgres pg_restore -U ppc_agent -d ppc_agent --clean --if-exists --no-owner < backups/ppc_agent-2026-10-03.dump
docker compose up -d
```

`up -d` reporneste `migrate`: aduce schema la zi si da din nou drepturile rolului
`ppc_app`. Verificat pe backup-ul real, restaurat intr-un Postgres separat: aceleasi
20 de tabele cu acelasi numar de randuri, migratiile si rolul limitat dupa el.

### Mutarea pe alt calculator

Doua lucruri nu sunt in git si se muta separat (stick, manager de parole - nu GitHub):

- **`.env`, acelasi fisier.** `JWT_SECRET_KEY` tine login-urile valide, `SECRETS_KEY`
  descifreaza tokenurile clientilor, `AGENCY_TENANT_ID` e agentia din baza mutata.
- **Baza de date**: cel mai nou fisier din `backups/` (vezi mai sus).

Pe calculatorul nou (Git Bash, Docker Desktop pornit): cloneaza, pune `.env` in folderul
proiectului si backup-ul in `backups/`, apoi:

```bash
docker compose up -d --wait postgres
docker compose exec -T postgres pg_restore -U ppc_agent -d ppc_agent --clean --if-exists --no-owner < backups/ppc_agent-2026-10-03.dump
docker compose up -d --build
```

Primul build dureaza (torch, Chromium, site-ul), iar API-ul porneste in 1-3 minute.
Verificat pe o copie curata, cu terminatii Windows (`core.autocrlf=true`): baza
restaurata, login-ul pastrat, toate containerele sanatoase, jobul de noapte fara erori.
Ollama si modelele din `.env` se instaleaza separat, pe calculator.

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
