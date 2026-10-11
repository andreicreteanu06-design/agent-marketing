"""Calificarea ulterioara din CRM: un lead in asteptare, calificat de vanzari mai tarziu."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent_server.models import AdPerformanceRecord
from ppc_agent_server.tracking.models import StandardizedConversion
from ppc_agent_server.tracking.qualification import ConversionQualifier
from tests_server.test_meta_capi import (  # noqa: F401
    _CapiStub,
    _client_with_pixel,
    _post,
    capi,
    meta_live,
)

_PENDING = {
    "event_id": "web_lead_crm_1",
    "event_type": "lead",
    "customer_email": "a@b.ro",
    "source_platform": "custom_web",
    "ad_id": "ad_77",
    "ad_platform": "meta",
    "lead_status": "pending",
}


def _status(status: str) -> dict[str, Any]:
    # CRM-ul trimite doar ID-ul si statusul; restul ramane cel salvat la prima primire.
    return {"event_id": "web_lead_crm_1", "source_platform": "custom_web", "lead_status": status}


def test_un_lead_in_asteptare_nu_e_inca_calificat() -> None:
    qualifier = ConversionQualifier(
        default_lead_value=100.0, objective=CampaignObjective.LEAD_GEN
    )
    result = qualifier.qualify(StandardizedConversion(client_id="1", **_PENDING))
    assert not result.qualified
    assert result.reason == "in asteptarea calificarii (CRM)"


def test_calificat_mai_tarziu_pleaca_doar_evenimentul_calificat(
    client: TestClient,
    auth_headers: dict[str, str],
    meta_live: None,  # noqa: F811
    capi: _CapiStub,  # noqa: F811
    session: Session,
) -> None:
    client_id = _client_with_pixel(client, auth_headers)

    first = _post(client, auth_headers, client_id, _PENDING, source="custom_web")
    assert (first["qualified"], first["meta_capi"]) == (False, None)
    assert capi.sent == []  # pixelul a trimis deja Lead-ul; serverul asteapta vanzarile

    later = _post(client, auth_headers, client_id, _status("qualified"), source="custom_web")
    assert later["requalified"] is True and later["qualified"] is True
    assert later["meta_capi"] == "sent"
    assert [call["payload"]["event_name"] for call in capi.sent] == ["SubmitApplication"]
    record = session.exec(
        select(AdPerformanceRecord).where(AdPerformanceRecord.ad_id == "ad_77")
    ).one()
    assert record.conversions == 1

    again = _post(client, auth_headers, client_id, _status("qualified"), source="custom_web")
    assert again["deduplicated"] is True and again["requalified"] is False
    assert len(capi.sent) == 1  # acelasi status: nimic nou


def test_descalificat_dupa_calificare_corecteaza_contoarele(
    client: TestClient,
    auth_headers: dict[str, str],
    meta_live: None,  # noqa: F811
    capi: _CapiStub,  # noqa: F811
    session: Session,
) -> None:
    client_id = _client_with_pixel(client, auth_headers)
    _post(client, auth_headers, client_id, _PENDING, source="custom_web")
    _post(client, auth_headers, client_id, _status("qualified"), source="custom_web")

    body = _post(client, auth_headers, client_id, _status("unqualified"), source="custom_web")

    assert body["requalified"] is True and body["qualified"] is False
    assert body["reason"] == "marcat de client: unqualified"
    record = session.exec(
        select(AdPerformanceRecord).where(AdPerformanceRecord.ad_id == "ad_77")
    ).one()
    assert record.conversions == 0
    assert len(capi.sent) == 1  # ce a plecat deja la Meta nu se poate retrage
