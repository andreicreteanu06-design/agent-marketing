"""Garda consiliului in tura de noapte: deciziile din chat se aplica in campanii.

Consiliul (``council.py``) decide in chat; jobul PPC de noapte
(``jobs/tasks.run_propose_job``) calculeaza bugetele cu Kelly/Thompson. Fara punte,
un veto al Tehnicianului sau o taietura a CFO-ului ramaneau teorie: noaptea,
algoritmii ar fi mutat si crescut bugetele pe cifre false. Doua restrictii, din
memoria consiliului (``MemoryStream``, ultimele :data:`COUNCIL_MEMORY_DAYS` zile) si
din raportul Tehnicianului de acum:

- **veto pe bani** (Tehnicianul: tracking picat, site cazut, drum de conversie rupt):
  nicio decizie pe bani nu se ia pe conversii false. Modificarile de buget (Thompson)
  si consolidarile Meta (lichiditate - tot pe conversii) se opresc (``BLOCKED``), la
  fel lansarile de campanii si planurile de buget inca in asteptare. Un pixel mort
  arata zero conversii: fara veto, Thompson ar fi taiat exact seturile care vand.
  Cuvintele negative (pe intentia cautarii, nu pe conversii) merg mai departe.
- **inghetarea cheltuielilor** (CFO-ul a taiat o idee care cere bani - cont
  nerentabil sau fara dovezi; ori Tehnicianul: site lent pe mobil): bugetul nu
  creste. Kelly nu mai poate urca plafonul peste bugetul zilnic aprobat al contului
  (``max_daily_spend``): alocarile Thompson se reduc proportional, iar lansarile in
  asteptare se opresc. Scaderile si mutarile intre campanii raman.

**Ridicarea**: fiecare restrictie are o conditie de rediscutare (``council._conflicts``,
``CouncilRuling.reopen_when``), iar jobul de noapte o verifica in datele de azi. Cand e
indeplinita, restrictia se ridica pe loc si se invalideaza in memorie: o intrare noua,
``lifted:<cod>`` (memoria e doar adaugata, ca un jurnal), pe care o vede si consiliul
din chat ("Azi, CFO-ul a ridicat restrictia pe buget: CPA-ul a coborat..."). Conditiile:

- veto pe bani: testul E2E trecut, DUPA veto;
- site lent: o masuratoare PageSpeed cu LCP sub 4 s, DUPA veto;
- CFO: contul trece din nou testul lui de rentabilitate (CPA sub tinta sau ROAS peste 1) -
  aceeasi regula dupa care a taiat.

O restrictie ridicata ramane ridicata: doar o decizie noua o repune. Iar deciziile noi
nu asteapta chatul - si Tehnicianul, si CFO-ul judeca singuri contul in fiecare noapte:

- un veto pe care Tehnicianul il vede acum (testul E2E, PageSpeed) se aplica si fara
  memorie - tracking-ul picat nu asteapta ca cineva sa intrebe in chat;
- **CFO-ul de noapte**: cand contul nu e rentabil (CPA peste tinta sau ROAS sub 1, aceeasi
  regula ca in chat) si nu exista deja o restrictie a CFO-ului, pune el una
  (:data:`CFO_NIGHT_CODE`): o scrie in memorie ("Azi, CFO-ul a oprit automat cresterea
  bugetului...") si Kelly nu mai urca bugetul. Se ridica la fel ca celelalte: cand contul
  trece din nou testul. Cu un veto pe bani activ, CFO-ul nu judeca: fara tracking, un CPA
  mare e un CPA fals (lipsesc conversiile), iar bugetele sunt oricum oprite.

Fara ridicare, o decizie din memorie tine :data:`COUNCIL_MEMORY_DAYS` zile (dupa care,
daca problema e tot acolo, cea de noapte o pune din nou).

Modul pur: regulile. Citirea memoriei si scrierea propunerilor sunt in ``jobs/tasks.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from ppc_agent.guardrails.models import ProposedChange as CliProposedChange
from ppc_agent_server.services.council import FinancialSnapshot
from ppc_agent_server.services.memory import MemoryEntry, memory_line
from ppc_agent_server.services.ro_format import ron as _ron
from ppc_agent_server.services.technician import (
    LCP_CRITICAL_MS,
    TechnicalSignals,
    TechnicianDirective,
    _day,
    _metric_value,
)

#: Cat de departe se uita jobul de noapte in memoria consiliului.
COUNCIL_MEMORY_DAYS = 7
#: Codurile veto-ului Tehnicianului, dupa ce opresc (``technician._SCOPES``).
MONEY_VETO_CODES = frozenset({"SITE_UNAVAILABLE", "CRITICAL_JOURNEY_BROKEN", "ATTRIBUTION_BROKEN"})
SPEND_VETO_CODES = frozenset({"MOBILE_LCP_CRITICAL"})
#: Ideile CFO-ului care cer bani (``council.IdeaKind``): taiate, inseamna "nu cheltuim in plus".
CFO_SPEND_CUTS = frozenset({"budget", "channel", "paid_targeting"})
#: Propunerile de noapte calculate pe conversii: fara tracking, sunt pe cifre false.
MONEY_MODULES = frozenset({"budget", "meta_liquidity"})
#: Cine opreste propunerile, in ``ProposedChange.decided_by``.
DECIDED_BY = "consiliu"
#: Codul intrarii care ridica o restrictie: ``lifted:<cheia restrictiei>``.
LIFT_PREFIX = "lifted:"
#: Restrictia pusa de CFO-ul de noapte, fara chat: contul a recazut pe pierdere.
CFO_NIGHT_CODE = "night_budget"

GuardKind = Literal["money_veto", "spend_freeze"]


@dataclass(frozen=True, slots=True)
class CouncilBlock:
    """O restrictie activa a consiliului: cine, de cand si de ce."""

    kind: GuardKind
    #: ``cto`` (Tehnicianul) sau ``cfo``.
    role: str
    #: Codul veto-ului sau felul ideii taiate de CFO.
    code: str
    since: datetime
    #: De ce - propozitia pe care o vede clientul pe propunerea oprita.
    reason: str


@dataclass(frozen=True, slots=True)
class CouncilConstraints:
    """Restrictiile consiliului pentru un client, in noaptea asta."""

    money_veto: CouncilBlock | None = None
    spend_freeze: CouncilBlock | None = None
    #: Restrictiile ridicate in noaptea asta (conditia de rediscutare s-a indeplinit):
    #: intrarile noi pentru memorie, ``lifted:<cheie>`` - le scrie jobul.
    lifted: tuple[MemoryEntry, ...] = ()
    #: Restrictiile puse in noaptea asta, fara chat (CFO-ul de noapte) - le scrie jobul.
    imposed: tuple[MemoryEntry, ...] = ()

    @property
    def active(self) -> bool:
        return self.money_veto is not None or self.spend_freeze is not None

    @property
    def growth_block(self) -> CouncilBlock | None:
        """Ce opreste cheltuiala in plus: veto-ul pe bani o opreste oricum."""
        return self.money_veto or self.spend_freeze

    def note(self) -> str:
        """Nota pentru jurnal si rezultatul jobului."""
        parts = []
        if self.money_veto is not None:
            parts.append(f"Veto pe bani: {self.money_veto.reason}")
        if self.spend_freeze is not None:
            parts.append(f"Bugetul nu crește: {self.spend_freeze.reason}")
        return " ".join(parts)


def _utc(value: datetime) -> datetime:
    # SQLite intoarce ore naive, dar sunt UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _lift_key(entry: MemoryEntry) -> str:
    """Ce ridica o ridicare: tot ce a taiat CFO-ul (aceeasi conditie), un veto dupa cod."""
    return "cfo" if entry.role == "cfo" else entry.code or ""


def _profitable_again(finances: FinancialSnapshot) -> str:
    """Cum a trecut contul testul CFO-ului - cu cifrele, pentru memorie."""
    cpa, target = finances.cpa, finances.target_cpa
    if cpa is not None and target is not None and cpa <= target:
        return f"CPA-ul contului a coborât la {_ron(cpa)} RON, sub ținta de {_ron(target)} RON"
    if finances.roas is not None:
        return (
            f"ROAS-ul contului a urcat la {_ron(finances.roas)}, peste pragul de "
            f"rentabilitate de {_ron(finances.break_even_roas)}"
        )
    return "contul e din nou rentabil"


def _losing(finances: FinancialSnapshot) -> str:
    """De ce nu mai e rentabil contul - cu cifrele, pentru memorie si pentru client."""
    cpa, target, roas = finances.cpa, finances.target_cpa, finances.roas
    if roas is not None and roas < finances.break_even_roas:
        return (
            f"ROAS-ul contului e {_ron(roas)}, sub pragul de rentabilitate de "
            f"{_ron(finances.break_even_roas)}"
        )
    if cpa is not None and target is not None and cpa > target:
        return f"CPA-ul contului e {_ron(cpa)} RON, peste ținta de {_ron(target)} RON"
    return "contul nu e rentabil"


def _night_cfo(finances: FinancialSnapshot, now: datetime) -> MemoryEntry:
    """Restrictia pusa de CFO-ul de noapte, scrisa ca decizia lui."""
    return MemoryEntry(
        at=now,
        role="cfo",
        topic="budget",
        decision=(
            f"a oprit automat creșterea bugetului în tura de noapte: {_losing(finances)}"
        ),
        code=CFO_NIGHT_CODE,
    )


def _lift(
    entry: MemoryEntry,
    signals: TechnicalSignals,
    finances: FinancialSnapshot | None,
    now: datetime,
) -> MemoryEntry | None:
    """Intrarea care ridica restrictia, cand conditia ei de rediscutare e indeplinita in date."""
    code = entry.code or ""
    decision: str | None = None
    if entry.role == "cto" and code in MONEY_VETO_CODES:
        evidence = signals.evidence
        if (
            evidence is not None
            and _utc(evidence.started_at) > _utc(entry.at)
            and evidence.failure_reason is None
        ):
            decision = (
                f"a ridicat veto-ul: testul E2E din {_day(evidence.started_at.date())} a trecut, "
                "conversiile ajung din nou la platforme"
            )
    elif entry.role == "cto" and code in SPEND_VETO_CODES:
        speed = signals.mobile_speed
        if (
            speed is not None
            and speed.lcp_ms is not None
            and _utc(speed.measured_at) > _utc(entry.at)
            and speed.lcp_ms <= LCP_CRITICAL_MS
        ):
            decision = (
                "a ridicat veto-ul: site-ul se încarcă acum pe mobil în "
                f"{_metric_value('lcp', speed.lcp_ms)} (LCP), sub pragul de 4 s"
            )
    elif entry.role == "cfo" and finances is not None and finances.status == "profitable":
        decision = f"a ridicat restricția pe buget: {_profitable_again(finances)}"
    if decision is None:
        return None
    return MemoryEntry(
        at=now,
        role=entry.role,
        topic=entry.topic,
        decision=decision,
        code=f"{LIFT_PREFIX}{_lift_key(entry)}",
    )


def council_constraints(
    memory: Sequence[MemoryEntry],
    technical: TechnicianDirective,
    signals: TechnicalSignals,
    *,
    now: datetime,
    finances: FinancialSnapshot | None = None,
) -> CouncilConstraints:
    """Restrictiile active: veto-ul de acum al Tehnicianului, apoi memoria consiliului.

    ``memory`` = deciziile consiliului (orice ordine); se folosesc doar cele cu cod, din
    ultimele :data:`COUNCIL_MEMORY_DAYS` zile. Cea mai recenta decizie de un fel castiga.
    O decizie invalidata deja (o ridicare de dupa ea) nu mai conteaza; una a carei conditie
    de rediscutare e indeplinita acum se ridica - ``lifted`` poarta intrarile de scris.
    ``finances`` = verdictul CFO-ului de azi: ridica taieturile CFO-ului cand contul e
    rentabil si, cand nu e si nicio restrictie a CFO-ului nu e activa, pune una
    (``imposed``). Fara el, CFO-ul nu judeca.
    """
    since = now - timedelta(days=COUNCIL_MEMORY_DAYS)
    recent = sorted(
        (entry for entry in memory if entry.code and _utc(entry.at) >= _utc(since)),
        key=lambda entry: _utc(entry.at),
        reverse=True,
    )
    # Cea mai recenta ridicare a fiecarei chei (``recent`` e de la nou la vechi).
    lifted_at: dict[str, datetime] = {}
    for entry in recent:
        code = entry.code or ""
        if code.startswith(LIFT_PREFIX):
            lifted_at.setdefault(code.removeprefix(LIFT_PREFIX), _utc(entry.at))
    lifts: list[MemoryEntry] = []
    money: CouncilBlock | None = None
    freeze: CouncilBlock | None = None
    live_code = technical.veto_code
    if live_code is not None and technical.veto_reason:
        reason = f"Tehnicianul a pus veto azi: {technical.veto_reason}"
        block_kind: GuardKind = "money_veto" if live_code in MONEY_VETO_CODES else "spend_freeze"
        live = CouncilBlock(block_kind, "cto", live_code, now, reason)
        if block_kind == "money_veto":
            money = live
        else:
            freeze = live
    cfo_active = False
    for entry in recent:
        code = entry.code or ""
        if entry.role == "cto" and code in MONEY_VETO_CODES | SPEND_VETO_CODES:
            kind: GuardKind = "money_veto" if code in MONEY_VETO_CODES else "spend_freeze"
        elif entry.role == "cfo" and code in CFO_SPEND_CUTS | {CFO_NIGHT_CODE}:
            kind = "spend_freeze"
        else:
            continue
        key = _lift_key(entry)
        invalidated = lifted_at.get(key)
        if invalidated is not None and invalidated >= _utc(entry.at):
            continue
        lift = _lift(entry, signals, finances, now)
        if lift is not None:
            lifts.append(lift)
            lifted_at[key] = _utc(now)
            continue
        cfo_active = cfo_active or entry.role == "cfo"
        block = CouncilBlock(kind, entry.role, code, entry.at, memory_line(entry, now))
        if kind == "money_veto" and money is None:
            money = block
        elif kind == "spend_freeze" and freeze is None:
            freeze = block
    # CFO-ul de noapte: contul a recazut si nimeni nu l-a oprit inca. Nu pe cifre false.
    imposed: list[MemoryEntry] = []
    if (
        finances is not None
        and finances.status == "unprofitable"
        and not cfo_active
        and money is None
    ):
        night = _night_cfo(finances, now)
        imposed.append(night)
        reason = memory_line(night, now)
        freeze = freeze or CouncilBlock("spend_freeze", "cfo", CFO_NIGHT_CODE, now, reason)
    return CouncilConstraints(
        money_veto=money, spend_freeze=freeze, lifted=tuple(lifts), imposed=tuple(imposed)
    )


# --- ce se face cu propunerile ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuardedChange:
    """O propunere a algoritmilor, dupa garda consiliului."""

    change: CliProposedChange
    #: De ce a oprit-o consiliul; ``None`` = merge la client (poate plafonata).
    blocked: str | None = None
    #: Bugetul zilnic propus de algoritm, cand consiliul l-a redus.
    capped_from: Decimal | None = None


def council_context(block: CouncilBlock, proposed: Decimal | None = None) -> dict[str, str]:
    """Contextul deciziei, in ``before``: ce restrictie, a cui, de cand."""
    context = {
        "restriction": block.kind,
        "role": block.role,
        "code": block.code,
        "since": _utc(block.since).isoformat(),
    }
    if proposed is not None:
        context["proposed_daily_budget"] = str(proposed)
    return context


def blocked_message(block: CouncilBlock) -> str:
    """Textul de pe o propunere oprita: motivul si ce urmeaza."""
    if block.kind == "money_veto":
        after = (
            "Bugetele nu se decid pe conversii false: jobul de noapte le propune din nou "
            "după ce testul E2E confirmă reparația."
        )
    else:
        after = "Cheltuiala nu crește până nu se ridică restricția."
    return f"Oprită de consiliu. {block.reason} {after}"


def guard_changes(
    changes: Sequence[CliProposedChange],
    constraints: CouncilConstraints,
    *,
    spend_cap: Decimal,
) -> list[GuardedChange]:
    """Aplica restrictiile pe propunerile de noapte.

    Veto pe bani: tot ce e calculat pe conversii (:data:`MONEY_MODULES`) se opreste.
    Cheltuiala inghetata: bugetele Thompson se reduc proportional pana cand totalul nu
    mai trece de ``spend_cap`` (bugetul zilnic aprobat al contului); sub el, raman.
    """
    money = constraints.money_veto
    if money is not None:
        message = blocked_message(money)
        return [
            GuardedChange(change, message if change.source_module in MONEY_MODULES else None)
            for change in changes
        ]
    freeze = constraints.spend_freeze
    budget = [change for change in changes if change.source_module == "budget"]
    total = sum((change.projected_daily_spend for change in budget), Decimal("0"))
    if freeze is None or total <= spend_cap:
        return [GuardedChange(change) for change in changes]

    factor = spend_cap / total
    guarded: list[GuardedChange] = []
    for change in changes:
        if change.source_module != "budget" or change.projected_daily_spend <= 0:
            guarded.append(GuardedChange(change))
            continue
        original = change.projected_daily_spend
        capped = (original * factor).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        note = (
            f"[Consiliu] Buget plafonat la {capped} RON/zi (algoritmul propunea {original}): "
            f"{freeze.reason} "
        )
        guarded.append(
            GuardedChange(
                change.model_copy(
                    update={
                        "before": {**change.before, "council": council_context(freeze, original)},
                        "after": {**change.after, "daily_budget": str(capped)},
                        "projected_daily_spend": capped,
                        "rationale": note + change.rationale,
                    }
                ),
                capped_from=original,
            )
        )
    return guarded
