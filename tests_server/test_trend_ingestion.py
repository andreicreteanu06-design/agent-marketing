"""Trendurile: ruta de ingestie cu CRON_SECRET_KEY, vectorii, TTL-ul de 30 de zile, scriptul
saptamanal - si CCO-ul care nu mai da 9 unui concept care a esuat deja.
"""

# Fixture-urile CCO-ului se importa din modulul lor de test: pytest le gaseste dupa nume.
# ruff: noqa: F401

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppc_agent.errors import ProviderError
from ppc_agent_server.models import ClientAccount, CreativeTrend, Tenant
from ppc_agent_server.routers.trends import get_trend_embedder
from ppc_agent_server.services.avatar_builder import CustomerAvatar
from ppc_agent_server.services.creative_context import (
    CalibrationLesson,
    CreativeEvaluationContext,
    TrendIngest,
    same_concept,
)
from ppc_agent_server.services.creative_memory import retrieve_trends
from ppc_agent_server.services.embeddings import (
    HASH_MODEL,
    HashEmbedder,
    OllamaEmbedder,
    cosine,
    embed_or_fallback,
)
from ppc_agent_server.settings import get_server_settings
from tests_server.test_creative_evaluator import _FakeJudge, _png, _run, ocr

SECRET = "o-cheie-de-test-destul-de-lunga-pentru-cron-0123456789"
INGEST = "/api/v1/trends/ingest"
_ROOT = Path(__file__).resolve().parent.parent


def _scraper() -> ModuleType:
    """``scripts/trend_scraper.py`` - un script, nu un pachet: incarcat dupa cale."""
    spec = importlib.util.spec_from_file_location(
        "trend_scraper", _ROOT / "scripts" / "trend_scraper.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["trend_scraper"] = module
    spec.loader.exec_module(module)
    return module


scraper = _scraper()


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    monkeypatch.setenv("CRON_SECRET_KEY", SECRET)
    get_server_settings.cache_clear()
    yield {"X-Cron-Secret": SECRET}
    get_server_settings.cache_clear()


def _trend(title: str, **fields: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": title,
        "hook": "Mecanicul arată piesa în prima secundă",
        "visual_format": "UGC 9:16, 20 s",
        "virality_reason": "Expertul real dezvăluie o practică necinstită",
        "platform": "meta",
        "industry": "service auto",
    }
    values.update(fields)
    return values


# --- ruta: cheia, vectorii, TTL-ul ------------------------------------------------------


def test_without_a_configured_secret_the_route_is_closed(client: TestClient) -> None:
    response = client.post(INGEST, json={"trends": [_trend("Atelierul")]})
    assert response.status_code == 503
    assert "CRON_SECRET_KEY" in response.json()["detail"]


def test_a_wrong_or_missing_secret_is_refused(
    client: TestClient, cron: dict[str, str]
) -> None:
    body = {"trends": [_trend("Atelierul")]}
    assert client.post(INGEST, json=body).status_code == 401
    assert client.post(INGEST, json=body, headers={"X-Cron-Secret": "ghicit"}).status_code == 401


def test_ingest_stores_vectors_updates_by_title_and_drops_the_old(
    client: TestClient, cron: dict[str, str], session: Session
) -> None:
    today = datetime.now(tz=UTC).date()
    session.add(
        CreativeTrend(
            platform="meta", industry="service auto", insight="Trend de acum o lună și ceva",
            observed_at=today - timedelta(days=31), expires_at=today + timedelta(days=1),
        )
    )
    session.commit()

    first = client.post(
        INGEST, headers=cron, json={"trends": [_trend("Atelierul"), _trend("Prețul spus")]}
    )
    again = client.post(
        INGEST, headers=cron,
        json={"trends": [_trend("atelierul", hook="Alt hook, aceeași idee de atelier")]},
    )

    assert first.status_code == 200, first.text
    assert first.json() == {
        "received": 2, "created": 2, "updated": 0, "expired_deleted": 1,
        "embedding_model": HASH_MODEL,
    }
    assert again.json()["updated"] == 1 and again.json()["created"] == 0
    rows = {row.title.lower(): row for row in session.exec(select(CreativeTrend)).all()}
    assert sorted(rows) == ["atelierul", "prețul spus"]  # cel vechi s-a sters
    atelier = rows["atelierul"]
    assert atelier.tenant_id is None  # pentru toti clientii
    assert atelier.hook == "Alt hook, aceeași idee de atelier"
    assert atelier.expires_at == today + timedelta(days=30)
    assert atelier.embedding is not None and len(atelier.embedding) == 256
    assert atelier.insight.startswith("atelierul: Alt hook, aceeași idee de atelier Format:")


def test_a_trend_older_than_30_days_is_not_stored(
    client: TestClient, cron: dict[str, str]
) -> None:
    old = (datetime.now(tz=UTC).date() - timedelta(days=45)).isoformat()
    response = client.post(
        INGEST, headers=cron, json={"trends": [_trend("Vechi", observed_at=old)]}
    )
    assert response.json()["created"] == 0


@dataclass(frozen=True)
class _Semantic:
    """Embeddings de proba "semantice": atelier ~ service ~ mecanic, fara cuvinte comune."""

    model: str = "fake-semantic"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        cars = ("service", "atelier", "mecanic", "automate")
        return [[1.0, 0.0] if any(w in t.lower() for w in cars) else [0.0, 1.0] for t in texts]


def test_the_cco_finds_a_trend_by_meaning_not_only_by_words(
    client: TestClient, cron: dict[str, str], session: Session,
    tenant_and_key: tuple[Tenant, str],
) -> None:
    client.app.dependency_overrides[get_trend_embedder] = lambda: _Semantic()  # type: ignore[attr-defined]
    client.post(INGEST, headers=cron, json={"trends": [
        _trend("Mecanicul în cadru", industry="atelier mecanic"),
        _trend("Rujul zilei", industry="cosmetice, machiaj", hook="Rujul aplicat în 2 secunde"),
    ]})
    client.app.dependency_overrides.pop(get_trend_embedder)  # type: ignore[attr-defined]

    found = retrieve_trends(
        session, tenant_and_key[0].id or 0, {"service", "cutii", "automate"},
        platform="meta", today=datetime.now(tz=UTC).date(), embedder=_Semantic(),
    )

    assert [trend.insight.split(":")[0] for trend in found] == ["Mecanicul în cadru"]


def test_hash_vectors_see_word_forms_and_ollama_failures_fall_back() -> None:
    near, far, query = HashEmbedder().embed(
        ["Service auto pentru cutii automate", "Ruj și machiaj de seară", "serviceul auto"]
    )
    assert cosine(query, near) > 0.3 > cosine(query, far)

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "this model does not support embeddings"})

    ollama = OllamaEmbedder(
        host="http://ollama.test", model="qwen2.5", transport=httpx.MockTransport(broken)
    )
    with pytest.raises(ProviderError):
        ollama.embed(["text"])
    model, [vector] = embed_or_fallback(ollama, ["text"])
    assert model == HASH_MODEL and len(vector) == 256


def test_ollama_embeddings_are_requested_and_normalized() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0]]})

    vectors = OllamaEmbedder(
        host="http://ollama.test", model="nomic-embed-text",
        transport=httpx.MockTransport(handler),
    ).embed(["service auto"])

    assert sent == [{"model": "nomic-embed-text", "input": ["service auto"]}]
    assert vectors == [[0.6, 0.8]]


# --- CCO: conceptele care au esuat, treaba clientului --------------------------------


def _failed(**fields: Any) -> CalibrationLesson:
    values: dict[str, Any] = {
        "score": "hook_power", "predicted": 9, "metric": "hook_rate", "actual": 0.12,
        "threshold": 0.2, "direction": "overestimated",
        "lesson": "Hook-ul a primit 9/10, dar pe Meta doar 12% au privit primele 3 secunde.",
    }
    values.update(fields)
    return CalibrationLesson(**values)


def test_a_concept_that_already_failed_does_not_get_a_9_again() -> None:
    """Acelasi hook ("Revizie completă în 24h"), spus putin altfel, intr-un fisier nou."""
    lesson = _failed(concept="Revizie în 24h, completă!", asset_sha256="altfisier")
    result = _run(_png(), context=CreativeEvaluationContext(lessons=[lesson]))

    assert result["concept"] == "Revizie completă în 24h"
    assert result["scores"]["hook_power"] == 5  # 8 de la model, -1 din piata, plafon 5
    assert (
        "conceptul «Revizie în 24h, completă!» a eșuat deja pe acest cont: Hook-ul a primit "
        "9/10, dar pe Meta doar 12% au privit primele 3 secunde"
    ) in result["detected_risks"]


def test_the_same_file_is_recognized_whatever_its_text() -> None:
    import hashlib

    lesson = _failed(asset_sha256=hashlib.sha256(_png()).hexdigest(), concept="")
    result = _run(_png(), context=CreativeEvaluationContext(lessons=[lesson]))
    assert result["scores"]["hook_power"] == 5
    risks = result["detected_risks"]
    assert any(risk.startswith("aceeași creativă a eșuat deja") for risk in risks)


def test_same_concept_is_word_overlap_not_spelling() -> None:
    assert same_concept("Revizie completă în 24h", "REVIZIE COMPLETA IN 24H")
    assert not same_concept("Revizie completă în 24h", "Schimb de ulei azi")
    assert not same_concept("", "Revizie")


def test_an_ad_must_show_the_job_the_customer_wants_done() -> None:
    avatar = CustomerAvatar(functional_job="mașina reparată până vineri")
    judge = _FakeJudge(job=0.1)
    result = _run(_png(), judge=judge, context=CreativeEvaluationContext(avatar=avatar))

    assert "job" in judge.calls[0][1] and "worry" not in judge.calls[0][1]
    assert judge.calls[0][0]["ideal_customer"]["job"] == "mașina reparată până vineri"
    assert result["scores"]["message_match"] == 4
    assert (
        "lipsă de aliniere strategică: reclama nu arată treaba pe care o vrea făcută («mașina "
        "reparată până vineri»)"
    ) in result["detected_risks"]
    aligned = _run(_png(), context=CreativeEvaluationContext(avatar=avatar))
    assert aligned["scores"]["message_match"] == 10


def test_without_the_avatar_or_the_hypothesis_the_verdict_says_so() -> None:
    notes = _run(_png(), context=CreativeEvaluationContext())["context_notes"]
    assert notes == [
        "Fără profilul clientului ideal (interviul JTBD): alinierea cu grijile și treburile "
        "lui nu s-a verificat.",
        "Fără ipoteză CMO (nicio barieră dominantă încă): strategia nu s-a verificat.",
    ]


# --- scriptul saptamanal ----------------------------------------------------------------


def test_the_scripts_trends_match_the_api_contract() -> None:
    trends = scraper.collect_trends(date(2026, 10, 5))
    assert len(TrendIngest.model_validate({"trends": trends}).trends) == len(trends)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://api.exemplu.ro/", True),
        ("http://localhost:8000", True),
        ("http://api.exemplu.ro", False),  # cheia ar pleca in clar
        ("ftp://api.exemplu.ro", False),
    ],
)
def test_the_script_only_sends_the_secret_over_https(url: str, ok: bool) -> None:
    if ok:
        assert scraper.ingest_url(url).endswith("/api/v1/trends/ingest")
    else:
        with pytest.raises(ValueError):
            scraper.ingest_url(url)


def test_the_script_writes_trends_json_then_posts_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, client: TestClient,
    cron: dict[str, str],
) -> None:
    """Scriptul cap-coada, cu ruta adevarata in locul retelei."""
    path = tmp_path / "trends.json"
    monkeypatch.setenv("API_URL", "https://api.exemplu.ro")
    monkeypatch.setenv("TRENDS_FILE", str(path))
    sent: list[tuple[str, str]] = []

    def post(url: str, secret: str, payload: dict[str, Any]) -> dict[str, Any]:
        sent.append((url, secret))
        response = client.post(INGEST, headers={"X-Cron-Secret": secret}, json=payload)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    monkeypatch.setattr(scraper, "post", post)

    assert scraper.main() == 0
    assert sent == [("https://api.exemplu.ro/api/v1/trends/ingest", SECRET)]
    assert len(json.loads(path.read_text("utf-8"))["trends"]) == 6


def test_the_script_stops_without_its_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.delenv("CRON_SECRET_KEY", raising=False)
    assert scraper.main() == 2
