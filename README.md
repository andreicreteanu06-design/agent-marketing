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
| 1 | Modulul 1 — context si ingestie (crawler, GSC, GBP, keyword planner, negative) | ⏳ |
| 2 | Modulul 2 — alocare buget (Thompson Sampling) + atribuire Markov | ⏳ |
| 3 | Modulul 3 — optimizare Quality Score + lichiditate Meta | ⏳ |
| 4 | Modulul 4 — poarta de aprobare + limitator absolut de cheltuiala | ⏳ |

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

- **Fara scriere fara aprobare.** Orice modificare trece prin
  `propose -> proposed_changes.json -> confirmare umana explicita -> execute`.
- **Plafon absolut de cheltuiala.** Un plafon hardcodat in cod pe care configuratia
  nu il poate depasi; un set de modificari care il incalca nici macar nu se scrie.
- **Fara credentiale in cod sau in git.** Doar `.env` local, ignorat de git.
- **v1 nu apeleaza platformele reale.** `execute` doar logheaza apelurile pe care
  le-ar face.

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
