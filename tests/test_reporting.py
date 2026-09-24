"""Raportul saptamanal: cele trei straturi, rezumatul si verificarea cifrelor.

Fara retea si fara baza de date: furnizorii zilnici si deciziile sunt dubluri
mici. Ce se verifica e ce ar face un raport sa minta: bani adunati in float,
zile lipsa desenate ca zero, CPA zero in loc de nedefinit, o cifra inventata de
model, o decizie simulata prezentata ca aplicata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import pytest

from ppc_agent.copywriter.llm import LiveLLMClient, MockLLMClient
from ppc_agent.copywriter.models import ReportSummary, ReportSummarySpec
from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.providers.live.daily import DAILY_COLUMNS
from ppc_agent.providers.mock.ads import MockGoogleAdsProvider
from ppc_agent.services.reporting.extractors import (
    PlatformExtract,
    ReportWindow,
    extract_decisions,
    extract_platform_daily,
)
from ppc_agent.services.reporting.serving import WeeklyReportPayload, build_weekly_report
from ppc_agent.services.reporting.summary import (
    SUMMARY_SYSTEM_PROMPT,
    executive_summary,
    grounded,
)
from ppc_agent.services.reporting.transformers import (
    PeriodTotals,
    daily_series,
    normalize,
    pct_change,
    platform_totals,
    to_cents,
    totals,
)

_WEEK = ReportWindow(start=date(2026, 9, 14), end=date(2026, 9, 20))


def _row(
    day: str, cost: float, clicks: int, conversions: float, revenue: float = 0.0
) -> dict[str, Any]:
    return {
        "date": date.fromisoformat(day),
        "arm_id": "c1",
        "name": "Campanie",
        "clicks": clicks,
        "conversions": conversions,
        "cost": cost,
        "revenue": revenue,
    }


class _Daily:
    """Un furnizor live simulat: raporteaza zi cu zi din randurile primite."""

    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows
        self.calls: list[tuple[str, int, date | None]] = []

    def daily_campaign_performance(
        self, account_id: str, *, days: int, end_date: date | None = None
    ) -> pd.DataFrame:
        self.calls.append((account_id, days, end_date))
        if isinstance(self._rows, Exception):
            raise self._rows
        return pd.DataFrame(self._rows, columns=DAILY_COLUMNS)


class _Sources:
    def __init__(self, google: object, meta: object) -> None:
        self._google, self._meta = google, meta

    def google_ads(self) -> object:
        return self._google

    def meta(self) -> object:
        return self._meta


_ACCOUNTS = {"google_ads": "123", "meta_ads": "act_555"}


def _extract(google: object, meta: object, accounts: dict[str, str] = _ACCOUNTS) -> PlatformExtract:
    return extract_platform_daily(_Sources(google, meta), accounts=accounts, window=_WEEK)


@dataclass
class _Change:
    decided_at: datetime | None
    op: str = "PAUSE"
    resource: str = "meta_ad_set/1"
    rationale: str = "test"
    source_module: str = "autonomous_evaluator"
    projected_daily_spend: Decimal = Decimal("0")
    decided_by: str | None = "client@exemplu.ro"
    execution_result: dict[str, Any] | None = None


# --- extractors -------------------------------------------------------------


def test_saptamana_raportata_e_cea_incheiata_ieri() -> None:
    window = ReportWindow.last_complete_week(date(2026, 9, 21))
    assert (window.start, window.end, window.days) == (date(2026, 9, 14), date(2026, 9, 20), 7)
    assert (window.previous.start, window.previous.end) == (date(2026, 9, 7), date(2026, 9, 13))


def test_o_fereastra_inversata_e_refuzata() -> None:
    with pytest.raises(ValueError):
        ReportWindow(start=date(2026, 9, 20), end=date(2026, 9, 14))


def test_extractorul_cere_ambele_saptamani_de_la_fiecare_platforma() -> None:
    google, meta = _Daily([]), _Daily([])
    extract = _extract(google, meta)
    assert google.calls == [("123", 14, date(2026, 9, 20))]
    assert meta.calls == [("act_555", 14, date(2026, 9, 20))]
    assert extract.platforms == ["google_ads", "meta_ads"]
    assert extract.gaps == []


def test_un_furnizor_fara_serii_zilnice_devine_gol_de_date() -> None:
    extract = _extract(MockGoogleAdsProvider(), _Daily([]))
    assert extract.platforms == ["meta_ads"]
    assert any("Google Ads" in gap and "mock" in gap for gap in extract.gaps)


def test_un_cont_neconfigurat_devine_gol_de_date() -> None:
    extract = _extract(_Daily([]), _Daily([]), accounts={"google_ads": "", "meta_ads": "act_555"})
    assert extract.platforms == ["meta_ads"]
    assert any("nu e configurat" in gap for gap in extract.gaps)


def test_o_platforma_care_pica_devine_gol_nu_exceptie() -> None:
    extract = _extract(_Daily(ProviderError("token expirat")), _Daily([]))
    assert extract.platforms == ["meta_ads"]
    assert any("token expirat" in gap for gap in extract.gaps)


def test_deciziile_din_afara_saptamanii_se_ignora_iar_restul_vin_in_ordine() -> None:
    changes = [
        _Change(datetime(2026, 9, 18, 10, tzinfo=UTC), op="UPDATE"),
        _Change(datetime(2026, 9, 13, 23, tzinfo=UTC)),  # saptamana anterioara
        _Change(datetime(2026, 9, 15, 8, tzinfo=UTC)),
        _Change(None),  # executata, dar fara data - nu are loc intr-o cronologie
    ]
    records = extract_decisions(changes, _WEEK)
    assert [record.op for record in records] == ["PAUSE", "UPDATE"]


def test_o_decizie_simulata_nu_e_prezentata_ca_aplicata() -> None:
    changes = [
        _Change(datetime(2026, 9, 15, tzinfo=UTC), execution_result={"simulated": True}),
        _Change(datetime(2026, 9, 16, tzinfo=UTC), execution_result={"campaign_id": "1"}),
    ]
    assert [record.applied for record in extract_decisions(changes, _WEEK)] == [False, True]


def test_ziua_unei_decizii_se_citeste_in_utc() -> None:
    naive = datetime(2026, 9, 20, 23, 30)  # asa vine din SQLite: UTC, fara fus orar
    bucharest = datetime(2026, 9, 21, 1, 0, tzinfo=timezone(timedelta(hours=3)))  # 20 sept UTC
    records = extract_decisions([_Change(naive), _Change(bucharest)], _WEEK)
    assert len(records) == 2
    assert all(record.decided_at.tzinfo is not None for record in records)


# --- transformers -----------------------------------------------------------


def _frame(rows: list[dict[str, Any]], platform: str = "meta_ads") -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=DAILY_COLUMNS).assign(platform=platform)
    return normalize(raw)


def test_banii_se_aduna_exact_nu_in_float() -> None:
    frame = _frame([_row("2026-09-15", 0.1, 1, 0), _row("2026-09-16", 0.2, 1, 0)])
    assert 0.1 + 0.2 != 0.3  # de-asta
    assert totals(frame, _WEEK).spend_cents == 30
    assert to_cents(12.34) == 1234
    assert to_cents(float("nan")) == 0


def test_cpa_fara_conversii_e_nedefinit_nu_zero() -> None:
    period = PeriodTotals(spend_cents=2500, clicks=40, conversions=0.0, revenue_cents=0)
    assert period.cpa is None
    assert PeriodTotals(2500, 40, 4.0, 0).cpa == 6.25


def test_roas_nu_se_aplica_la_obiectivul_de_lead_uri() -> None:
    period = PeriodTotals(2500, 40, 4.0, 0, track_roas=False)
    assert period.roas is None
    assert period.value("revenue") is None
    assert PeriodTotals(2500, 40, 4.0, 10000).roas == 4.0


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(110.0, 100.0, 10.0), (90.0, 100.0, -10.0), (10.0, 0.0, None), (None, 5.0, None)],
)
def test_evolutia_procentuala(
    current: float | None, previous: float | None, expected: float | None
) -> None:
    """Fata de zero nu exista evolutie - nu e +100%."""
    assert pct_change(current, previous) == expected


def test_zilele_fara_livrare_apar_in_serie_cu_zero() -> None:
    frame = _frame([_row("2026-09-15", 25.0, 40, 2), _row("2026-09-18", 30.0, 50, 0)])
    series = daily_series(frame, _WEEK)

    assert [day for day, _ in series] == _WEEK.dates()
    by_day = dict(series)
    assert by_day[date(2026, 9, 14)].spend_cents == 0
    assert by_day[date(2026, 9, 14)].cpa is None
    assert by_day[date(2026, 9, 15)].cpa == 12.5
    assert by_day[date(2026, 9, 18)].cpa is None  # cheltuiala fara conversii


def test_platformele_care_au_raspuns_apar_si_fara_randuri() -> None:
    frame = _frame([_row("2026-09-15", 25.0, 40, 2)], platform="meta_ads")
    result = dict(platform_totals(frame, _WEEK, ["google_ads", "meta_ads"]))
    assert result["google_ads"].spend_cents == 0
    assert result["meta_ads"].spend_cents == 2500


# --- rezumatul --------------------------------------------------------------


class _Summarizer:
    def __init__(self, text: str | Exception) -> None:
        self._text = text
        self.specs: list[ReportSummarySpec] = []

    def generate_report_summary(self, spec: ReportSummarySpec) -> ReportSummary:
        self.specs.append(spec)
        if isinstance(self._text, Exception):
            raise self._text
        return ReportSummary(summary=self._text)


_FACTS = [
    "Cheltuiala: 175.00 RON (anterior: 160.00 RON; evolutie +9.4%).",
    "Conversii: 32 (anterior: 28; evolutie +14.3%).",
]


def test_acelasi_numar_scris_diferit_e_acelasi_numar() -> None:
    assert grounded("32.0 conversii si 175 RON", _FACTS)


def test_un_text_ai_cu_cifrele_din_fapte_e_acceptat() -> None:
    model = _Summarizer("Ai cheltuit 175.00 RON pentru 32 de conversii, cu 9.4% mai mult.")
    _, source, note = executive_summary(model, _FACTS, "sablon")
    assert source == "ai"
    assert note is None
    assert model.specs[0].system_prompt == SUMMARY_SYSTEM_PROMPT


def test_un_text_ai_cu_o_cifra_inventata_e_inlocuit() -> None:
    """Un client care prinde o cifra falsa nu mai crede nicio cifra din raport."""
    model = _Summarizer("Ai cheltuit 175.00 RON si ai economisit 999 RON.")
    text, source, note = executive_summary(model, _FACTS, "sablon")
    assert (text, source) == ("sablon", "template")
    assert note is not None and "nu exista in date" in note


def test_un_model_care_pica_lasa_rezumatul_din_cifre() -> None:
    text, source, note = executive_summary(
        _Summarizer(SetupRequiredError("Ollama nu raspunde")), _FACTS, "sablon"
    )
    assert (text, source) == ("sablon", "template")
    assert note is not None and "Ollama nu raspunde" in note


def test_fara_model_rezumatul_e_din_cifre_fara_nota() -> None:
    assert executive_summary(None, _FACTS, "sablon") == ("sablon", "template", None)


def test_un_model_care_repeta_sablonul_nu_e_etichetat_ai() -> None:
    assert executive_summary(_Summarizer("sablon"), _FACTS, "sablon")[1] == "template"


# --- serving ----------------------------------------------------------------


def _week_rows() -> list[dict[str, Any]]:
    current = [
        _row("2026-09-14", 20.0, 30, 2, 150.0),
        _row("2026-09-15", 25.0, 40, 3, 240.0),
        _row("2026-09-17", 30.0, 45, 0, 0.0),
        _row("2026-09-20", 25.5, 38, 5, 410.0),
    ]
    previous = [_row("2026-09-09", 50.0, 60, 4, 300.0), _row("2026-09-12", 40.0, 50, 2, 150.0)]
    return current + previous


def _report(**overrides: Any) -> WeeklyReportPayload:
    arguments: dict[str, Any] = {
        "client_account_id": 7,
        "currency": "RON",
        "window": _WEEK,
        "extract": _extract(_Daily([]), _Daily(_week_rows())),
        "decisions": [],
        "summarizer": None,
        "track_roas": True,
        "generated_at": datetime(2026, 9, 21, 6, tzinfo=UTC),
    }
    arguments.update(overrides)
    return build_weekly_report(**arguments)


def test_graficul_zilnic_are_cate_un_punct_pe_zi_gata_pentru_recharts() -> None:
    payload = _report().model_dump(mode="json")
    chart = payload["daily_performance_chart"]

    assert [point["date"] for point in chart] == [day.isoformat() for day in _WEEK.dates()]
    assert chart[0] == {
        "date": "2026-09-14",
        "spend": 20.0,
        "clicks": 30,
        "conversions": 2.0,
        "revenue": 150.0,
        "cpa": 10.0,
        "roas": 7.5,
    }
    assert chart[2]["spend"] == 0.0 and chart[2]["cpa"] is None  # zi fara livrare
    assert chart[3]["spend"] == 30.0 and chart[3]["cpa"] is None  # cheltuiala fara conversii
    json.dumps(payload)


def test_indicatorii_au_evolutia_si_sensul_bun() -> None:
    kpis = {kpi.key: kpi for kpi in _report().kpis}

    assert kpis["spend"].current == 100.5
    assert kpis["spend"].previous == 90.0
    assert kpis["spend"].change_pct == 11.7
    assert kpis["spend"].better_when == "neutral"
    assert kpis["cpa"].better_when == "lower"
    assert kpis["cpa"].current == 10.05  # 100.50 / 10 conversii
    assert kpis["conversions"].change_pct == 66.7


def test_fara_date_de_la_platforme_graficul_e_gol_nu_plin_de_zero() -> None:
    payload = _report(extract=_extract(MockGoogleAdsProvider(), MockGoogleAdsProvider()))
    assert payload.daily_performance_chart == []
    assert payload.kpis == []
    assert len(payload.data_gaps) == 2
    assert "nu exista date de performanta" in payload.executive_summary


def test_la_lead_uri_roas_si_venitul_sunt_null_nu_zero() -> None:
    payload = _report(track_roas=False)
    chart = payload.daily_performance_chart
    assert all(point.roas is None and point.revenue is None for point in chart)
    assert {kpi.key: kpi for kpi in payload.kpis}["roas"].current is None


def test_deciziile_ajung_in_jurnal_cu_descriere_si_sursa() -> None:
    decisions = extract_decisions(
        [
            _Change(datetime(2026, 9, 15, 9, tzinfo=UTC), op="PAUSE", resource="meta_ad_set/1"),
            _Change(
                datetime(2026, 9, 16, 9, tzinfo=UTC),
                op="UPDATE",
                resource="meta_ad_set/2",
                projected_daily_spend=Decimal("30.00"),
                source_module="budget",
                execution_result={"simulated": True},
            ),
        ],
        _WEEK,
    )
    log = _report(decisions=decisions).ai_decisions_log

    assert log[0].description == "Pauza pe meta_ad_set/1"
    assert log[0].source == "evaluatorul autonom"
    assert log[0].applied is True
    assert log[1].description == "Buget zilnic 30.00 RON pe meta_ad_set/2"
    assert log[1].applied is False


def test_rezumatul_din_cifre_foloseste_aceleasi_cifre_ca_indicatorii() -> None:
    payload = _report()
    assert payload.summary_source == "template"
    assert "100.50 RON" in payload.executive_summary
    assert "10 conversii" in payload.executive_summary


def test_rezumatul_acorda_singularul() -> None:
    """Textul ajunge la client: "1 decizie (1 pauza)", nu "1 decizii (1 pauze)"."""
    decisions = extract_decisions([_Change(datetime(2026, 9, 15, tzinfo=UTC))], _WEEK)
    rows = [_row("2026-09-15", 25.0, 40, 1)]
    payload = _report(decisions=decisions, extract=_extract(_Daily([]), _Daily(rows)))
    assert "1 conversie," in payload.executive_summary
    assert "1 decizie (1 pauza)" in payload.executive_summary


def test_un_rezumat_ai_respins_apare_in_golurile_de_date() -> None:
    payload = _report(summarizer=_Summarizer("Ai economisit 12345 RON."))
    assert payload.summary_source == "template"
    assert any("nu exista in date" in gap for gap in payload.data_gaps)


# --- clientul LLM -----------------------------------------------------------


def test_clientul_mock_intoarce_rezumatul_din_cifre() -> None:
    spec = ReportSummarySpec(system_prompt="x", facts=["a"], template="rezumat determinist")
    assert MockLLMClient().generate_report_summary(spec).summary == "rezumat determinist"


def test_clientul_live_cere_rezumatul_de_la_ollama() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"summary": "Saptamana a mers bine."})},
                "done": True,
            },
        )

    client = LiveLLMClient(model="llama3", transport=httpx.MockTransport(handler))
    spec = ReportSummarySpec(
        system_prompt=SUMMARY_SYSTEM_PROMPT, facts=["Cheltuiala: 10.00 RON."], template="t"
    )
    assert client.generate_report_summary(spec).summary == "Saptamana a mers bine."
    messages = sent[0]["messages"]
    assert messages[0]["content"] == SUMMARY_SYSTEM_PROMPT
    assert "Cheltuiala: 10.00 RON." in messages[1]["content"]
