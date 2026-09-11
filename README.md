# Agent PPC

Unealta Python, controlata prin configuratie, care ajuta marketerii sa planifice
si sa gestioneze campanii **Google Ads** si **Meta Ads**, folosind modele
matematice pentru alocarea bugetului si atribuire, in spatele unor **guardrails
stricte cu om in bucla (HITL)**.

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
| — | Integrare `live` (Google Ads / GSC / GBP / Meta / Fish Speech / Flick) | ⏳ |

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
| `live` | Clientul LLM (Ollama, vezi mai jos) e functional. Google Ads / GSC / GBP / Meta / Fish Speech / Flick raman stub-uri care ridica `SetupRequiredError`. |

## Utilizare

```powershell
.venv\Scripts\python.exe -m ppc_agent.cli --help
```

| Comanda | Rol |
|---------|-----|
| `ingest --url <domeniu>` | Modulul 1: crawling + date organice + expansiune cuvinte cheie |
| `plan` | Kelly (plafon zilnic) + Thompson (alocare) + Markov + Quality Score + lichiditate Meta |
| `copy --keyword <kw> --usp <text> --trigger <pas\|status\|fomo\|aida>` | Genereaza copy emotional; il adauga in `proposed_ads_queue.json` (HITL). `--dry-run` disponibil |
| `build-creative --keyword <kw> --broll <video>` | Modulul 5: copy -> voce (Fish Speech) -> video (Flick) -> `.mp4` in `creative_output/` |
| `propose` | Modulul 4: scrie `proposed_changes_*.json` (nu aplica nimic) |
| `status` | Arata setul de modificari in asteptare si modul furnizorilor |
| `execute --changeset <fisier> --confirm` | Modulul 4: executa un set confirmat (simulat in v1) |

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
- **`proposed_changes*.json` si `config.yaml` sunt in `.gitignore`.**
- **Toate testele ruleaza fara retea** (furnizori `mock` + fixture-uri locale).

## De la `mock` la `live`

Fiecare furnizor extern are trei parti in `ppc_agent/providers/`:

| Parte | Fisier | Stare |
|-------|--------|-------|
| interfata (ABC) | `base.py` | completa |
| implementare `mock` | `mock/*.py` | completa, deterministica, fara retea |
| stub `live` | `live/__init__.py` | ridica `SetupRequiredError` |

Pentru a activa un client real:

1. Obtine credentialele (Google Ads developer token + OAuth2, Meta app) si pune-le
   in `.env`.
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

## Dezvoltare

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m mypy --strict ppc_agent
.venv\Scripts\python.exe -m ruff check
```

## Structura

```
swipe_file.json   formule de copywriting emotional (RAG local, editabil)
ppc_agent/
  config.py       configuratie (pydantic-settings + YAML)
  errors.py       tipuri de exceptii partajate
  cli.py          interfata linie de comanda (typer)
  texttools.py    normalizare / tokenizare / sentiment (modul frunza)
  providers/      adaptoare externe: base (ABC), factory, mock/, live/
  ingestion/      Modulul 1 — context si ingestie
  decision/       Modulul 2 — Thompson Sampling + Markov + Kelly (kelly_sizing.py)
  alignment/      Modulul 3 — Quality Score + lichiditate Meta
  guardrails/     Modulul 4 — ApprovalGate + AbsoluteSpendLimiter
  copywriter/     copy direct-response emotional (engine, llm, swipe, pipeline)
  creative/       Modulul 5 — audio_engine (Fish Speech) + video_engine (Flick) + factory
tests/
  fixtures/       date de test locale
```
