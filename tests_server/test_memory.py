"""Memoria consiliului: ce se tine minte, cum se comprima si cum revine in deliberare.

Doua sesiuni la distanta de doua saptamani: prima scrie in memorie (ce a taiat
CFO-ul), a doua o primeste ca Context Istoric - in faptele fiecarui agent si in
raspunsul Reginei.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    MemoryStream,
    ProposedChange,
)
from ppc_agent_server.services.council import (
    CFO_SYSTEM_PROMPT,
    CHAIR_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
    QueenCouncil,
    memories_from_reply,
)
from ppc_agent_server.services.memory import (
    HISTORY_RULE,
    MemoryEntry,
    compress,
    memory_line,
    recall_for,
    relative_when,
)
from ppc_agent_server.services.queen_signals import DbMemory
from ppc_agent_server.services.researcher import RESEARCHER_SYSTEM_PROMPT
from ppc_agent_server.services.technician import TECHNICIAN_SYSTEM_PROMPT
from tests_server.test_jobs_tasks import _client_account
from tests_server.test_queen_agent import NOW
from tests_server.test_queen_council import (
    LOSING,
    _CouncilVoice,
    _directive,
    _finances,
    _Static,
)
from tests_server.test_queen_router import signed_in  # noqa: F401 - fixture

BUDGET = "Merită să cresc bugetul?"


class _Memory:
    """Memoria in RAM: ce s-a scris, in ordinea scrierii."""

    def __init__(self, entries: Sequence[MemoryEntry] = ()) -> None:
        self.entries = list(entries)
        self.written: list[MemoryEntry] = []

    def recall(self, client_account_id: int, limit: int = 5) -> list[MemoryEntry]:
        return sorted(self.entries, key=lambda entry: entry.at, reverse=True)[:limit]

    def remember(self, client_account_id: int, entries: Sequence[MemoryEntry]) -> None:
        self.written.extend(entries)
        self.entries.extend(entries)


class _Broken:
    def recall(self, client_account_id: int, limit: int = 5) -> list[MemoryEntry]:
        raise RuntimeError("baza de date indisponibila")

    def remember(self, client_account_id: int, entries: Sequence[MemoryEntry]) -> None:
        raise RuntimeError("baza de date indisponibila")


def _council(
    memory: _Memory | _Broken, *, now: datetime = NOW, finances: object = None, voice: object = None
) -> QueenCouncil:
    return QueenCouncil(
        _Static(finances or LOSING),  # type: ignore[arg-type]
        memory=memory,
        voice=voice,  # type: ignore[arg-type]
        clock=lambda: now,
    )


CFO_CUT = MemoryEntry(
    at=NOW - timedelta(days=14),
    role="cfo",
    topic="budget",
    decision="a tăiat creșterea bugetului: contul nu e rentabil",
    observation="CPA-ul era 95 RON, peste ținta de 80 RON",
)


# --- formularea ----------------------------------------------------------------------------------


def test_compression_keeps_the_first_sentence_under_the_limit() -> None:
    assert compress("Contul nu e rentabil: CPA 95,5 RON. Restul nu conteaza.") == (
        "Contul nu e rentabil: CPA 95,5 RON"
    )
    assert compress("cuvant " * 80, limit=30).endswith("…")
    assert len(compress("cuvant " * 80, limit=30)) <= 30


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, "Azi"), (1, "Ieri"), (3, "Acum 3 zile"), (9, "Acum o săptămână"),
     (14, "Acum 2 săptămâni"), (40, "Acum o lună"), (95, "Acum 3 luni")],
)
def test_relative_time_reads_like_a_person(days: int, expected: str) -> None:
    naive = (NOW - timedelta(days=days)).replace(tzinfo=None)  # asa vin din SQLite

    assert relative_when(naive, NOW) == expected


def test_each_outcome_has_its_own_line() -> None:
    three_days, yesterday = NOW - timedelta(days=3), NOW - timedelta(days=1)
    rejected = MemoryEntry(
        three_days, "cfo", "budget", "Creșterea bugetului pe Meta", outcome="rejected"
    )
    failed = MemoryEntry(
        yesterday, "queen", "creative", "Rescrierea reclamei", "Meta a răspuns 400", "failed"
    )

    # "CPA" ramane cu majuscule: prima litera se micsoreaza doar cand nu e acronim.
    assert memory_line(CFO_CUT, NOW) == (
        "Acum 2 săptămâni, CFO-ul a tăiat creșterea bugetului: contul nu e rentabil; "
        "atunci, CPA-ul era 95 RON, peste ținta de 80 RON."
    )
    assert memory_line(rejected, NOW) == (
        "Acum 3 zile, ai respins propunerea: creșterea bugetului pe Meta."
    )
    assert memory_line(failed, NOW) == (
        "Ieri, aplicarea a eșuat: rescrierea reclamei; eroarea: Meta a răspuns 400."
    )


def test_the_reply_cites_the_same_topic_from_a_past_session_only() -> None:
    today = MemoryEntry(NOW, "queen", "budget", "a decis: nu acum")

    assert recall_for([today, CFO_CUT], "budget", NOW) is CFO_CUT
    assert recall_for([CFO_CUT], "creative", NOW) is None


# --- ce se tine minte ---------------------------------------------------------------------------


def test_a_budget_cut_is_remembered_with_who_decided_what() -> None:
    reply = _council(_Memory()).evaluate_client_query(BUDGET, _directive())

    entries = memories_from_reply(BUDGET, reply.ruling, _snapshot(LOSING), None, None, at=NOW)

    assert [(entry.role, entry.topic) for entry in entries] == [
        ("cfo", "budget"),
        ("queen", "budget"),
    ]
    assert entries[0].decision == "a tăiat creșterea bugetului, pentru că contul nu e rentabil"
    assert entries[0].observation.startswith("CPA-ul e ")
    assert entries[1].decision == (
        f"a răspuns «Nu acum: contul nu e rentabil» la întrebarea «{BUDGET}»"
    )


def test_a_question_that_decides_nothing_leaves_no_trace() -> None:
    reply = _council(_Memory(), finances=_finances()).evaluate_client_query(
        "Cine e clientul meu ideal?", _directive()
    )

    snapshot = _snapshot(_finances())
    assert memories_from_reply("Cine?", reply.ruling, snapshot, None, None, at=NOW) == []


def _snapshot(signals: object) -> object:
    from ppc_agent_server.services.council import build_financial_snapshot

    return build_financial_snapshot(signals)  # type: ignore[arg-type]


# --- memoria in consiliu --------------------------------------------------------------------------


def test_every_agent_prompt_asks_to_check_the_history() -> None:
    for prompt in (
        STRATEGIST_SYSTEM_PROMPT,
        CFO_SYSTEM_PROMPT,
        CHAIR_SYSTEM_PROMPT,
        TECHNICIAN_SYSTEM_PROMPT,
        RESEARCHER_SYSTEM_PROMPT,
    ):
        assert HISTORY_RULE in prompt
        # Regula e printre reguli, inaintea vocii.
        assert prompt.index(HISTORY_RULE) < prompt.index("VOCEA (regulile de mai sus")


def test_the_history_reaches_every_member_and_the_synthesis() -> None:
    voice = _CouncilVoice()
    _council(_Memory([CFO_CUT]), voice=voice).evaluate_client_query(BUDGET, _directive())

    line = "Acum 2 săptămâni, CFO-ul a tăiat creșterea bugetului"
    for role in ("strategist", "cfo", "chair"):
        prompt = voice.prompt(role)
        assert "CONTEXT ISTORIC (memoria consiliului):" in prompt
        assert line in prompt


def test_two_sessions_two_weeks_apart_the_queen_remembers() -> None:
    memory = _Memory()

    first = _council(memory).evaluate_client_query(BUDGET, _directive())
    assert [entry.role for entry in memory.written] == ["cfo", "queen"]
    later = _council(memory, now=NOW + timedelta(days=14)).evaluate_client_query(
        BUDGET, _directive()
    )

    assert "Acum 2 săptămâni" not in first.reply
    assert later.reply.startswith(later.ruling.decision)
    remembered = "Țin minte: acum 2 săptămâni, CFO-ul a tăiat creșterea bugetului, pentru că"
    assert remembered in later.reply
    assert later.history[0].startswith("Acum 2 săptămâni, CFO-ul a tăiat")
    # Si a doua sesiune se scrie; dedupe-ul pe 7 zile e in DbMemory (testat mai jos).
    assert len(memory.written) == 4


def test_a_broken_memory_never_breaks_the_chat() -> None:
    reply = _council(_Broken()).evaluate_client_query(BUDGET, _directive())

    assert reply.reply.startswith("Nu acum")
    assert reply.history == []


# --- memoria in baza de date ----------------------------------------------------------------------


def test_the_same_decision_is_not_written_twice_within_a_week(session: Session) -> None:
    account = _client_account(session)
    memory = DbMemory(session, clock=lambda: NOW)
    cut = MemoryEntry(NOW - timedelta(days=10), "cfo", "budget", "a tăiat creșterea bugetului")

    memory.remember(account.id or 0, [cut])
    again = MemoryEntry(NOW - timedelta(days=5), "cfo", "budget", cut.decision)
    memory.remember(account.id or 0, [again])
    memory.remember(account.id or 0, [MemoryEntry(NOW, "cfo", "budget", cut.decision)])

    rows = session.exec(select(MemoryStream)).all()
    # 10 zile -> scris; 5 zile (la 5 de prima) -> sarit; azi (la 10 de prima) -> scris.
    assert len(rows) == 2


def test_recall_merges_council_memory_with_rejected_and_failed_proposals(
    session: Session,
) -> None:
    account = _client_account(session)
    other = _client_account(session)
    memory = DbMemory(session, clock=lambda: NOW)
    memory.remember(account.id or 0, [CFO_CUT])
    memory.remember(other.id or 0, [MemoryEntry(NOW, "cto", "budget", "a pus veto: alt client")])
    for days, status, rationale in (
        (2, ChangeStatus.REJECTED, "Creșterea bugetului pe campania de service."),
        (6, ChangeStatus.FAILED, "Rescrierea reclamei cu timp salvat."),
        (60, ChangeStatus.REJECTED, "Prea veche, nu mai conteaza."),
        (1, ChangeStatus.EXECUTED, "A mers, nu e un esec."),
    ):
        session.add(
            ProposedChange(
                client_account_id=account.id or 0,
                op=ChangeOp.UPDATE,
                resource="meta_ad/1",
                resource_type="ad_copy" if "Rescrierea" in rationale else "keyword_budget",
                projected_daily_spend=Decimal("0"),
                rationale=rationale,
                source_module="queen_agent" if "Rescrierea" in rationale else "ppc_agent",
                status=status,
                created_at=NOW - timedelta(days=days),
                decided_at=NOW - timedelta(days=days),
                error_message="Meta a răspuns 400." if status == ChangeStatus.FAILED else None,
            )
        )
    session.commit()

    entries = memory.recall(account.id or 0)

    assert [(entry.role, entry.topic, entry.outcome) for entry in entries] == [
        ("cfo", "budget", "rejected"),
        ("queen", "creative", "failed"),
        ("cfo", "budget", "decided"),
    ]
    assert entries[0].decision == "Creșterea bugetului pe campania de service"
    assert entries[1].observation == "Meta a răspuns 400"


# --- ruta -----------------------------------------------------------------------------------------

Signed = tuple[TestClient, FastAPI, dict[str, str], int]


def test_the_memory_route_shows_the_full_history(signed_in: Signed, session: Session) -> None:  # noqa: F811
    client, _, headers, account_id = signed_in
    DbMemory(session).remember(
        account_id,
        [MemoryEntry(datetime.now(tz=UTC) - timedelta(days=14), "cfo", "budget", CFO_CUT.decision)],
    )

    response = client.get("/api/v1/queen/memory", headers=headers)

    assert response.status_code == 200, response.text
    [record] = response.json()
    assert (record["agent_role"], record["outcome"]) == ("cfo", "decided")
    assert record["line"] == (
        "Acum 2 săptămâni, CFO-ul a tăiat creșterea bugetului: contul nu e rentabil."
    )
    assert client.get("/api/v1/queen/memory").status_code == 401


def test_a_chat_about_money_is_written_to_memory(signed_in: Signed, session: Session) -> None:  # noqa: F811
    client, _, headers, account_id = signed_in

    response = client.post("/api/v1/queen/chat", headers=headers, json={"message": BUDGET})

    assert response.status_code == 200, response.text
    query = select(MemoryStream).where(MemoryStream.client_account_id == account_id)
    rows = session.exec(query).all()
    # Client nou, fara conversii: CFO-ul taie cresterea bugetului, Regina decide "nu acum".
    assert [row.agent_role for row in rows] == ["cfo", "queen"]
    assert rows[0].decision.startswith("a tăiat creșterea bugetului, pentru că")
    assert rows[1].decision.endswith(f"la întrebarea «{BUDGET}»")
