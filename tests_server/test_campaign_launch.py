"""Lansarea de campanii prin poarta de aprobare.

Doua jumatati, testate separat:

- payload-urile Meta (functii pure) - aici se verifica tot ce ar da eroare
  dura la primul apel real: campurile obligatorii din v23-v25, statusul PAUSED
  pe toate obiectele, bugetul in unitati minime;
- ``propose_launch`` - care NU trebuie sa vorbeasca cu Meta deloc. Invariantul
  e verificat direct: ``httpx.AsyncClient`` e inlocuit cu unul care pica testul
  la orice cerere.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.providers.meta_campaign import (
    LAUNCH_STATUS,
    MetaLaunchSpec,
    ad_fields,
    adset_fields,
    campaign_fields,
    creative_fields,
    normalize_ad_account_id,
)
from ppc_agent.services.execution_engine import resolve_target
from ppc_agent_server.models import (
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.routers.campaigns import get_creative_review


def _spec(**overrides: Any) -> MetaLaunchSpec:
    fields: dict[str, Any] = {
        "campaign_name": "Service Auto - Vanzari",
        "objective": CampaignObjective.SALES,
        "daily_budget": Decimal("25.00"),
        "pixel_id": "1234567890",
        "custom_event_type": "PURCHASE",
        "page_id": "9876543210",
        "target_url": "https://exemplu.ro/oferta",
        "headline": "Revizie completa in 24h",
        "primary_text": "Programeaza revizia online si primesti diagnoza gratuita.",
        "image_url": "https://cdn.exemplu.ro/reclama.jpg",
        "country": "RO",
        "call_to_action": "SHOP_NOW",
    }
    fields.update(overrides)
    return MetaLaunchSpec(**fields)


# --- payload-urile Meta -----------------------------------------------------


def test_campania_are_campurile_fara_de_care_meta_refuza_crearea() -> None:
    fields = campaign_fields(_spec())
    assert fields["objective"] == "OUTCOME_SALES"
    assert fields["status"] == "PAUSED"
    assert fields["special_ad_categories"] == "[]"
    # Obligatoriu din v24 cand bugetul sta pe ad set - altfel eroarea 4834011.
    assert fields["is_adset_budget_sharing_enabled"] == "false"
    assert "daily_budget" not in fields  # bugetul e pe ad set, nu pe campanie


def test_obiectivul_de_lead_uri_da_outcome_leads() -> None:
    spec = _spec(objective=CampaignObjective.LEAD_GEN, custom_event_type="LEAD")
    assert campaign_fields(spec)["objective"] == "OUTCOME_LEADS"


def test_ad_set_ul_are_payload_ul_complet() -> None:
    fields = adset_fields(_spec(), campaign_id="camp_123", daily_budget_minor=2500)

    assert fields["campaign_id"] == "camp_123"
    assert fields["status"] == "PAUSED"
    assert fields["daily_budget"] == "2500"
    assert fields["billing_event"] == "IMPRESSIONS"
    assert fields["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert fields["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
    assert fields["destination_type"] == "WEBSITE"
    assert json.loads(fields["promoted_object"]) == {
        "pixel_id": "1234567890",
        "custom_event_type": "PURCHASE",
    }
    targeting = json.loads(fields["targeting"])
    assert targeting["geo_locations"] == {"countries": ["RO"]}
    # Obligatoriu din v23 la crearea unui ad set.
    assert targeting["targeting_automation"] == {"advantage_audience": 1}
    # Cu advantage_audience=1, Meta respinge age_max sub 65 - deci nu trimitem varste.
    assert "age_min" not in targeting and "age_max" not in targeting


def test_toate_obiectele_create_pornesc_oprite() -> None:
    """Daca doar campania ar fi oprita, activarea ei ar porni instant si restul."""
    spec = _spec()
    assert LAUNCH_STATUS == "PAUSED"
    assert campaign_fields(spec)["status"] == "PAUSED"
    assert adset_fields(spec, campaign_id="c", daily_budget_minor=1)["status"] == "PAUSED"
    assert ad_fields(spec, adset_id="a", creative_id="k")["status"] == "PAUSED"


def test_creative_ul_leaga_textul_imaginea_si_pagina() -> None:
    story = json.loads(creative_fields(_spec(), image_hash="hash_abc")["object_story_spec"])
    assert story["page_id"] == "9876543210"
    link_data = story["link_data"]
    assert link_data["link"] == "https://exemplu.ro/oferta"
    assert link_data["message"].startswith("Programeaza revizia")
    assert link_data["name"] == "Revizie completa in 24h"
    assert link_data["image_hash"] == "hash_abc"
    assert link_data["call_to_action"]["type"] == "SHOP_NOW"


def test_diacriticele_trec_neescapate() -> None:
    story = creative_fields(_spec(headline="Revizie în 24 de ore"), image_hash="h")
    assert "Revizie în 24 de ore" in story["object_story_spec"]


def test_anuntul_se_leaga_de_creative_prin_id() -> None:
    fields = ad_fields(_spec(), adset_id="adset_456", creative_id="creative_321")
    assert fields["adset_id"] == "adset_456"
    assert json.loads(fields["creative"]) == {"creative_id": "creative_321"}


@pytest.mark.parametrize(
    ("raw", "expected"), [("act_123", "act_123"), ("123", "act_123"), (" act_9 ", "act_9")]
)
def test_contul_de_reclame_ajunge_in_forma_graph_api(raw: str, expected: str) -> None:
    assert normalize_ad_account_id(raw) == expected


def test_un_cont_nenumeric_e_refuzat() -> None:
    with pytest.raises(ValueError, match="invalid"):
        normalize_ad_account_id("act_abc")


# --- specificatia -----------------------------------------------------------


def test_specificatia_trece_prin_json_fara_sa_piarda_bani() -> None:
    """25.10 ca float ar deveni 25.099999999999998 dupa un drum prin JSON."""
    spec = _spec(daily_budget=Decimal("25.10"))
    restored = MetaLaunchSpec.from_payload(json.loads(json.dumps(spec.to_payload())))
    assert restored == spec
    assert restored.daily_budget == Decimal("25.10")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"custom_event_type": "PURCHSE"}, "eveniment necunoscut"),
        ({"call_to_action": "CLICK_HERE"}, "call-to-action"),
        ({"page_id": "pagina-mea"}, "page_id"),
        ({"pixel_id": ""}, "pixel_id"),
        ({"image_url": "http://cdn.exemplu.ro/x.jpg"}, "https"),
        ({"target_url": "exemplu.ro"}, "https"),
        ({"daily_budget": Decimal("0")}, "pozitiv"),
        ({"daily_budget": Decimal("-5")}, "pozitiv"),
        ({"country": "Romania"}, "ISO"),
        ({"headline": "   "}, "headline"),
    ],
)
def test_specificatia_invalida_e_refuzata_inainte_de_orice_apel(
    override: dict[str, Any], message: str
) -> None:
    """Orice eroare prinsa aici e o campanie care nu mai trebuie stearsa dupa."""
    with pytest.raises(ValueError, match=message):
        _spec(**override)


def test_o_specificatie_din_alta_versiune_nu_se_executa_pe_ghicite() -> None:
    payload = _spec().to_payload()
    payload["launch_spec_version"] = 99
    with pytest.raises(ValueError, match="versiunea"):
        MetaLaunchSpec.from_payload(payload)


def test_lansarea_bate_in_contul_de_reclame_nu_intr_o_campanie() -> None:
    target = resolve_target(
        ProposedChange(
            client_account_id=1,
            op=ChangeOp.CREATE_CAMPAIGN,
            resource="meta_ad_account/act_123",
            resource_type="campaign",
            rationale="t",
            source_module="t",
        )
    )
    assert (target.platform, target.kind, target.object_id) == ("meta", "ad_account", "act_123")


# --- endpoint-ul ------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Orice cerere prin ``httpx.AsyncClient`` pica testul - propunerea nu are voie."""
    attempts: list[str] = []

    async def refuse(self: httpx.AsyncClient, url: Any, *args: Any, **kwargs: Any) -> Any:
        attempts.append(str(url))
        raise AssertionError(f"propose_launch a incercat sa contacteze {url}")

    for method in ("post", "get", "delete", "request"):
        monkeypatch.setattr(httpx.AsyncClient, method, refuse)
    return attempts


def _signup(client: TestClient) -> tuple[dict[str, str], int]:
    response = client.post(
        "/api/v1/signup",
        json={
            "name": "Client Lansare",
            "email": "lansare@exemplu.ro",
            "password": "parola-sigura-123",
        },
    )
    assert response.status_code == 201
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    account_id = client.get("/api/v1/me", headers=headers).json()["account"]["id"]
    return headers, int(account_id)


@pytest.fixture
def launcher(
    client: TestClient, agency_settings: Tenant, session: Session
) -> tuple[TestClient, dict[str, str], int]:
    headers, account_id = _signup(client)
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.meta_ad_account_id = "act_555"
    session.add(account)
    session.commit()
    return client, headers, account_id


def _request(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "campaign_name": "Service Auto - Vanzari",
        "daily_budget": "25.00",
        "pixel_id": "1234567890",
        "page_id": "9876543210",
        "target_url": "https://exemplu.ro/oferta",
        "headline": "Revizie completa in 24h",
        "primary_text": "Programeaza revizia online.",
        "image_url": "https://cdn.exemplu.ro/reclama.jpg",
    }
    body.update(overrides)
    return body


def test_propunerea_se_salveaza_in_asteptare_fara_niciun_apel_meta(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
) -> None:
    client, headers, account_id = launcher
    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ChangeStatus.PENDING.value
    assert body["op"] == "CREATE_CAMPAIGN"
    assert body["resource"] == "meta_ad_account/act_555"
    assert Decimal(body["projected_daily_spend"]) == Decimal("25.00")
    # Omul care aproba vede specificatia completa, nu un rezumat.
    assert body["after"]["headline"] == "Revizie completa in 24h"
    assert body["after"]["daily_budget"] == "25.00"
    assert "PAUSED" in body["rationale"]
    assert no_network == []

    stored = session.exec(
        select(ProposedChange).where(ProposedChange.client_account_id == account_id)
    ).one()
    assert stored.op is ChangeOp.CREATE_CAMPAIGN
    assert MetaLaunchSpec.from_payload(stored.after).page_id == "9876543210"


def test_obiectivul_si_evenimentul_vin_din_contul_clientului(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
) -> None:
    """Niciodata ghicit: LEAD_GEN pe client inseamna OUTCOME_LEADS + LEAD."""
    client, headers, account_id = launcher
    account = session.get(ClientAccount, account_id)
    assert account is not None
    account.objective = CampaignObjective.LEAD_GEN
    session.add(account)
    session.commit()

    body = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request()
    ).json()
    assert body["after"]["objective"] == CampaignObjective.LEAD_GEN.value
    assert body["after"]["custom_event_type"] == "LEAD"
    assert body["after"]["call_to_action"] == "LEARN_MORE"
    assert "OUTCOME_LEADS" in body["rationale"]


def test_bugetul_peste_plafon_nu_intra_in_coada(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
) -> None:
    """Plafonul implicit e 50 RON/zi."""
    client, headers, _ = launcher
    response = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request(daily_budget="500")
    )
    assert response.status_code == 409
    assert session.exec(select(ProposedChange)).all() == []


def test_plafonul_numara_ce_s_a_executat_deja(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
) -> None:
    client, headers, account_id = launcher
    session.add(
        ProposedChange(
            client_account_id=account_id,
            op=ChangeOp.UPDATE,
            resource="meta_ad_set/1",
            resource_type="ad_set",
            projected_daily_spend=Decimal("40"),
            rationale="deja aplicat",
            source_module="test",
            status=ChangeStatus.EXECUTED,
        )
    )
    session.commit()
    # 40 deja angajati + 25 = 65 > 50.
    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())
    assert response.status_code == 409


def test_fara_cont_meta_configurat_nu_se_poate_propune(
    client: TestClient,
    agency_settings: Tenant,
    no_network: list[str],
) -> None:
    headers, _ = _signup(client)
    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())
    assert response.status_code == 409
    assert "contul de reclame Meta" in response.json()["detail"]


@pytest.mark.parametrize(
    "override",
    [
        {"custom_event_type": "PURCHSE"},
        {"image_url": "http://cdn.exemplu.ro/x.jpg"},
        {"pixel_id": "abc"},
        {"daily_budget": "0"},
        {"country": "Romania"},
    ],
)
def test_cererea_invalida_da_422_si_nu_salveaza_nimic(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
    override: dict[str, Any],
) -> None:
    client, headers, _ = launcher
    response = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request(**override)
    )
    assert response.status_code == 422
    assert session.exec(select(ProposedChange)).all() == []


def test_propunerea_cere_autentificare(client: TestClient) -> None:
    assert client.post("/api/v1/campaigns/propose_launch", json=_request()).status_code == 401


# --- brief-ul de lansare ----------------------------------------------------


def test_propunerea_poarta_brief_ul_agentilor(
    launcher: tuple[TestClient, dict[str, str], int],
    no_network: list[str],
) -> None:
    """Omul care aproba vede ce au spus ambii agenti, nu doar specificatia."""
    client, headers, _ = launcher
    body = client.post(
        "/api/v1/campaigns/propose_launch", headers=headers, json=_request()
    ).json()

    brief = body["before"]
    assert brief["verdict"] in ("ok", "warnings")
    assert brief["landing_page"]["status"] == "ok"
    assert brief["learning_phase"]["status"] == "ok"
    assert brief["budget_position"]["status"] in ("ok", "no_history")
    assert "gsc" in brief["message_signals"]
    assert "Brief de lansare" in body["rationale"]
    assert no_network == []


def test_o_pagina_de_destinatie_404_opreste_propunerea(
    launcher: tuple[TestClient, dict[str, str], int],
    session: Session,
    no_network: list[str],
) -> None:
    """Singurul fel de problema care blocheaza: banii ar arde cu certitudine."""
    client, headers, _ = launcher
    response = client.post(
        "/api/v1/campaigns/propose_launch",
        headers=headers,
        json=_request(target_url="https://exemplu.ro/pagina-404"),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["blocking"]
    assert "404" in detail["message"]
    assert detail["brief"]["verdict"] == "blocked"
    assert session.exec(select(ProposedChange)).all() == []


def _cco(decision: str) -> dict[str, Any]:
    return {
        "asset_type": "image",
        "decision": decision,
        "scores": {},
        "detected_risks": ["finalul nu spune ce sa faca privitorul (fara CTA)"],
        "priority_fixes": ["Adauga un CTA clar pe imagine"],
    }


def _launch_with_cco(client: TestClient, headers: dict[str, str], verdict: dict[str, Any]) -> Any:
    client.app.dependency_overrides[get_creative_review] = lambda: lambda image_url: verdict  # type: ignore[attr-defined]
    return client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())


def test_a_weak_creative_blocks_the_launch_with_the_cco_fixes(
    launcher: tuple[TestClient, dict[str, str], int],
) -> None:
    """CCO-ul spune "de revizuit": lansarea nu ajunge de aprobat - nu se cheltuie bani pe
    o reclama pe care evaluatorul o stie slaba. Motivul si reparatia stau in propunere."""
    client, headers, _ = launcher
    body = _launch_with_cco(client, headers, _cco("REVISE_BEFORE_TEST")).json()

    assert (body["status"], body["decided_by"]) == (ChangeStatus.BLOCKED.value, "cco")
    assert body["before"]["creative_review"]["decision"] == "REVISE_BEFORE_TEST"
    assert "Adauga un CTA clar pe imagine" in body["error_message"]


def test_a_creative_needing_a_human_look_stays_approvable_with_a_warning(
    launcher: tuple[TestClient, dict[str, str], int],
) -> None:
    """Verificarea umana ceruta de CCO e chiar aprobarea: propunerea ramane de aprobat."""
    client, headers, _ = launcher
    body = _launch_with_cco(client, headers, _cco("HUMAN_REVIEW_REQUIRED")).json()

    assert body["status"] == ChangeStatus.PENDING.value
    assert "CCO: creativa cere verificare umana" in body["rationale"]


def test_a_cco_that_cannot_run_does_not_stop_the_launch(
    launcher: tuple[TestClient, dict[str, str], int],
) -> None:
    """Ollama oprit: lansarea merge, iar avizul spune ca evaluarea lipseste."""
    client, headers, _ = launcher
    response = client.post("/api/v1/campaigns/propose_launch", headers=headers, json=_request())

    body = response.json()
    assert body["status"] == ChangeStatus.PENDING.value
    assert "creative_review" in body["before"]
    assert "evaluarea creativei n-a putut rula" in body["rationale"]

