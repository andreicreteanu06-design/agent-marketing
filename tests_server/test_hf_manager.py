"""Modelele GGUF de pe Hugging Face pentru Ollama si cache-ul Hugging Face - fara retea.

Descarcarea e o functie falsa cu semnatura lui ``hf_hub_download``; Ollama e un
``httpx.MockTransport`` care verifica API-ul documentat (``HEAD``/``POST
/api/blobs/:digest``, ``POST /api/create`` cu ``files``, ``POST /api/show``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from huggingface_hub.errors import LocalEntryNotFoundError

from ppc_agent.decision.forecasting import timesfm_cached
from ppc_agent_server.hf_manager import (
    DEFAULT_PRESET,
    PRESETS,
    TIMESFM_REPO,
    HfManagerError,
    OllamaImporter,
    benchmark,
    cache_report,
    download_gguf,
    file_digest,
    install,
    main,
)
from tests_server.llm_fakes import OLLAMA_TEST_HOST, FakeOllama

PRESET = PRESETS[DEFAULT_PRESET]


def test_the_default_is_small_and_commercially_usable() -> None:
    assert PRESET.commercial and PRESET.license == "Apache-2.0"
    assert PRESET.filename.lower().endswith("q4_k_m.gguf")
    assert not PRESETS["qwen2.5-3b"].commercial  # "Qwen Research License"


class _Hub:
    """``hf_hub_download`` fals: un "cache" pe disc si lista cererilor."""

    def __init__(self, cache: Path, *, cached: bool) -> None:
        self.cache = cache
        self.cached = cached
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        target = self.cache / kwargs["filename"]
        if kwargs.get("local_files_only"):
            if not self.cached:
                raise LocalEntryNotFoundError("nu e in cache")
            return str(target)
        target.write_bytes(b"GGUF" + b"\0" * 2048)
        self.cached = True
        return str(target)


def test_a_cached_model_is_never_downloaded_again(tmp_path: Path) -> None:
    hub = _Hub(tmp_path, cached=False)

    first, downloaded = download_gguf(PRESET, downloader=hub)
    again, downloaded_again = download_gguf(PRESET, downloader=hub)

    assert (downloaded, downloaded_again) == (True, False)
    assert first == again == tmp_path / PRESET.filename
    # Prima data: cache (lipsa) + descarcarea; a doua oara: doar cache-ul, fara retea.
    assert [call.get("local_files_only", False) for call in hub.calls] == [True, False, True]
    assert all(call["repo_id"] == PRESET.repo_id for call in hub.calls)


def test_a_failed_download_explains_itself() -> None:
    def broken(**kwargs: Any) -> str:
        if kwargs.get("local_files_only"):
            raise LocalEntryNotFoundError("nu e in cache")
        raise OSError("No space left on device")

    with pytest.raises(HfManagerError, match="No space left on device"):
        download_gguf(PRESET, downloader=broken)


def test_the_digest_is_the_sha256_ollama_expects(tmp_path: Path) -> None:
    path = tmp_path / "model.gguf"
    path.write_bytes(b"GGUF" * 1000)

    assert file_digest(path) == f"sha256:{hashlib.sha256(b'GGUF' * 1000).hexdigest()}"


class _FakeOllamaStore:
    """Serverul Ollama pentru importul GGUF: blob-uri, modele, ce s-a cerut."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.models: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if path.startswith("/api/blobs/sha256:"):
            digest = path.removeprefix("/api/blobs/")
            if request.method == "HEAD":
                return httpx.Response(200 if digest in self.blobs else 404)
            body = request.read()
            if f"sha256:{hashlib.sha256(body).hexdigest()}" != digest:
                return httpx.Response(400, json={"error": "digest mismatch"})
            self.blobs[digest] = body
            return httpx.Response(201)
        if path == "/api/create":
            body = json.loads(request.content)
            missing = [d for d in body.get("files", {}).values() if d not in self.blobs]
            if missing or body.get("stream") is not False:
                return httpx.Response(400, json={"error": "missing blob"})
            self.models[body["model"]] = body
            return httpx.Response(200, json={"status": "success"})
        if path == "/api/show":
            name = json.loads(request.content)["model"]
            return httpx.Response(200 if name in self.models else 404, json={})
        return httpx.Response(404)


@pytest.fixture
def store() -> _FakeOllamaStore:
    return _FakeOllamaStore()


def _importer(store: _FakeOllamaStore) -> OllamaImporter:
    return OllamaImporter(host=OLLAMA_TEST_HOST, transport=httpx.MockTransport(store))


def test_install_downloads_uploads_and_creates_the_model(
    tmp_path: Path, store: _FakeOllamaStore
) -> None:
    report = install(PRESET, _importer(store), downloader=_Hub(tmp_path, cached=False))

    assert (report.downloaded, report.uploaded, report.created) == (True, True, True)
    created = store.models[PRESET.ollama_name]
    digest = file_digest(tmp_path / PRESET.filename)
    assert created["files"] == {PRESET.filename: digest}
    # Doar pe CPU, cu loc pentru sinteza consiliului (~5000 de tokeni).
    assert created["parameters"] == {"num_ctx": 8192, "num_gpu": 0}
    assert list(store.blobs) == [digest]


def test_the_gpu_is_opt_in(tmp_path: Path, store: _FakeOllamaStore) -> None:
    install(PRESET, _importer(store), downloader=_Hub(tmp_path, cached=False), cpu_only=False)

    assert store.models[PRESET.ollama_name]["parameters"] == {"num_ctx": 8192}


def test_install_is_idempotent(tmp_path: Path, store: _FakeOllamaStore) -> None:
    hub = _Hub(tmp_path, cached=False)
    install(PRESET, _importer(store), downloader=hub)
    store.requests.clear()

    again = install(PRESET, _importer(store), downloader=hub)
    forced = install(PRESET, _importer(store), downloader=hub, force=True)

    assert (again.downloaded, again.uploaded, again.created) == (False, False, False)
    # Recrearea nu mai urca fisierul: blob-ul e deja in Ollama.
    assert (forced.uploaded, forced.created) == (False, True)
    assert ("POST", f"/api/blobs/{file_digest(tmp_path / PRESET.filename)}") not in store.requests


def test_a_noncommercial_license_needs_an_explicit_yes(
    tmp_path: Path, store: _FakeOllamaStore
) -> None:
    hub = _Hub(tmp_path, cached=False)

    with pytest.raises(HfManagerError, match="fără uz comercial"):
        install(PRESETS["qwen2.5-3b"], _importer(store), downloader=hub)
    assert hub.calls == [] and store.requests == []

    report = install(
        PRESETS["qwen2.5-3b"], _importer(store), downloader=hub, allow_noncommercial=True
    )
    assert report.created


def test_ollama_down_is_explained(tmp_path: Path) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    importer = OllamaImporter(host=OLLAMA_TEST_HOST, transport=httpx.MockTransport(down))

    with pytest.raises(HfManagerError, match="ollama serve"):
        install(PRESET, importer, downloader=_Hub(tmp_path, cached=True))


def test_the_benchmark_measures_the_first_token_on_a_council_sized_prompt(
    fake_ollama: FakeOllama,
) -> None:
    ticks: Iterator[float] = iter([0.0, 6.5, 9.0])  # inceput, primul token, final
    fake_ollama.reply = "Da, dar controlat."

    result = benchmark(fake_ollama.client(), prompt_chars=6000, clock=lambda: next(ticks))

    assert (result.first_token_seconds, result.total_seconds, result.chunks) == (6.5, 9.0, 3)
    assert result.within_target and result.text == "Da, dar controlat."
    [body] = fake_ollama.requests
    assert len(body["messages"][1]["content"]) > 6000


class _Repo:
    def __init__(self, repo_id: str, size: int, files: int) -> None:
        self.repo_id, self.size_on_disk, self.nb_files = repo_id, size, files


class _Scan:
    def __init__(self, *repos: _Repo) -> None:
        self.repos = set(repos)


def test_the_cache_report_lists_models_and_flags_what_would_be_downloaded(
    tmp_path: Path,
) -> None:
    persistent = str(Path.home() / ".cache" / "huggingface" / "hub")
    scan = _Scan(_Repo(TIMESFM_REPO, 925_000_000, 3), _Repo(PRESET.repo_id, 1_120_000_000, 1))

    report = cache_report(persistent, scanner=lambda cache_dir: scan)

    assert [(repo.repo_id, repo.size_gb) for repo in report.repos] == [
        (PRESET.repo_id, 1.12),
        (TIMESFM_REPO, 0.93),
    ]
    assert report.warnings == ()

    empty = cache_report(str(tmp_path), scanner=lambda cache_dir: _Scan())
    assert any("director temporar" in warning for warning in empty.warnings)
    assert any("TimesFM" in warning for warning in empty.warnings)
    assert any("Niciun model GGUF" in warning for warning in empty.warnings)


def test_a_missing_cache_is_an_empty_report(tmp_path: Path) -> None:
    report = cache_report(str(tmp_path / "nu-exista"))

    assert report.repos == ()


def _fake_hf_cache(root: Path, repo_id: str, filename: str) -> None:
    folder = root / f"models--{repo_id.replace('/', '--')}"
    (folder / "refs").mkdir(parents=True)
    (folder / "refs" / "main").write_text("abc123")
    snapshot = folder / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / filename).write_bytes(b"weights")


def test_timesfm_loads_offline_once_its_weights_are_cached(tmp_path: Path) -> None:
    assert timesfm_cached(str(tmp_path)) is False

    _fake_hf_cache(tmp_path, TIMESFM_REPO, "model.safetensors")

    assert timesfm_cached(str(tmp_path)) is True


def test_the_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models"]) == 0
    listing = capsys.readouterr().out
    assert "qwen2.5-1.5b" in listing and "(implicit)" in listing and "NECOMERCIAL" in listing

    # Licenta se verifica inainte de orice descarcare sau cerere catre Ollama.
    assert main(["install", "--preset", "qwen2.5-3b", "--host", "localhost"]) == 1
    assert "fără uz comercial" in capsys.readouterr().out
