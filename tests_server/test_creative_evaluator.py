"""CCO-ul ca Senior Media Buyer: modelul observa fapte, codul decide.

Fara model real si fara retea (modelul e dublat). Video-urile se genereaza local cu
ffmpeg (testele lor sar fara ffmpeg): un clip negru (timp mort) si unul in miscare.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from ppc_agent.errors import ProviderError, SetupRequiredError
from ppc_agent_server.models import Tenant
from ppc_agent_server.routers.creative import get_vision_model
from ppc_agent_server.services.creative_evaluator import (
    MAX_IMAGE_BYTES,
    evaluate_creative,
    format_suitability,
    image_size,
    vision_model_from_settings,
)
from ppc_agent_server.services.llm_client import (
    LLMUnavailableError,
    OllamaChatClient,
    OllamaError,
)
from ppc_agent_server.settings import get_server_settings

KEYS = {"asset_type", "decision", "scores", "detected_risks", "priority_fixes"}


def _png(width: int = 1080, height: int = 1350) -> bytes:
    """Antetul unui PNG cu dimensiunile date - destul pentru CCO (nu decodeaza pixeli)."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00" * 8
    )


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = (
        b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _seen(**overrides: Any) -> str:
    """O reclama curata: alt domeniu, firma vizibila, hook dominant, 2 blocuri de text."""
    facts: dict[str, Any] = {
        "domain": "other",
        "brand_identity_visible": True,
        "conditions_stated": True,
        "spelling_errors": [],
        "stock_photo": False,
        "claims_authentic": False,
        "text_blocks": 2,
        "main_hook": "Revizie completă în 24h",
        "hook_is_dominant": True,
        "visual_hook": 8,
        "text_hook_present": True,
        "opens_with_brand_intro": False,
        "risks": [],
        "fixes": ["Crește contrastul butonului"],
    }
    facts.update(overrides)
    return json.dumps(facts)


#: Anuntul real testat (recrutare, 2300 EUR/luna, fara firma, titlu de 5 randuri, 3:4).
RECRUITMENT = _seen(
    domain="recruitment",
    brand_identity_visible=False,
    conditions_stated=True,
    spelling_errors=["CĂUTA", "INGRIJITOARE", "GERMANA", "Nurnberg", "locuieste"],
    stock_photo=True,
    text_blocks=7,
    main_hook="2300€/luna",
    hook_is_dominant=False,
    visual_hook=6,
)


class _FakeVision:
    """Modelul cu vision, dublat: raspunde ce i se da si tine minte ce a primit."""

    def __init__(self, answer: str = "", *, error: Exception | None = None) -> None:
        self.answer = answer or _seen()
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


def _evaluate(answer: str = "", media: bytes | None = None) -> dict[str, Any]:
    return evaluate_creative(media or _png(), model=_FakeVision(answer))


# --- decizia ----------------------------------------------------------------------


def test_o_creativa_curata_e_eligibila_pentru_test() -> None:
    result = _evaluate()

    assert set(result) == KEYS
    assert result["asset_type"] == "image"
    assert result["decision"] == "ELIGIBLE_FOR_TEST"
    assert result["scores"] == {
        "trust": 10,
        "hook_power": 8,
        "cognitive_load_and_hierarchy": 9,
        "format_suitability": 10,
    }
    assert result["detected_risks"] == []
    assert result["priority_fixes"] == ["Crește contrastul butonului"]


def test_anuntul_de_recrutare_fara_firma_cere_om_in_bucla() -> None:
    """Cazul real: recrutare, fara firma, greseli, hook ingropat, 7 blocuri, 3:4."""
    result = _evaluate(RECRUITMENT, _png(1080, 1440))

    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert result["scores"] == {
        "trust": 0,  # 3 (sensibil, fara firma) - 4 (5 greseli de scriere)
        "hook_power": 5,  # plafonat: hook-ul nu domina
        "cognitive_load_and_hierarchy": 1,  # 7 blocuri concurente
        "format_suitability": 7,  # 3:4, feed-ul il taie la 4:5
    }
    risks = result["detected_risks"]
    assert risks[0] == "domeniu sensibil (recrutare): încrederea decide"
    assert "lipsește identitatea: niciun logo sau nume de firmă verificabil" in risks
    assert any(risk.startswith("greșeli de scriere (5): «CĂUTA»") for risk in risks)
    assert "hook-ul principal («2300€/luna») e îngropat în text mic" in risks
    assert result["priority_fixes"] == [
        "Adaugă numele firmei și logo-ul (plus licența, unde e cerută)",
        "Corectează ortografia și diacriticele",
        "Păstrează pe imagine maximum 3 blocuri; restul merge în textul reclamei",
    ]


def test_fara_firma_in_afara_domeniilor_sensibile_scade_dar_nu_cere_om() -> None:
    result = _evaluate(_seen(brand_identity_visible=False))
    assert result["scores"]["trust"] == 7
    assert result["decision"] == "ELIGIBLE_FOR_TEST"


@pytest.mark.parametrize(
    ("overrides", "trust"),
    [
        ({"spelling_errors": ["unu", "doi"]}, 9),
        ({"spelling_errors": ["unu", "doi", "trei"]}, 6),
        ({"stock_photo": True}, 10),  # stock-ul nu e rau in sine...
        ({"stock_photo": True, "claims_authentic": True}, 6),  # ...dar nu ca "echipa reala"
        ({"domain": "finance", "conditions_stated": False}, 7),
    ],
    ids=["2-greseli", "greseli-masive", "stock", "stock-drept-autentic", "fara-conditii"],
)
def test_scorul_de_incredere(overrides: dict[str, Any], trust: int) -> None:
    assert _evaluate(_seen(**overrides))["scores"]["trust"] == trust


def test_peste_3_blocuri_de_text_cer_retusare() -> None:
    result = _evaluate(_seen(text_blocks=5))
    assert result["scores"]["cognitive_load_and_hierarchy"] == 3
    assert result["decision"] == "REVISE_BEFORE_TEST"
    assert "5 blocuri de text concurente: ochiul nu știe unde să se uite" in (
        result["detected_risks"]
    )


def test_un_hook_ingropat_plafoneaza_ierarhia_si_hook_ul() -> None:
    scores = _evaluate(_seen(hook_is_dominant=False, visual_hook=9))["scores"]
    assert scores["cognitive_load_and_hierarchy"] == 4
    assert scores["hook_power"] == 5


# --- formatul, masurat din fisier ------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height", "score"),
    [(1080, 1350, 10), (1080, 1920, 9), (1080, 1080, 8), (1080, 1440, 7), (1200, 628, 5),
     (500, 625, 7)],
    ids=["4:5", "9:16", "1:1", "3:4", "1.91:1", "4:5-mic"],
)
def test_formatul_imaginii(width: int, height: int, score: int) -> None:
    assert format_suitability("image", width, height)[0] == score


def test_dimensiunile_se_citesc_din_png_si_jpeg() -> None:
    assert image_size(_png(1080, 1440)) == (1080, 1440)
    assert image_size(_jpeg(1200, 628)) == (1200, 628)


# --- video ------------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg lipsește"
)


def _video(tmp_path: Path, source: str) -> bytes:
    path = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source, "-t", "4",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path.read_bytes()


@needs_ffmpeg
def test_un_video_care_incepe_cu_timp_mort_pierde_hook_ul(tmp_path: Path) -> None:
    model = _FakeVision()
    result = evaluate_creative(
        _video(tmp_path, "color=c=black:s=720x1280:r=25"), model=model
    )

    assert result["asset_type"] == "video"
    assert result["scores"]["hook_power"] == 3
    assert result["scores"]["format_suitability"] == 10  # 9:16
    assert result["decision"] == "REVISE_BEFORE_TEST"
    assert "timp mort în primele 3 secunde" in result["detected_risks"][0]
    assert len(model.calls[0]["images"]) == 4  # cadrele de la 0, 1, 2 si 3 s
    assert "first 3 seconds" in model.calls[0]["system"]


@needs_ffmpeg
def test_un_video_in_miscare_fara_intro_trece(tmp_path: Path) -> None:
    result = evaluate_creative(
        _video(tmp_path, "testsrc2=s=720x1280:r=25"), model=_FakeVision()
    )
    assert result["scores"]["hook_power"] == 8
    assert result["decision"] == "ELIGIBLE_FOR_TEST"


@needs_ffmpeg
def test_un_intro_de_logo_prabuseste_hook_ul(tmp_path: Path) -> None:
    result = evaluate_creative(
        _video(tmp_path, "testsrc2=s=720x1280:r=25"),
        model=_FakeVision(_seen(opens_with_brand_intro=True)),
    )
    assert result["scores"]["hook_power"] == 3
    assert "video-ul începe cu un intro de brand/logo" in result["detected_risks"]


@needs_ffmpeg
def test_un_video_stricat_e_ilizibil() -> None:
    with pytest.raises(ValueError, match="nu se poate citi"):
        evaluate_creative(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64, model=_FakeVision())


# --- modelul -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    ["nu e json", _seen(text_blocks=-1), _seen(fixes=[]), json.dumps({"domain": "other"})],
    ids=["text", "negativ", "fara-remedieri", "incomplet"],
)
def test_un_raspuns_invalid_al_modelului_e_o_eroare_de_furnizor(answer: str) -> None:
    with pytest.raises(ProviderError, match="invalid"):
        _evaluate(answer)


def test_tip_nesuportat_sau_prea_mare() -> None:
    model = _FakeVision()
    with pytest.raises(ValueError, match="JPEG/PNG"):
        evaluate_creative(b"GIF89a....", model=model)
    with pytest.raises(ValueError, match="depășește"):
        evaluate_creative(_png() + b"\x00" * MAX_IMAGE_BYTES, model=model)
    assert model.calls == []


def test_ollama_oprit_e_o_problema_de_configurare_iar_o_cadere_e_de_furnizor() -> None:
    with pytest.raises(SetupRequiredError):
        evaluate_creative(_png(), model=_FakeVision(error=LLMUnavailableError("oprit")))
    with pytest.raises(ProviderError):
        evaluate_creative(_png(), model=_FakeVision(error=OllamaError("a picat")))


def test_promptul_cere_fapte_nu_scoruri_si_fara_exemple_de_copiat() -> None:
    model = _FakeVision()
    evaluate_creative(_png(), model=model)
    system = model.calls[0]["system"]
    assert "do not score the ad" in system
    assert "a phone number alone is NOT an identity" in system


def test_fiecare_text_si_lista_din_schema_are_plafon() -> None:
    """Vazut real: fara plafon, modelul mic a intrat in bucla ("token repeat limit")."""
    model = _FakeVision()
    evaluate_creative(_png(), model=model)
    properties = model.calls[0]["schema"]["properties"]
    for name, spec in properties.items():
        if spec.get("type") == "string" and "enum" not in spec:  # enum-ul e deja marginit
            assert "maxLength" in spec, name
        if spec.get("type") == "array":
            assert "maxItems" in spec and "maxLength" in spec["items"], name


def test_clientul_de_vision_are_samanta_fixa_in_cerere() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, text=json.dumps({"message": {"content": _seen()}, "done": True})
        )

    settings = get_server_settings().model_copy(
        update={"ollama_host": "http://ollama.test", "ollama_vision_model": "gemma3:4b"}
    )
    client = vision_model_from_settings(settings)
    client = dataclasses.replace(client, transport=httpx.MockTransport(handler))
    evaluate_creative(_png(), model=client)
    assert seen[0]["options"]["seed"] == 7
    assert seen[0]["options"]["temperature"] > 0


def test_ollama_primeste_imaginea_si_schema_in_cerere() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        lines = [
            json.dumps({"message": {"content": _seen()}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        return httpx.Response(200, text="\n".join(lines))

    client = OllamaChatClient(
        host="http://ollama.test", model="gemma3:4b", transport=httpx.MockTransport(handler)
    )
    assert evaluate_creative(_png(), model=client)["decision"] == "ELIGIBLE_FOR_TEST"

    [payload] = seen
    assert payload["messages"][1]["images"] == [base64.b64encode(_png()).decode("ascii")]
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
        "/api/v1/creative/upload", headers=headers, files={"file": ("reclama", data)}
    )


def test_ruta_intoarce_verdictul_ccoului(
    client: TestClient, login: dict[str, str], vision: _FakeVision
) -> None:
    response = _upload(client, login, _png())
    assert response.status_code == 200, response.text
    assert set(response.json()) == KEYS


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"%PDF-1.7 nu e imagine", 415),
        (_png() + b"\x00" * MAX_IMAGE_BYTES, 413),
        (b"\x89PNG\r\n\x1a\n", 422),  # semnatura buna, fara antet
    ],
    ids=["pdf", "prea-mare", "ilizibil"],
)
def test_ruta_refuza_ce_nu_poate_evalua(
    client: TestClient, login: dict[str, str], vision: _FakeVision, data: bytes, status: int
) -> None:
    assert _upload(client, login, data).status_code == status
    assert vision.calls == []


def test_ruta_cere_autentificare(client: TestClient, vision: _FakeVision) -> None:
    assert _upload(client, {}, _png()).status_code == 401


def test_fara_model_de_vision_configurat_da_503(
    client: TestClient, login: dict[str, str]
) -> None:
    response = _upload(client, login, _png())
    assert response.status_code == 503
    assert "OLLAMA_VISION_MODEL" in response.json()["detail"]
