"""Modele GGUF de pe Hugging Face pentru Ollama pe CPU, si cache-ul Hugging Face.

Vocea consiliului (Sistemul 2, ``services/llm_client.py``) ruleaza pe Ollama, local,
si scrie un singur text: sinteza Reginei. Pe CPU, un model de 8B (``llama3``,
implicitul) citeste promptul ei (~5000 de tokeni) prea incet ca primul token sa vina
in termenul circuit-breaker-ului (``OLLAMA_FIRST_TOKEN_TIMEOUT``, 180 s). Utilitarul
aduce o varianta cuantizata mica (Q4_K_M) si o incarca direct in Ollama-ul local:

1. **descarca** fisierul GGUF cu ``huggingface_hub`` - intai din cache
   (``local_files_only``), abia apoi din retea; a doua rulare nu mai descarca nimic;
2. **il urca** in Ollama ca blob (``POST /api/blobs/sha256:<digest>``), doar daca nu
   e deja acolo (``HEAD``);
3. **creeaza modelul** (``POST /api/create`` cu ``files``) - Ollama ia sablonul de chat
   din metadatele GGUF. Implicit **doar pe CPU** (``num_gpu 0``): pe placile grafice
   integrate, backend-ul GPU al Ollama a dat text fara sens cu Qwen2.5 (masurat pe
   masina de dezvoltare), iar tinta e oricum CPU-ul. Contextul implicit e 8192 de
   tokeni: sinteza consiliului are ~5000 si ar fi fost taiata la 4096;
4. **il masoara** (``benchmark``): timpul pana la primul token si viteza, pe un prompt
   de marimea sintezei consiliului. Pe CPU, primul token depinde mai ales de lungimea
   promptului (citirea lui), nu de lungimea raspunsului - de aceea masuram, nu promitem.

Licentele conteaza: platforma e comerciala. Presetarile cu licenta necomerciala (Qwen2.5
3B, "Qwen Research License") se instaleaza doar cu ``--allow-noncommercial``.

``cache`` verifica ce e deja in cache-ul Hugging Face (``HF_HOME``): checkpoint-ul
TimesFM (propunerile de buget din CLI) si modelele GGUF de aici - si avertizeaza cand
cache-ul sta intr-un director temporar, care se pierde la repornire (atunci fiecare
rulare de noapte ar descarca din nou).

Folosire::

    python -m ppc_agent_server.hf_manager models
    python -m ppc_agent_server.hf_manager install [--preset qwen2.5-1.5b]
    python -m ppc_agent_server.hf_manager benchmark [--model qwen2.5-1.5b-q4km]
    python -m ppc_agent_server.hf_manager cache
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from huggingface_hub import hf_hub_download, scan_cache_dir
from huggingface_hub.errors import CacheNotFound, LocalEntryNotFoundError

from ppc_agent_server.services.llm_client import (
    OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS,
    OllamaChatClient,
)
from ppc_agent_server.settings import get_server_settings, normalize_ollama_host

#: Checkpoint-ul TimesFM folosit de ``ppc_agent.decision.forecasting``.
TIMESFM_REPO = "google/timesfm-2.5-200m-pytorch"
#: Cat citim dintr-o data din GGUF (digest si upload): 1 MiB.
_CHUNK = 1 << 20
#: Urcarea unui GGUF de 1-3 GB in Ollama, pe loopback: generos.
UPLOAD_TIMEOUT_SECONDS = 600.0
#: Tinta primului token, aceeasi ca circuit-breaker-ul consiliului.
FIRST_TOKEN_TARGET_SECONDS = OLLAMA_FIRST_TOKEN_TIMEOUT_SECONDS
#: Promptul sintezei consiliului (singurul apel LLM), masurat: 12-13k caractere.
SYNTHESIS_PROMPT_CHARS = 12500
#: Contextul modelului creat: sinteza consiliului are ~5000 de tokeni (fapte + pareri).
DEFAULT_NUM_CTX = 8192


@dataclass(frozen=True, slots=True)
class GgufPreset:
    """Un model GGUF cuantizat, cum il aducem de pe Hugging Face in Ollama."""

    key: str
    repo_id: str
    filename: str
    #: Numele sub care il creeaza Ollama (``OLLAMA_MODEL``).
    ollama_name: str
    size_gb: float
    license: str
    #: ``False`` = licenta nu permite uzul comercial fara acord separat.
    commercial: bool
    note: str


PRESETS: dict[str, GgufPreset] = {
    preset.key: preset
    for preset in (
        GgufPreset(
            "qwen2.5-1.5b",
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "qwen2.5-1.5b-q4km",
            1.12,
            "Apache-2.0",
            True,
            "Cel mai rapid pe CPU: sinteza consiliului porneste in ~100 s pe 8 nuclee.",
        ),
        GgufPreset(
            "llama3.2-3b",
            "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "llama3.2-3b-q4km",
            2.02,
            "Llama 3.2 Community License",
            True,
            "Echilibru viteza/calitate; licenta cere mentiunea «Built with Llama».",
        ),
        GgufPreset(
            "gemma3-4b",
            "unsloth/gemma-3-4b-it-GGUF",
            "gemma-3-4b-it-Q4_K_M.gguf",
            "gemma3-4b-q4km",
            2.49,
            "Gemma Terms of Use",
            True,
            "Romana cea mai buna dintre cele mici; de ~2,5 ori mai lent decat 1.5B pe CPU.",
        ),
        GgufPreset(
            "qwen2.5-3b",
            "Qwen/Qwen2.5-3B-Instruct-GGUF",
            "qwen2.5-3b-instruct-q4_k_m.gguf",
            "qwen2.5-3b-q4km",
            2.1,
            "Qwen Research License",
            False,
            "Licenta de cercetare: fara uz comercial fara acordul Alibaba Cloud.",
        ),
    )
}
DEFAULT_PRESET = "qwen2.5-1.5b"


class HfManagerError(RuntimeError):
    """Un pas n-a mers (descarcare, Ollama, licenta) - mesajul spune ce e de facut."""


# --- 1. descarcarea, din cache intai -------------------------------------------------

Downloader = Callable[..., str]


def download_gguf(
    preset: GgufPreset,
    *,
    cache_dir: str | None = None,
    token: str | None = None,
    downloader: Downloader = hf_hub_download,
) -> tuple[Path, bool]:
    """Calea GGUF-ului in cache-ul Hugging Face si daca a fost descarcat acum.

    Intai ``local_files_only``: un fisier deja in cache nu face nicio cerere in retea
    (nici macar verificarea de versiune). Doar daca lipseste, se descarca - o data.
    """
    common: dict[str, Any] = {
        "repo_id": preset.repo_id,
        "filename": preset.filename,
        "cache_dir": cache_dir,
    }
    try:
        return Path(downloader(**common, local_files_only=True)), False
    except LocalEntryNotFoundError:
        pass
    try:
        return Path(downloader(**common, token=token)), True
    except Exception as exc:  # retea, spatiu pe disc, repo mutat: mesaj pentru om
        raise HfManagerError(
            f"Descărcarea {preset.repo_id}/{preset.filename} a eșuat ({type(exc).__name__}: "
            f"{str(exc)[:200]})"
        ) from exc


def file_digest(path: Path) -> str:
    """``sha256:<hex>`` al fisierului - adresa blob-ului in Ollama."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            sha.update(chunk)
    return f"sha256:{sha.hexdigest()}"


# --- 2-3. incarcarea in Ollama -------------------------------------------------------


def _chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        yield from iter(lambda: handle.read(_CHUNK), b"")


@dataclass(frozen=True, slots=True)
class OllamaImporter:
    """API-ul Ollama pentru modele create din GGUF: blob-uri si ``/api/create``."""

    host: str
    transport: httpx.BaseTransport | None = None
    timeout: float = UPLOAD_TIMEOUT_SECONDS

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self.transport, timeout=httpx.Timeout(self.timeout, connect=5.0)
        )

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with self._client() as client:
                return client.request(method, f"{self.host}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise HfManagerError(
                f"Ollama nu răspunde la {self.host} ({type(exc).__name__}): pornește-l cu "
                "«ollama serve» sau corectează OLLAMA_HOST"
            ) from exc

    def installed(self, name: str) -> bool:
        return self._call("POST", "/api/show", json={"model": name}).status_code == 200

    def has_blob(self, digest: str) -> bool:
        return self._call("HEAD", f"/api/blobs/{digest}").status_code == 200

    def push_blob(self, path: Path, digest: str) -> None:
        response = self._call("POST", f"/api/blobs/{digest}", content=_chunks(path))
        if response.status_code not in (200, 201):
            raise HfManagerError(
                f"Ollama a refuzat fișierul ({response.status_code}): {response.text[:200]}"
            )

    def create(
        self, name: str, filename: str, digest: str, *, num_ctx: int, cpu_only: bool = True
    ) -> None:
        parameters: dict[str, int] = {"num_ctx": num_ctx}
        if cpu_only:
            parameters["num_gpu"] = 0  # niciun strat pe GPU
        body = {
            "model": name,
            "files": {filename: digest},
            "parameters": parameters,
            "stream": False,
        }
        response = self._call("POST", "/api/create", json=body)
        if response.status_code != 200:
            raise HfManagerError(
                f"Ollama n-a creat modelul «{name}» ({response.status_code}): "
                f"{response.text[:200]}"
            )


@dataclass(frozen=True, slots=True)
class InstallReport:
    preset: GgufPreset
    path: Path
    downloaded: bool
    uploaded: bool
    created: bool


def install(
    preset: GgufPreset,
    importer: OllamaImporter,
    *,
    allow_noncommercial: bool = False,
    force: bool = False,
    num_ctx: int = DEFAULT_NUM_CTX,
    cpu_only: bool = True,
    cache_dir: str | None = None,
    token: str | None = None,
    downloader: Downloader = hf_hub_download,
) -> InstallReport:
    """Modelul, din cache sau de pe Hugging Face, creat in Ollama. Idempotent.

    Raises:
        HfManagerError: licenta necomerciala fara acord, descarcare sau Ollama picate.
    """
    if not preset.commercial and not allow_noncommercial:
        raise HfManagerError(
            f"«{preset.key}» are licența «{preset.license}», fără uz comercial. Alege alt "
            "model sau confirmă cu --allow-noncommercial că îl folosești doar pentru teste."
        )
    path, downloaded = download_gguf(
        preset, cache_dir=cache_dir, token=token, downloader=downloader
    )
    if importer.installed(preset.ollama_name) and not force:
        return InstallReport(preset, path, downloaded, uploaded=False, created=False)
    digest = file_digest(path)
    uploaded = not importer.has_blob(digest)
    if uploaded:
        importer.push_blob(path, digest)
    importer.create(
        preset.ollama_name, preset.filename, digest, num_ctx=num_ctx, cpu_only=cpu_only
    )
    return InstallReport(preset, path, downloaded, uploaded=uploaded, created=True)


# --- 4. masuratoarea ---------------------------------------------------------------------

#: Un rand de fapte ca ale consiliului; se repeta pana la marimea ceruta.
_FACT_LINE = (
    "- Contul e rentabil: CPA-ul e 39,23 RON (26 de conversii din 1020 RON cheltuiți), sub "
    "ținta de 80 RON. Publicul ideal e «Ocupatul pragmatic»: vrea să rezolve totul din "
    "telefon, decide repede (Sistemul 1) și îl oprește prețul neafișat.\n"
)
BENCH_SYSTEM = (
    "Ești Regina, strategul de brand al unei agenții de marketing. Răspunzi în română, "
    "în maximum 60 de cuvinte, doar din FAPTE."
)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    model: str
    prompt_chars: int
    first_token_seconds: float
    total_seconds: float
    chunks: int
    text: str

    @property
    def within_target(self) -> bool:
        return self.first_token_seconds <= FIRST_TOKEN_TARGET_SECONDS


def benchmark(
    client: OllamaChatClient,
    *,
    prompt_chars: int = SYNTHESIS_PROMPT_CHARS,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkResult:
    """Primul token si durata totala pe un prompt de marimea celor din consiliu."""
    facts = (_FACT_LINE * (prompt_chars // len(_FACT_LINE) + 1))[:prompt_chars]
    user = f"FAPTE:\n{facts}\n\nÎNTREBAREA CLIENTULUI: «Merită să cresc bugetul?»"
    started = clock()
    first: float | None = None
    parts: list[str] = []
    for chunk in client.stream(system=BENCH_SYSTEM, user=user):
        if first is None:
            first = clock() - started
        parts.append(chunk)
    total = clock() - started
    return BenchmarkResult(
        model=client.model,
        prompt_chars=len(user),
        first_token_seconds=round(first if first is not None else total, 2),
        total_seconds=round(total, 2),
        chunks=len(parts),
        text="".join(parts).strip(),
    )


# --- cache-ul Hugging Face -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CachedRepo:
    repo_id: str
    size_gb: float
    files: int


@dataclass(frozen=True, slots=True)
class CacheReport:
    cache_dir: str
    repos: tuple[CachedRepo, ...]
    #: Ce lipseste sau ce e riscant, in cuvinte.
    warnings: tuple[str, ...]


Scanner = Callable[[str | None], Any]


def _is_temporary(path: str) -> bool:
    resolved = Path(path).resolve()
    temporary = [Path(tempfile.gettempdir()).resolve(), Path("/tmp")]
    return any(resolved == root or root in resolved.parents for root in temporary)


def cache_report(cache_dir: str | None = None, *, scanner: Scanner = scan_cache_dir) -> CacheReport:
    """Ce e in cache-ul Hugging Face si ce ar costa descarcari la fiecare rulare."""
    from huggingface_hub.constants import HF_HUB_CACHE

    where = cache_dir or HF_HUB_CACHE
    try:
        info = scanner(cache_dir)
        repos = tuple(
            CachedRepo(repo.repo_id, round(repo.size_on_disk / 1e9, 2), repo.nb_files)
            for repo in sorted(info.repos, key=lambda repo: repo.repo_id)
        )
    except CacheNotFound:
        repos = ()
    warnings: list[str] = []
    if _is_temporary(where):
        warnings.append(
            f"Cache-ul Hugging Face e într-un director temporar ({where}): se pierde la "
            "repornire și modelele se descarcă din nou. Setează HF_HOME pe un disc persistent."
        )
    cached = {repo.repo_id for repo in repos}
    if TIMESFM_REPO not in cached:
        warnings.append(
            f"TimesFM ({TIMESFM_REPO}) nu e în cache: prima prognoză cu --forecast-engine "
            "timesfm îl descarcă (~200-400 MB), apoi rămâne aici."
        )
    if not cached & {preset.repo_id for preset in PRESETS.values()}:
        warnings.append("Niciun model GGUF în cache: rulează «install» pentru vocea pe CPU.")
    return CacheReport(where, repos, tuple(warnings))


# --- linia de comanda ---------------------------------------------------------------------


def _print(text: str = "") -> None:
    # Consola Windows (cp1250) nu are "ș"/"ț" cu virgula: un caracter inlocuit, nu o eroare.
    encoding = sys.stdout.encoding or "utf-8"
    line = f"{text}\n".encode(encoding, errors="replace").decode(encoding)
    sys.stdout.write(line)


def _importer(host: str | None) -> OllamaImporter:
    raw = host if host is not None else get_server_settings().ollama_host
    normalized = normalize_ollama_host(raw)
    if not normalized:
        raise HfManagerError("OLLAMA_HOST e gol: spune unde rulează Ollama cu --host.")
    return OllamaImporter(host=normalized)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ppc_agent_server.hf_manager",
        description="Modele GGUF de pe Hugging Face pentru Ollama pe CPU.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("models", help="presetările, cu licența și mărimea lor")
    install_cmd = commands.add_parser("install", help="descarcă (din cache întâi) și creează")
    install_cmd.add_argument("--preset", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    install_cmd.add_argument("--host", help="adresa Ollama (implicit OLLAMA_HOST)")
    install_cmd.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    install_cmd.add_argument(
        "--allow-gpu", action="store_true", help="lasă Ollama să mute straturi pe GPU"
    )
    install_cmd.add_argument("--force", action="store_true", help="recreează modelul")
    install_cmd.add_argument("--allow-noncommercial", action="store_true")
    bench_cmd = commands.add_parser("benchmark", help="primul token și viteza, pe CPU")
    bench_cmd.add_argument("--model", default=PRESETS[DEFAULT_PRESET].ollama_name)
    bench_cmd.add_argument("--host", help="adresa Ollama (implicit OLLAMA_HOST)")
    bench_cmd.add_argument("--prompt-chars", type=int, default=SYNTHESIS_PROMPT_CHARS)
    bench_cmd.add_argument(
        "--timeout",
        type=float,
        default=FIRST_TOKEN_TARGET_SECONDS,
        help="cât așteaptă primul token (secunde)",
    )
    cache_cmd = commands.add_parser("cache", help="ce e în cache-ul Hugging Face")
    cache_cmd.add_argument("--cache-dir")
    args = parser.parse_args(argv)

    try:
        if args.command == "models":
            for preset in PRESETS.values():
                use = "comercial" if preset.commercial else "NECOMERCIAL"
                _print(
                    f"{preset.key:<14} {preset.size_gb:>5.2f} GB  {use:<11} {preset.license}"
                    f"{'  (implicit)' if preset.key == DEFAULT_PRESET else ''}"
                )
                _print(f"{'':<14} {preset.repo_id}/{preset.filename} - {preset.note}")
            return 0
        if args.command == "install":
            report = install(
                PRESETS[args.preset],
                _importer(args.host),
                allow_noncommercial=args.allow_noncommercial,
                force=args.force,
                num_ctx=args.num_ctx,
                cpu_only=not args.allow_gpu,
            )
            source = "descărcat acum" if report.downloaded else "din cache, fără descărcare"
            _print(f"GGUF: {report.path} ({source})")
            if report.created:
                _print(f"Ollama: modelul «{report.preset.ollama_name}» a fost creat.")
            else:
                _print(f"Ollama: «{report.preset.ollama_name}» exista deja (--force îl recreează).")
            _print(f"În .env: OLLAMA_MODEL={report.preset.ollama_name}")
            return 0
        if args.command == "benchmark":
            importer = _importer(args.host)
            client = OllamaChatClient(
                host=importer.host,
                model=args.model,
                first_token_timeout=args.timeout,
                keep_alive=None,
            )
            result = benchmark(client, prompt_chars=args.prompt_chars)
            verdict = "sub" if result.within_target else "PESTE"
            _print(
                f"{result.model}: primul token în {result.first_token_seconds} s ({verdict} "
                f"ținta de {FIRST_TOKEN_TARGET_SECONDS:.0f} s), total {result.total_seconds} s, "
                f"{result.chunks} fragmente, prompt de {result.prompt_chars} caractere."
            )
            return 0 if result.within_target else 2
        report_cache = cache_report(args.cache_dir)
        _print(f"Cache Hugging Face: {report_cache.cache_dir}")
        for repo in report_cache.repos:
            _print(f"  {repo.repo_id}: {repo.size_gb} GB, {repo.files} fișiere")
        for warning in report_cache.warnings:
            _print(f"  ! {warning}")
        return 0
    except HfManagerError as exc:
        _print(f"Eroare: {exc}")
        return 1
    except Exception as exc:  # benchmark: Ollama oprit, model lipsa - mesaj, nu traceback
        _print(f"Eroare: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
