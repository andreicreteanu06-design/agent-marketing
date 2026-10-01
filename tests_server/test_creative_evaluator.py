"""CCO-ul: estetica (scala Aesthetic Predictor V2.5) si semnalele algoritmilor de
Discovery, judecate de un model cu vision - fara model real, fara retea.

Modelul doar noteaza (JSON impus prin schema) si propune remedieri; scorul estetic,
potentialul viral si verdictul pentru algoritmi le calculeaza codul.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent_server.models import Tenant
from ppc_agent_server.routers.creative import get_vision_model
from ppc_agent_server.services.creative_evaluator import MAX_IMAGE_BYTES, evaluate_creative
from ppc_agent_server.services.llm_client import (
    LLMUnavailableError,
    OllamaChatClient,
    OllamaError,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
KEYS = {"aesthetic_score", "virality_potential", "algorithm_compatibility", "feedback"}


def _ratings(**overrides: Any) -> str:
    """O creativa curata si profesionista, cu CTA-ul slab - suprascrisa pe caz."""
    marks: dict[str, Any] = {
        "composition": 8,
        "color_balance": 7,
        "visual_noise": 8,
        "perceived_quality": 7,
        "visual_hook": 8,
        "thumb_stop": 7,
        "cognitive_load": 8,
        "text_density": 9,
        "cta_clarity": 4,
        "observation": "Mecanic zâmbitor în prim-plan, fundal albastru curat.",
        "fixes": ["Crește luminozitatea pe CTA", "Mută logo-ul în colțul de jos"],
    }
    marks.update(overrides)
    return json.dumps(marks)


class _FakeVision:
    """Modelul cu vision, dublat: raspunde ce i se da si tine minte ce a primit."""

    def __init__(self, answer: str = "", *, error: Exception | None = None) -> None:
        self.answer = answer or _ratings()
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        images: Sequence[str] = (),
        schema: Mapping[str, Any] | None = None,
    ) -> str:
        self.calls.append({"system": system, "images": list(images), "schema": schema})
        if self.error is not None:
            raise self.error
        return self.answer


def test_raspunsul_are_exact_schema_ceruta() -> None:
    model = _FakeVision()

    result = evaluate_creative(PNG, model=model)

    assert set(result) == KEYS
    assert result["aesthetic_score"] == 7.5  # (8 + 7 + 8 + 7) / 4
    assert result["virality_potential"] == "High"  # indice 7,7 si estetic peste 5,5
    [call] = model.calls
    assert call["images"] == [base64.b64encode(PNG).decode("ascii")]
    assert "Aesthetic Predictor V2.5" in call["system"]
    assert {"visual_hook", "thumb_stop", "cognitive_load"} <= set(call["schema"]["properties"])


def test_feedback_ul_e_al_unui_media_buyer_cu_cel_mai_slab_semnal() -> None:
    feedback = evaluate_creative(PNG, model=_FakeVision())["feedback"]

    assert feedback.startswith("Estetic: 7,5/10, profesionist (compoziție 8, culori 7")
    assert "Ce schimbi: 1) Crește luminozitatea pe CTA; 2) Mută logo-ul în colțul de jos." in (
        feedback
    )
    assert feedback.endswith(
        "Cel mai slab semnal e CTA-ul (4/10): îndemnul mare, pe o bandă sau un buton "
        "contrastant."
    )


@pytest.mark.parametrize(
    ("aesthetic", "tier"),
    [((9, 9, 8, 9), "premium"), ((6, 6, 6, 6), "profesionist"), ((5, 6, 5, 6), "sub pragul")],
    ids=["premium", "profesionist", "amator"],
)
def test_pragurile_scalei_estetice(aesthetic: tuple[int, ...], tier: str) -> None:
    names = ("composition", "color_balance", "visual_noise", "perceived_quality")
    answer = _ratings(**dict(zip(names, aesthetic, strict=True)))
    assert tier in evaluate_creative(PNG, model=_FakeVision(answer))["feedback"]


@pytest.mark.parametrize(
    ("overrides", "potential"),
    [
        ({}, "High"),
        # Semnale puternice, dar imagine amatoare: opreste scroll-ul, nu tine increderea.
        ({"composition": 4, "color_balance": 5, "visual_noise": 5, "perceived_quality": 5},
         "Medium"),
        ({"visual_hook": 6, "thumb_stop": 5, "cognitive_load": 6}, "Medium"),
        ({"visual_hook": 3, "thumb_stop": 4, "cognitive_load": 5}, "Low"),
    ],
    ids=["puternica", "amatoare", "medie", "derulata"],
)
def test_potentialul_viral_il_calculeaza_codul(
    overrides: dict[str, int], potential: str
) -> None:
    result = evaluate_creative(PNG, model=_FakeVision(_ratings(**overrides)))
    assert result["virality_potential"] == potential


def test_compatibilitatea_cu_algoritmii_spune_semnalele_si_textul() -> None:
    low = evaluate_creative(
        PNG,
        model=_FakeVision(
            _ratings(visual_hook=3, thumb_stop=4, cognitive_load=5, text_density=2)
        ),
    )["algorithm_compatibility"]

    assert low.startswith("Pe Meta, va fi derulată")
    assert "hook 3/10, oprirea scroll-ului 4/10, încărcare cognitivă 5/10; indice 4,0" in low
    assert "Mult text pe imagine" in low
    assert "Pe TikTok, distribuția o primește video-ul" in low


def test_cand_estetica_opreste_high_verdictul_spune_motivul_real() -> None:
    """Cazul gasit pe o creativa reala: semnale de High (indice 7), estetic 5,3."""
    answer = _ratings(
        composition=7, color_balance=6, visual_noise=3, perceived_quality=5,
        visual_hook=6, thumb_stop=7, cognitive_load=8,
    )
    result = evaluate_creative(PNG, model=_FakeVision(answer))

    assert (result["aesthetic_score"], result["virality_potential"]) == (5.3, "Medium")
    assert result["algorithm_compatibility"].startswith(
        "Pe Meta, oprește scroll-ul, dar arată amator (estetic sub 5,5)"
    )


def test_promptul_nu_mai_da_exemple_de_copiat() -> None:
    """Pe creativa reala, modelul a copiat aproape cuvant cu cuvant exemplele din prompt."""
    model = _FakeVision()
    evaluate_creative(PNG, model=model)
    assert "«" not in model.calls[0]["system"]


def test_primeste_si_calea_imaginii(tmp_path: Path) -> None:
    path = tmp_path / "reclama.jpg"
    path.write_bytes(JPEG)
    assert set(evaluate_creative(path, model=_FakeVision())) == KEYS


@pytest.mark.parametrize(
    "answer",
    [
        "nu e json",
        _ratings(composition=11),
        _ratings(composition=0),  # scala estetica incepe de la 1
        _ratings(fixes=[]),
        json.dumps({"composition": 5}),
    ],
    ids=["text", "peste-10", "sub-1", "fara-remedieri", "incomplet"],
)
def test_un_raspuns_invalid_al_modelului_e_o_eroare_de_furnizor(answer: str) -> None:
    with pytest.raises(ProviderError, match="invalid"):
        evaluate_creative(PNG, model=_FakeVision(answer))


@pytest.mark.parametrize(
    ("data", "match"),
    [(b"GIF89a....", "JPEG sau PNG"), (PNG + b"\x00" * MAX_IMAGE_BYTES, "depășește")],
    ids=["gif", "prea-mare"],
)
def test_doar_imagini_jpeg_png_sub_plafon(data: bytes, match: str) -> None:
    model = _FakeVision()
    with pytest.raises(ValueError, match=match):
        evaluate_creative(data, model=model)
    assert model.calls == []


def test_ollama_oprit_e_o_problema_de_configurare_iar_o_cadere_e_de_furnizor() -> None:
    with pytest.raises(SetupRequiredError):
        evaluate_creative(PNG, model=_FakeVision(error=LLMUnavailableError("oprit")))
    with pytest.raises(ProviderError):
        evaluate_creative(PNG, model=_FakeVision(error=OllamaError("a picat")))


def test_ollama_primeste_imaginea_si_schema_in_cerere() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        lines = [
            json.dumps({"message": {"content": _ratings()}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        return httpx.Response(200, text="\n".join(lines))

    client = OllamaChatClient(
        host="http://ollama.test", model="qwen2.5vl:3b", transport=httpx.MockTransport(handler)
    )
    assert evaluate_creative(PNG, model=client)["aesthetic_score"] == 7.5

    [payload] = seen
    assert payload["model"] == "qwen2.5vl:3b"
    assert payload["messages"][1]["images"] == [base64.b64encode(PNG).decode("ascii")]
    assert payload["format"]["type"] == "object"


# --- ruta -----------------------------------------------------------------------


@pytest.fixture
def login(client: TestClient, agency_settings: Tenant) -> dict[str, str]:
    response = client.post(
        "/api/v1/signup",
        json={"name": "Client CCO", "email": "cco@exemplu.ro", "password": "parola-sigura-123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def vision(client: TestClient) -> _FakeVision:
    model = _FakeVision()
    client.app.dependency_overrides[get_vision_model] = lambda: model  # type: ignore[attr-defined]
    return model


def _upload(client: TestClient, headers: dict[str, str], data: bytes) -> httpx.Response:
    return client.post(
        "/api/v1/creative/upload", headers=headers, files={"file": ("reclama.png", data)}
    )


def test_ruta_intoarce_schema_ccoului(
    client: TestClient, login: dict[str, str], vision: _FakeVision
) -> None:
    response = _upload(client, login, PNG)
    assert response.status_code == 200, response.text
    assert set(response.json()) == KEYS


@pytest.mark.parametrize(
    ("data", "status"),
    [(b"%PDF-1.7 nu e imagine", 415), (PNG + b"\x00" * MAX_IMAGE_BYTES, 413)],
    ids=["pdf", "prea-mare"],
)
def test_ruta_refuza_ce_nu_e_imagine_sau_e_prea_mare(
    client: TestClient, login: dict[str, str], vision: _FakeVision, data: bytes, status: int
) -> None:
    assert _upload(client, login, data).status_code == status
    assert vision.calls == []


def test_ruta_cere_autentificare(client: TestClient, vision: _FakeVision) -> None:
    assert _upload(client, {}, PNG).status_code == 401


def test_fara_model_de_vision_configurat_da_503(
    client: TestClient, login: dict[str, str]
) -> None:
    response = _upload(client, login, PNG)
    assert response.status_code == 503
    assert "OLLAMA_VISION_MODEL" in response.json()["detail"]
