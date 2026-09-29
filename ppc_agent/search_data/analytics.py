"""Google Analytics 4: ce fac vizitatorii dupa ce ajung pe site.

Complementar cu Search Console (``search_console.py``): GSC stie cum te vede
Google inainte de click, GA4 stie ce se intampla dupa - sesiuni, pagini vazute,
engagement. Impreuna raspund la "pagina asta pierde trafic din cauza Google sau
din cauza paginii?".

API: Google Analytics Data API v1beta, ``POST /properties/{id}:runReport``,
cu un refresh token emis pentru scope-ul ``analytics.readonly`` (vezi
``ppc_agent_server/routers/integrations.py`` pentru conectare).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent.search_data.google_oauth import ANALYTICS_SCOPE, exchange_refresh_token

_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
_DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class DailyTotals:
    """O zi din GA4, pe toata proprietatea."""

    day: date
    sessions: int
    pageviews: int
    #: Sesiunile "engaged" (peste 10 s, o conversie sau 2+ pagini). Rata se
    #: calculeaza din sume, nu din media ratelor zilnice.
    engaged_sessions: int


@dataclass(frozen=True, slots=True)
class LandingPageTotals:
    """O pagina de intrare, agregata pe intervalul cerut."""

    path: str
    sessions: int
    engaged_sessions: int


class AnalyticsDataClient:
    """Client de citire pentru rapoartele GA4 ale unei proprietati."""

    def __init__(
        self,
        *,
        property_id: str,
        client_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._property_id = property_id.strip().removeprefix("properties/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._timeout = timeout
        self._transport = transport
        self._cached_access_token: str | None = None

    def _access_token(self) -> str:
        if self._cached_access_token is None:
            self._cached_access_token = exchange_refresh_token(
                client_id=self._client_id,
                client_secret=self._client_secret,
                refresh_token=self._refresh_token,
                timeout=self._timeout,
                transport=self._transport,
                missing_message=(
                    "Conectarea la Google Analytics e incompleta: lipsesc client_id/"
                    "client_secret/refresh_token. Token-ul trebuie emis pentru scope-ul "
                    f"{ANALYTICS_SCOPE}."
                ),
            )
        return self._cached_access_token

    def run_report(
        self,
        *,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        metrics: list[str],
        order_by_metric: str | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, str]]:
        """Randurile raportului, cate un dictionar {dimensiune/metrica: valoare}.

        Raises:
            SetupRequiredError: proprietate nesetata, inexistenta sau fara acces
                pentru contul conectat - lucruri pe care le rezolva clientul.
            ProviderError: orice alt raspuns de eroare sau un raspuns malformat.
        """
        if not self._property_id:
            raise SetupRequiredError("Proprietatea GA4 nu e aleasa pentru acest client.")
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date.isoformat(), "endDate": end_date.isoformat()}],
            "dimensions": [{"name": name} for name in dimensions],
            "metrics": [{"name": name} for name in metrics],
            "limit": str(limit),
        }
        if order_by_metric:
            body["orderBys"] = [{"metric": {"metricName": order_by_metric}, "desc": True}]
        url = f"{_BASE_URL}/properties/{self._property_id}:runReport"
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise SetupRequiredError(f"Google Analytics Data API nu raspunde: {exc}") from exc

        if response.status_code == 403:
            raise SetupRequiredError(
                f"Google Analytics refuza accesul la proprietatea {self._property_id}. "
                "Verifica daca contul conectat o poate vedea si daca 'Google Analytics "
                "Data API' e activat in proiectul Cloud."
            )
        if response.status_code == 404:
            raise SetupRequiredError(
                f"Proprietatea GA4 {self._property_id} nu exista. Alege-o din nou din Integrari."
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Google Analytics Data API a raspuns {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderError(f"raspuns GA4 invalid: {exc}") from exc

        names = [header["name"] for header in payload.get("dimensionHeaders", [])] + [
            header["name"] for header in payload.get("metricHeaders", [])
        ]
        rows: list[dict[str, str]] = []
        for raw in payload.get("rows") or []:
            values = [cell.get("value", "") for cell in raw.get("dimensionValues", [])] + [
                cell.get("value", "") for cell in raw.get("metricValues", [])
            ]
            if len(values) == len(names):
                rows.append(dict(zip(names, values, strict=True)))
        return rows

    def daily_totals(self, *, start_date: date, end_date: date) -> list[DailyTotals]:
        """Sesiunile, vizualizarile si sesiunile engaged, zi de zi."""
        rows = self.run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=["date"],
            metrics=["sessions", "screenPageViews", "engagedSessions"],
        )
        totals: list[DailyTotals] = []
        for row in rows:
            try:
                day = datetime.strptime(row["date"], "%Y%m%d").date()
            except ValueError:
                continue
            totals.append(
                DailyTotals(
                    day=day,
                    sessions=_int(row["sessions"]),
                    pageviews=_int(row["screenPageViews"]),
                    engaged_sessions=_int(row["engagedSessions"]),
                )
            )
        return totals

    def channel_sessions(self, *, start_date: date, end_date: date) -> dict[str, int]:
        """Sesiunile pe grupul de canale implicit GA4 ("Paid Social", "Organic Search"...)."""
        rows = self.run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=["sessionDefaultChannelGroup"],
            metrics=["sessions"],
        )
        return {
            row["sessionDefaultChannelGroup"]: _int(row["sessions"])
            for row in rows
            if row["sessionDefaultChannelGroup"]
        }

    def landing_pages(
        self, *, start_date: date, end_date: date, limit: int = 50
    ) -> list[LandingPageTotals]:
        """Paginile pe care intra vizitatorii, cele mai vizitate primele."""
        rows = self.run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=["landingPage"],
            metrics=["sessions", "engagedSessions"],
            order_by_metric="sessions",
            limit=limit,
        )
        return [
            LandingPageTotals(
                path=row["landingPage"],
                sessions=_int(row["sessions"]),
                engaged_sessions=_int(row["engagedSessions"]),
            )
            for row in rows
            # "(not set)" = sesiuni fara pagina de intrare cunoscuta; nu e o pagina.
            if row["landingPage"] and row["landingPage"] != "(not set)"
        ]


def _int(value: str) -> int:
    try:
        return round(float(value))
    except ValueError:
        return 0
