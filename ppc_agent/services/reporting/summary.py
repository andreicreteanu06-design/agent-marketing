"""Rezumatul executiv: fapte exacte, un text din cifre, si - optional - textul unui model.

Un rezumat scris de un model de limbaj suna mai bine decat unul din sablon, dar
un model poate inventa o cifra, iar un client care prinde o cifra falsa intr-un
raport nu mai crede nicio cifra din el. De-asta:

1. **Faptele se formuleaza aici**, cu cifrele deja calculate. Modelul le
   reformuleaza; nu calculeaza nimic.
2. **Orice numar din textul modelului trebuie sa existe in fapte.** Altfel
   textul se arunca, ramane rezumatul din cifre, iar motivul ajunge in golurile
   de date ale raportului.
3. **Rezumatul din cifre exista mereu** si e ce vede clientul cand modelul
   lipseste, pica sau inventeaza.

Limita verificarii, spusa deschis: confirma ca un numar EXISTA in fapte, nu ca
sta langa eticheta corecta. Un model care scrie "CPA 32" cand 32 e numarul de
conversii trece de ea.

Cifrele se scriu cu punct zecimal si fara separator de mii, peste tot - in fapte,
in rezumat si in ce i se cere modelului. Un "1.250" romanesc (o mie doua sute
cincizeci) ar fi citit altfel de verificare decat de client.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Literal, Protocol

from ppc_agent.copywriter.models import ReportSummary, ReportSummarySpec
from ppc_agent.services.reporting.extractors import DecisionRecord, ReportWindow
from ppc_agent.services.reporting.transformers import KpiChange, PeriodTotals

SummarySource = Literal["ai", "template"]

SUMMARY_SYSTEM_PROMPT = (
    "Esti analistul PPC al unei agentii si scrii rezumatul executiv al raportului "
    "saptamanal pentru client, in limba romana: 3-4 propozitii, ton profesionist si "
    "direct, fara jargon. Folosesti EXCLUSIV cifrele din faptele primite, scrise exact "
    "ca acolo, cu punct zecimal: nu calcula cifre noi, nu rotunji, nu inventa procente, "
    "cauze sau recomandari care nu reies din fapte. Daca o metrica e nedefinita, spune "
    "ca nu se poate calcula, fara sa dai o cifra. Raspunde strict in JSON: "
    '{"summary": "<textul>"}.'
)

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

#: Singular si plural - textul ajunge la client, "1 pauze" nu are ce cauta acolo.
_OP_WORDS = {
    "PAUSE": ("pauza", "pauze"),
    "UPDATE": ("schimbare de buget", "schimbari de buget"),
    "CREATE": ("adaugire", "adaugiri"),
    "CREATE_CAMPAIGN": ("lansare de campanie", "lansari de campanii"),
}


def _count(value: float, singular: str, plural: str) -> str:
    """``1 conversie``, ``2 conversii``, ``2.5 conversii``."""
    return f"{fmt_number(value)} {singular if value == 1 else plural}"


class ReportSummarizer(Protocol):
    """Ce stie sa scrie un rezumat. ``BaseLLMClient`` il satisface ca atare."""

    def generate_report_summary(self, spec: ReportSummarySpec) -> ReportSummary: ...


def fmt_money(value: float | None, currency: str) -> str:
    return "nedefinit" if value is None else f"{value:.2f} {currency}"


def fmt_number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_change(change: float | None) -> str:
    return "nu se poate calcula" if change is None else f"{change:+.1f}%"


def _decision_counts(decisions: list[DecisionRecord]) -> str:
    counts = Counter(record.op for record in decisions if record.applied)
    return ", ".join(
        _count(count, *_OP_WORDS.get(op, (op.lower(), op.lower())))
        for op, count in counts.items()
    )


def build_facts(
    *,
    window: ReportWindow,
    currency: str,
    current: PeriodTotals,
    previous: PeriodTotals,
    changes: list[KpiChange],
    decisions: list[DecisionRecord],
    gaps: list[str],
    has_data: bool,
) -> list[str]:
    """Faptele saptamanii, fiecare o propozitie cu cifrele exacte."""
    by_key = {change.key: change for change in changes}
    prior = window.previous
    facts = [
        f"Perioada raportata: {window.start.isoformat()} - {window.end.isoformat()} "
        f"({window.days} zile); comparatie cu {prior.start.isoformat()} - "
        f"{prior.end.isoformat()}."
    ]
    if has_data:
        facts.extend(
            [
                f"Cheltuiala: {fmt_money(current.spend, currency)} (anterior: "
                f"{fmt_money(previous.spend, currency)}; evolutie "
                f"{fmt_change(by_key['spend'].change_pct)}).",
                f"Conversii: {fmt_number(current.conversions)} (anterior: "
                f"{fmt_number(previous.conversions)}; evolutie "
                f"{fmt_change(by_key['conversions'].change_pct)}).",
                (
                    f"CPA: {fmt_money(current.cpa, currency)} (anterior: "
                    f"{fmt_money(previous.cpa, currency)}; evolutie "
                    f"{fmt_change(by_key['cpa'].change_pct)})."
                    if current.cpa is not None
                    else "CPA: nedefinit - nicio conversie in perioada."
                ),
                f"Click-uri: {current.clicks} (anterior: {previous.clicks}; evolutie "
                f"{fmt_change(by_key['clicks'].change_pct)}).",
            ]
        )
        if current.track_roas:
            now = fmt_number(current.roas) if current.roas is not None else "nedefinit"
            before = fmt_number(previous.roas) if previous.roas is not None else "nedefinit"
            facts.append(
                f"ROAS: {now} (anterior: {before}; evolutie "
                f"{fmt_change(by_key['roas'].change_pct)})."
            )
        else:
            facts.append("ROAS: nu se aplica - obiectivul contului e generarea de lead-uri.")
    else:
        facts.append("Nu exista date de performanta de la platforme pentru aceasta perioada.")

    applied = [record for record in decisions if record.applied]
    simulated = len(decisions) - len(applied)
    facts.append(
        f"Decizii aplicate de platforma: {len(applied)}"
        + (f" ({_decision_counts(decisions)})." if applied else ".")
    )
    if simulated:
        facts.append(
            f"Decizii doar marcate ca executate, fara aplicare pe platforma: {simulated}."
        )
    facts.extend(f"Date lipsa: {gap}." for gap in gaps)
    return facts


def template_summary(
    *,
    window: ReportWindow,
    currency: str,
    current: PeriodTotals,
    previous: PeriodTotals,
    decisions: list[DecisionRecord],
    gaps: list[str],
    has_data: bool,
) -> str:
    """Rezumatul din cifre - determinist, fara model."""
    period = f"{window.start.isoformat()} - {window.end.isoformat()}"
    applied = [record for record in decisions if record.applied]
    if not has_data:
        sentences = [
            f"Pentru perioada {period} nu exista date de performanta de la platformele "
            "de reclame, deci raportul nu poate spune cat s-a cheltuit sau ce a adus."
        ]
    else:
        cpa = (
            f"un CPA de {fmt_money(current.cpa, currency)}"
            if current.cpa is not None
            else "fara nicio conversie, deci fara CPA"
        )
        sentences = [
            f"In perioada {period} s-au cheltuit {fmt_money(current.spend, currency)} pentru "
            f"{_count(current.conversions, 'conversie', 'conversii')}, {cpa}.",
            f"In saptamana anterioara: {fmt_money(previous.spend, currency)} si "
            f"{_count(previous.conversions, 'conversie', 'conversii')}.",
        ]
        if current.track_roas and current.roas is not None:
            sentences.append(f"ROAS-ul a fost {fmt_number(current.roas)}.")
    sentences.append(
        f"Platforma a aplicat {_count(len(applied), 'decizie', 'decizii')} "
        f"({_decision_counts(decisions)})."
        if applied
        else "Platforma nu a aplicat nicio decizie in aceasta perioada."
    )
    if gaps:
        sentences.append(f"Atentie, lipsesc date: {'; '.join(gaps)}.")
    return " ".join(sentences)


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(token.replace(",", ".")) for token in _NUMBER.findall(text)}


def grounded(text: str, facts: list[str]) -> bool:
    """Adevarat daca orice numar din ``text`` apare si in ``facts``.

    Compara VALORI, nu siruri: "32" si "32.0" sunt acelasi numar.
    """
    return _numbers(text) <= _numbers(" ".join(facts))


def executive_summary(
    summarizer: ReportSummarizer | None, facts: list[str], template: str
) -> tuple[str, SummarySource, str | None]:
    """Rezumatul final, sursa lui si - daca modelul a fost respins - motivul.

    Returns:
        ``(text, "ai" | "template", nota pentru golurile de date sau None)``.
    """
    if summarizer is None:
        return template, "template", None
    spec = ReportSummarySpec(system_prompt=SUMMARY_SYSTEM_PROMPT, facts=facts, template=template)
    try:
        text = summarizer.generate_report_summary(spec).summary.strip()
    except Exception as exc:
        return (
            template,
            "template",
            f"rezumatul AI indisponibil ({type(exc).__name__}: {exc}) - s-a folosit "
            "rezumatul din cifre",
        )
    if not text or text == template:
        return template, "template", None
    if not grounded(text, facts):
        return (
            template,
            "template",
            "rezumatul AI continea cifre care nu exista in date - a fost inlocuit cu "
            "rezumatul din cifre",
        )
    return text, "ai", None
