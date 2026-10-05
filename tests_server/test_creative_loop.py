"""Bucla CCO-ului cu ceilalti agenti: contextul, Message Match, lectiile din piata, GEO, trends_db.

Tesseract, Jev si modelul cu vision sunt dublati ca in ``test_creative_evaluator`` (de acolo
vin si dublurile); baza e SQLite in memorie.
"""

# Fixture-urile CCO-ului si ale MCP-ului se importa din modulele lor de test: pytest le
# gaseste dupa nume, deci importul pare nefolosit, iar parametrii par redefiniri.
# ruff: noqa: F401, F811

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import ppc_agent_server.services.creative_evaluator as ce
from ppc_agent_server.jobs.brand_alignment import publish_hypothesis
from ppc_agent_server.jobs.tasks import run_creative_feedback_job
from ppc_agent_server.models import (
    AdFatiguePlatform,
    AdPerformanceRecord,
    ChangeOp,
    ChangeStatus,
    ClientAccount,
    CreativeEvaluationRecord,
    CreativeTrend,
    PerformanceCalibration,
    ProposedChange,
    Tenant,
)
from ppc_agent_server.services.avatar_builder import PROFILE_KEYS, CustomerAvatar
from ppc_agent_server.services.creative_context import (
    CalibrationLesson,
    CreativeEvaluationContext,
    PerformanceFeedback,
    PerformanceMetrics,
    TrendInsight,
    calibrate,
)
from ppc_agent_server.services.creative_memory import (
    build_context,
    record_feedback,
    retrieve_trends,
)
from ppc_agent_server.services.propensity import Experiment
from ppc_agent_server.services.queen_agent import build_directive
from tests_server.test_creative_evaluator import (
    _FakeJudge,
    _FakeOcr,
    _FakeVision,
    _look,
    _png,
    _run,
    _upload,
    judge,
    login,
    ocr,
    vision,
)
from tests_server.test_mcp_agents import _new_key, _rpc, owner
from tests_server.test_queen_agent import NOW, _signals

HYPOTHESIS = Experiment(
    barrier="lack_of_trust",
    hypothesis="Dacă punem dovada în prim-plan, rata de conversie crește cu cel puțin 15%.",
    change="Punem dovada în prim-plan: recenzii reale, cine face lucrarea, garanția scrisă",
    control="Reclama actuală, neschimbată.",
    metric="rata de conversie (conversii / click-uri)",
    success_criterion="varianta bate controlul cu cel puțin 15% la rata de conversie",
    min_sample="cel puțin 100 de click-uri pe fiecare variantă și 14 zile",
    falsified_if="varianta nu bate controlul cu 15% după eșantion",
)
AVATAR = CustomerAvatar(anxieties=["prețul", "că nu știe dacă lucrarea iese bine"])
STRATEGY = CreativeEvaluationContext(avatar=AVATAR, cmo_hypothesis=HYPOTHESIS)


# --- 1. Message Match: avatarul si ipoteza CMO-ului ------------------------------------


@pytest.mark.parametrize(
    ("answers", "match", "decision"),
    [
        ({}, 10, "ELIGIBLE_FOR_TEST"),
        ({"worry": "none"}, 4, "REVISE_BEFORE_TEST"),
        ({"hypothesis": 0.1}, 4, "REVISE_BEFORE_TEST"),
        ({"worry": "none", "hypothesis": 0.1}, 1, "REVISE_BEFORE_TEST"),
    ],
    ids=["aliniata", "fara-grija", "fara-ipoteza", "nimic"],
)
def test_a_beautiful_ad_off_strategy_is_rejected(
    answers: dict[str, Any], match: int, decision: str
) -> None:
    """Vizual 10/10 si tot respinsa: nu raspunde clientului ideal sau nu face ce cere CMO-ul."""
    result = _run(
        _png(), model=_FakeVision(_look(visual_hook=10)), judge=_FakeJudge(**answers),
        context=STRATEGY,
    )
    assert result["scores"]["message_match"] == match
    assert result["decision"] == decision


def test_jev_sees_the_worries_and_the_hypothesis_and_the_client_sees_why() -> None:
    judge = _FakeJudge(worry="none", hypothesis=0.1)
    result = _run(_png(), judge=judge, context=STRATEGY)

    state, questions = judge.calls[0]
    assert state["cmo_hypothesis"]["test_variant"] == HYPOTHESIS.change
    assert questions["worry"].options == {  # type: ignore[union-attr]
        "worry_0": "prețul",
        "worry_1": "că nu știe dacă lucrarea iese bine",
        "none": "the ad answers none of these worries",
    }
    risks = result["detected_risks"]
    assert (
        "lipsă de aliniere strategică: reclama nu răspunde la nicio grijă a clientului ideal "
        "(«prețul», «că nu știe dacă lucrarea iese bine»)"
    ) in risks
    assert result["priority_fixes"][:2] == [
        "Răspunde în reclamă la grija «prețul», cu dovada care o stinge",
        f"Fă varianta cerută de CMO: {HYPOTHESIS.change}",
    ]
    assert result["context_notes"][1] == f"Ipoteza CMO-ului: {HYPOTHESIS.hypothesis}"


# --- 2. Feedback-ul PPC: lectiile din piata ---------------------------------------------


def _feedback(**metrics: Any) -> PerformanceFeedback:
    values: dict[str, Any] = {
        "impressions": 5000, "clicks": 120, "video_views_3s": 600,
        "spend": Decimal("300"), "revenue": Decimal("240"), "conversions": 3,
    }
    values.update(metrics)
    return PerformanceFeedback(
        evaluation_id=1, platform="meta", ad_id="120210", window_days=7,
        metrics=PerformanceMetrics(**values), break_even_roas=2.0,
    )


def test_a_hook_of_9_that_meta_did_not_hold_becomes_a_lesson() -> None:
    """Hook 9/10, dar doar 12% au privit 3 secunde (sub 20%): CCO-ul a supraestimat."""
    [lesson] = calibrate({"hook_power": 9}, "video", _feedback())

    assert lesson.direction == "overestimated" and lesson.metric == "hook_rate"
    assert lesson.actual == 0.12 and lesson.threshold == 0.2
    assert lesson.lesson == (
        "Hook-ul a primit 9/10, dar pe Meta doar 12% au privit primele 3 secunde (pragul: "
        "20%): deschiderea a promis mai mult decât a ținut."
    )


def test_small_samples_teach_nothing_and_images_are_judged_on_ctr() -> None:
    assert calibrate({"hook_power": 9}, "video", _feedback(impressions=800)) == []
    [ctr] = calibrate({"hook_power": 9}, "image", _feedback(video_views_3s=None, clicks=20))
    assert ctr.metric == "ctr" and ctr.actual == 0.004
    [under] = calibrate({"hook_power": 3}, "video", _feedback(video_views_3s=2000))
    assert under.direction == "underestimated"


def test_an_aligned_message_that_did_not_sell_is_corrected_on_roas() -> None:
    [lesson] = calibrate({"message_match": 10}, "image", _feedback(video_views_3s=None))
    assert (lesson.score, lesson.metric, lesson.actual) == ("message_match", "roas", 0.8)


def test_lessons_move_the_next_scores_on_the_same_account() -> None:
    over = CalibrationLesson(
        score="hook_power", predicted=9, metric="hook_rate", actual=0.12, threshold=0.2,
        direction="overestimated", lesson="Hook-ul a primit 9/10, dar pe Meta doar 12%.",
    )
    result = _run(_png(), context=CreativeEvaluationContext(lessons=[over, over]))

    assert result["scores"]["hook_power"] == 6  # 8 de la model, -2 din piata
    assert (
        "pe acest cont, CCO-ul a supraestimat hook-ul în piață (2 lecții de la PPC): scad 2 "
        "puncte"
    ) in result["detected_risks"]


def _account(session: Session, tenant: Tenant, **fields: Any) -> ClientAccount:
    account = ClientAccount(tenant_id=tenant.id or 0, name="Service Cutii Automate", **fields)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def _evaluation(session: Session, account: ClientAccount, **fields: Any) -> int:
    values: dict[str, Any] = {
        "client_account_id": account.id, "asset_sha256": "ab" * 32, "asset_type": "image",
        "decision": "ELIGIBLE_FOR_TEST", "scores": {"hook_power": 9, "message_match": None},
    }
    values.update(fields)
    record = CreativeEvaluationRecord(**values)
    session.add(record)
    session.commit()
    session.refresh(record)
    assert record.id is not None
    return record.id


def test_the_same_ad_updates_its_lesson_instead_of_doubling_it(
    session: Session, tenant_and_key: tuple[Tenant, str]
) -> None:
    account = _account(session, tenant_and_key[0])
    evaluation = _evaluation(session, account, asset_type="video")
    feedback = _feedback().model_copy(update={"evaluation_id": evaluation})

    record_feedback(session, account.id or 0, feedback)
    later = feedback.model_copy(
        update={"metrics": PerformanceMetrics(**{**feedback.metrics.model_dump(
            exclude={"hook_rate", "ctr", "roas"}), "video_views_3s": 500})}
    )
    record_feedback(session, account.id or 0, later)

    [row] = session.exec(select(PerformanceCalibration)).all()
    assert row.actual == 0.1
    linked = session.get(CreativeEvaluationRecord, evaluation)
    assert linked is not None and linked.ad_id == "120210"  # legat de anunt la primul feedback


def test_the_nightly_job_sends_the_launched_ads_numbers_back_to_the_cco(
    session: Session, tenant_and_key: tuple[Tenant, str]
) -> None:
    account = _account(session, tenant_and_key[0])
    evaluation = _evaluation(session, account)
    session.add(
        ProposedChange(
            client_account_id=account.id or 0, op=ChangeOp.CREATE_CAMPAIGN,
            resource="meta_ad_account/act_1", resource_type="campaign",
            before={"creative_review": {"decision": "ELIGIBLE_FOR_TEST",
                                        "evaluation_id": evaluation}},
            after={}, projected_daily_spend=Decimal("40"), rationale="lansare",
            source_module="campaign_launch", status=ChangeStatus.EXECUTED,
            execution_result={"ad_id": "777"},
        )
    )
    session.add(
        AdPerformanceRecord(
            client_account_id=account.id or 0, ad_id="777", platform=AdFatiguePlatform.META,
            launch_time=datetime.now(tz=UTC) - timedelta(days=5), target_cpa=Decimal("80"),
            impressions=6000, clicks=24, spend=Decimal("90"),
        )
    )
    session.commit()

    result = run_creative_feedback_job(client_account_id=account.id or 0)

    assert result == {"feedback": 1, "lessons": 1, "overestimated": 1}
    [row] = session.exec(select(PerformanceCalibration)).all()
    assert (row.metric, row.ad_id, row.predicted) == ("ctr", "777", 9)


# --- context: ce afla CCO-ul inainte ----------------------------------------------------


def test_the_cco_reads_the_avatar_the_published_hypothesis_lessons_and_trends(
    session: Session, tenant_and_key: tuple[Tenant, str]
) -> None:
    tenant = tenant_and_key[0]
    account = _account(
        session, tenant, business_kind="programat",
        avatar_answers={**dict.fromkeys(PROFILE_KEYS), "functional_job": "service auto rapid",
                        "anxieties": ["prețul"]},
    )
    # Fara ipoteza publicata, CCO-ul o calculeaza din interviu (grija de pret).
    fallback = build_context(session, account)
    assert fallback.cmo_hypothesis is not None
    assert fallback.cmo_hypothesis.barrier == "price_uncertainty"

    directive = build_directive(
        account.id or 0, _signals(customer_avatar=AVATAR), generated_at=NOW
    )
    publish_hypothesis(session, account.id or 0, directive)
    session.refresh(account)
    evaluation = _evaluation(session, account, asset_type="video")
    record_feedback(
        session, account.id or 0, _feedback().model_copy(update={"evaluation_id": evaluation})
    )
    today = datetime.now(tz=UTC).date()
    session.add_all([
        CreativeTrend(tenant_id=tenant.id or 0, platform="meta", industry="service auto",
                      insight="UGC filmat în service, cu mecanicul vorbind", observed_at=today,
                      expires_at=today + timedelta(days=30)),
        CreativeTrend(tenant_id=tenant.id or 0, platform="tiktok", industry="service auto",
                      insight="Doar pe TikTok", observed_at=today,
                      expires_at=today + timedelta(days=30)),
        CreativeTrend(tenant_id=tenant.id or 0, platform="meta", industry="cosmetice",
                      insight="Altă industrie", observed_at=today,
                      expires_at=today + timedelta(days=30)),
        CreativeTrend(tenant_id=tenant.id or 0, platform="all", industry="service auto",
                      insight="Expirat de mult", observed_at=today - timedelta(days=200),
                      expires_at=today - timedelta(days=1)),
    ])
    session.commit()

    context = build_context(session, account, platform="meta")

    assert context.avatar is not None and context.avatar.anxieties == ["prețul"]
    assert context.cmo_hypothesis == directive.experiment  # cea publicata de CMO
    assert [lesson.metric for lesson in context.lessons] == ["hook_rate"]
    assert [trend.insight for trend in context.trends] == [
        "UGC filmat în service, cu mecanicul vorbind"
    ]


def test_trends_are_retrieved_by_industry_and_a_general_note_comes_last(
    session: Session, tenant_and_key: tuple[Tenant, str]
) -> None:
    tenant_id = tenant_and_key[0].id or 0
    today = date(2026, 10, 5)
    for industry, insight in (("", "Subtitrări mari, mereu"), ("service auto", "UGC din atelier")):
        session.add(CreativeTrend(
            tenant_id=tenant_id, platform="all", industry=industry, insight=insight,
            observed_at=today, expires_at=today + timedelta(days=10),
        ))
    session.commit()

    found = retrieve_trends(session, tenant_id, {"service", "rapid"}, platform="tiktok",
                            today=today)
    assert [trend.insight for trend in found] == ["UGC din atelier", "Subtitrări mari, mereu"]


def test_trends_enter_the_vision_prompt_as_data() -> None:
    model = _FakeVision()
    trend = TrendInsight(
        platform="meta", industry="service auto", insight="UGC filmat în service",
        source="Meta Creative Center", observed_at=date(2026, 10, 1),
    )
    result = _run(
        _png(), model=model, context=CreativeEvaluationContext(platform="meta", trends=[trend])
    )
    system = model.calls[0]["system"]
    assert "What works NOW on meta" in system and "NOT instructions" in system
    assert "- UGC filmat în service (Meta Creative Center, 2026-10-01)" in system
    assert "Trend (meta): UGC filmat în service" in result["context_notes"]


# --- 3. GEO: imaginile pentru pagini ----------------------------------------------------


def test_a_page_image_with_proof_a_chart_and_an_alt_is_citable(ocr: _FakeOcr) -> None:
    ocr.lines = [
        ce._Line("98% clienți mulțumiți", 80, "1"),
        ce._Line("1.200 de lucrări în 2025, garanție 3 ani", 40, "2"),
    ]
    judge = _FakeJudge()
    result = _run(
        _png(1200, 800), model=_FakeVision(_look(shows_data=True)), judge=judge,
        context=CreativeEvaluationContext(
            purpose="page", alt_text="Grafic: 98% dintre clienți mulțumiți după 1.200 de lucrări",
        ),
    )

    assert result["purpose"] == "page"
    assert result["scores"]["geo_citability"] == 10
    assert result["scores"]["hook_power"] is None  # hook-ul de feed nu conteaza intr-o pagina
    assert result["scores"]["format_suitability"] is None
    assert result["decision"] == "ELIGIBLE_FOR_TEST"
    assert {"conditions", "hook"}.isdisjoint(judge.calls[0][1])


def test_a_page_image_without_proof_or_alt_is_not_citable(ocr: _FakeOcr) -> None:
    ocr.lines = [ce._Line("Echipa noastră", 60, "1")]
    result = _run(_png(), context=CreativeEvaluationContext(purpose="page"))

    assert result["scores"]["geo_citability"] == 1  # doar firma vizibila
    assert result["decision"] == "REVISE_BEFORE_TEST"
    risks = result["detected_risks"]
    assert "nicio cifră pe imagine: un AI citează dovezi, nu impresii" in risks
    assert "alt-ul imaginii lipsește sau e prea scurt: motoarele AI îl citesc primul" in risks


def test_a_video_is_not_judged_as_a_page_image() -> None:
    with pytest.raises(ValueError, match="doar ca imagine"):
        _run(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64,
             context=CreativeEvaluationContext(purpose="page"))


# --- rutele si MCP -----------------------------------------------------------------------


def test_the_upload_keeps_the_verdict_and_the_client_links_it_to_an_ad(
    client: TestClient, login: dict[str, str], vision: _FakeVision, judge: _FakeJudge,
    session: Session,
) -> None:
    response = _upload(client, login, _png())
    assert response.status_code == 200, response.text
    evaluation_id = response.json()["evaluation_id"]

    linked = client.post(
        f"/api/v1/creative/evaluations/{evaluation_id}/ad", headers=login,
        json={"platform": "meta", "ad_id": "120210"},
    )

    assert linked.status_code == 204
    record = session.get(CreativeEvaluationRecord, evaluation_id)
    assert record is not None and (record.ad_platform, record.ad_id) == ("meta", "120210")
    assert record.scores["hook_power"] == 8


def test_the_ppc_posts_its_numbers_and_gets_the_lessons(
    client: TestClient, auth_headers: dict[str, str], session: Session,
    tenant_and_key: tuple[Tenant, str],
) -> None:
    account = _account(session, tenant_and_key[0])
    evaluation = _evaluation(session, account, asset_type="video")
    payload = _feedback().model_copy(update={"evaluation_id": evaluation}).model_dump(
        mode="json"
    )

    response = client.post("/api/v1/creative/feedback", headers=auth_headers, json=payload)

    assert response.status_code == 200, response.text
    assert [lesson["metric"] for lesson in response.json()] == ["hook_rate"]
    stranger = client.post(
        "/api/v1/creative/feedback", headers=auth_headers,
        json={**payload, "evaluation_id": evaluation + 99},
    )
    assert stranger.status_code == 404


def test_the_agency_fills_the_trends_db(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/creative/trends", headers=auth_headers,
        json={"platform": "tiktok", "industry": "service auto", "insight": "Hook vorbit în 1s",
              "source": "TikTok Creative Center", "observed_at": "2026-10-01",
              "valid_days": 30},
    )
    assert created.status_code == 201, created.text
    assert created.json()["expires_at"] == "2026-10-31"
    listed = client.get("/api/v1/creative/trends", headers=auth_headers).json()
    assert [trend["insight"] for trend in listed] == ["Hook vorbit în 1s"]


def test_an_external_ppc_agent_reports_through_mcp(
    client: TestClient, owner: dict[str, str], session: Session
) -> None:
    key = _new_key(client, owner)["key"]
    account_id = client.get("/api/v1/me", headers=owner).json()["account"]["id"]
    account = session.get(ClientAccount, account_id)
    assert account is not None
    evaluation = _evaluation(session, account, asset_type="video")

    result = _rpc(client, key, "tools/call", {
        "name": "report_creative_performance",
        "arguments": {
            "evaluation_id": evaluation, "platform": "meta", "ad_id": "55", "window_days": 7,
            "impressions": 5000, "clicks": 120, "spend": 300, "revenue": 240,
            "conversions": 3, "video_views_3s": 600,
        },
    })["structuredContent"]

    assert result["metrics"]["hook_rate"] == 0.12
    assert [lesson["direction"] for lesson in result["lessons"]] == ["overestimated"]
    lessons = _rpc(client, key, "tools/call", {"name": "get_creative_lessons", "arguments": {}})
    assert lessons["structuredContent"]["count"] == 1
