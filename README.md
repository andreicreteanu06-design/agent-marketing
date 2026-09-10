# Agent PPC

Unealta Python, controlata prin configuratie, care ajuta marketerii sa planifice
si sa gestioneze campanii **Google Ads** si **Meta Ads**, folosind modele
matematice pentru alocarea bugetului si atribuire, in spatele unor **guardrails
stricte cu om in bucla (HITL)**.

> **Versiunea 1 nu face niciun apel real** catre platformele de reclame. Fiecare
> integrare externa sta in spatele unui adaptor cu implementare `mock`, deci
> intreaga logica este testabila acum. Clientii `live` se adauga intr-o faza
> ulterioara.

## Stare

| Faza | Continut | Stare |
|------|----------|-------|
| 0 | Schela proiectului, configurare, CLI, adaptoare | ✅ |
| 1 | Modulul 1 — context si ingestie (crawler, GSC, GBP, keyword planner, negative) | ✅ |
| 2 | Modulul 2 — alocare buget (Thompson Sampling) + atribuire Markov | ✅ |
| 3 | Modulul 3 — optimizare Quality Score + lichiditate Meta | ✅ |
| 4 | Modulul 4 — poarta de aprobare + limitator absolut de cheltuiala | ✅ |
| — | Integrare `live` (clienti reali Google Ads / GSC / GBP / Meta) | ⏳ |

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
| `live` | Momentan un stub: ridica `SetupRequiredError` cu instructiuni. |

## Utilizare

```powershell
.venv\Scripts\python.exe -m ppc_agent.cli --help
```

| Comanda | Rol |
|---------|-----|
| `ingest --url <domeniu>` | Modulul 1: crawling + date organice + expansiune cuvinte cheie |
| `plan` | Modulele 2-3: alocare buget, atribuire, Quality Score, lichiditate Meta |
| `propose` | Modulul 4: scrie `proposed_changes.json` (nu aplica nimic) |
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
| `budget.max_daily_spend` | `config.yaml` | Limita ta zilnica |
| `HARD_CEILING = 500.00` | hardcodat in `ppc_agent/guardrails/spend_limiter.py` | Plafon absolut; `max_daily_spend` nu il poate depasi (eroare la construirea limitatorului) |

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

## Dezvoltare

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m mypy --strict ppc_agent
.venv\Scripts\python.exe -m ruff check
```

## Structura

```
ppc_agent/
  config.py       configuratie (pydantic-settings + YAML)
  errors.py       tipuri de exceptii partajate
  cli.py          interfata linie de comanda (typer)
  providers/      adaptoare externe: base (ABC), factory, mock/, live/
  ingestion/      Modulul 1
  decision/       Modulul 2
  alignment/      Modulul 3
  guardrails/     Modulul 4
tests/
  fixtures/       date de test locale
```
