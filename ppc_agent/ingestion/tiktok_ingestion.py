"""Ingestie CSV/JSON pentru biblioteca proprie de anunturi TikTok dovedite.

Spre deosebire de generarea de copy (``ppc_agent.copywriter``), aici nu e nevoie
de niciun LLM: intrarile sunt deja structurate (nisa/format/hook/cta), se
valideaza direct prin :class:`~ppc_agent.copywriter.models.TikTokSwipeRecord`
si se adauga in ``tiktok_swipe_library.json`` — un fisier separat, generat, care
creste in timp (analog cu ``proposed_ads_queue.json``). Diferit de cheia
``tiktok_swipe_library`` din ``swipe_file.json``, care e setul curat, comis in
git, folosit ca punct de plecare pentru RAG.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console

from ppc_agent.copywriter.models import TikTokSwipeRecord
from ppc_agent.errors import TikTokIngestError

LIBRARY_FILENAME = "tiktok_swipe_library.json"

# CSV-ul de intrare foloseste nume de coloane "brute"; mapate la campurile
# TikTokSwipeRecord (doar body_text -> mechanism_proof si cta -> cta_text difera).
_CSV_FIELD_MAP: dict[str, str] = {
    "niche": "niche",
    "format": "format",
    "hook_audio": "hook_audio",
    "hook_visual": "hook_visual",
    "body_text": "mechanism_proof",
    "cta": "cta_text",
}
_REQUIRED_CSV_COLUMNS = frozenset(_CSV_FIELD_MAP)


def _stable_ad_id(row: dict[str, str]) -> str:
    """Id stabil derivat din continut — re-rularea aceluiasi CSV da acelasi id."""
    seed = "|".join(row.get(key, "") for key in ("niche", "format", "hook_audio"))
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]


def _record_from_csv_row(row: dict[str, str]) -> TikTokSwipeRecord:
    missing = _REQUIRED_CSV_COLUMNS - set(row)
    if missing:
        raise TikTokIngestError(f"coloane lipsa in CSV: {', '.join(sorted(missing))}")
    mapped: dict[str, str] = {target: row[source] for source, target in _CSV_FIELD_MAP.items()}
    mapped["ad_id"] = _stable_ad_id(row)
    try:
        return TikTokSwipeRecord.model_validate(mapped)
    except ValidationError as exc:
        raise TikTokIngestError(f"rand CSV invalid: {exc}") from exc


def _load_csv(path: Path) -> list[TikTokSwipeRecord]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise TikTokIngestError(f"fisierul CSV este gol: {path}")
        rows = list(reader)
    if not rows:
        raise TikTokIngestError(f"fisierul CSV nu contine niciun rand: {path}")
    return [_record_from_csv_row(row) for row in rows]


def _load_json(path: Path) -> list[TikTokSwipeRecord]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TikTokIngestError(f"fisierul JSON nu e valid: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise TikTokIngestError("fisierul JSON trebuie sa contina o lista nevida de intrari")
    try:
        return [TikTokSwipeRecord.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise TikTokIngestError(f"intrare JSON invalida: {exc}") from exc


def load_input_records(path: Path) -> list[TikTokSwipeRecord]:
    """Citeste si valideaza intrarile dintr-un CSV sau JSON, dupa extensie.

    Args:
        path: Cale catre fisierul de intrare (``.csv`` sau ``.json``).

    Returns:
        Intrarile validate, ca :class:`TikTokSwipeRecord`.

    Raises:
        TikTokIngestError: Fisierul lipseste, are extensie necunoscuta, sau
            continutul nu respecta schema ceruta.
    """
    if not path.is_file():
        raise TikTokIngestError(f"fisierul nu a fost gasit: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".csv":
        return _load_csv(path)
    raise TikTokIngestError(f"extensie necunoscuta (asteptat .csv sau .json): {path}")


def _library_path(output_dir: Path) -> Path:
    return output_dir / LIBRARY_FILENAME


def _load_existing_library(path: Path) -> list[TikTokSwipeRecord]:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [TikTokSwipeRecord.model_validate(item) for item in raw.get("entries", [])]


def run_tiktok_ingest(
    input_path: Path | str, output_dir: Path | str = "."
) -> list[TikTokSwipeRecord]:
    """Valideaza intrarile din ``input_path`` si le adauga in ``tiktok_swipe_library.json``.

    Deduplica dupa ``ad_id`` — re-rularea aceluiasi fisier nu creeaza intrari duplicate.

    Args:
        input_path: CSV sau JSON cu anunturi TikTok dovedite.
        output_dir: Directorul in care traieste/se scrie ``tiktok_swipe_library.json``.

    Returns:
        Doar intrarile noi validate acum (nu tot continutul bibliotecii).

    Raises:
        TikTokIngestError: Daca fisierul de intrare e invalid.
    """
    new_records = load_input_records(Path(input_path))
    library_path = _library_path(Path(output_dir))
    existing = _load_existing_library(library_path)

    existing_ids = {record.ad_id for record in existing}
    added = [record for record in new_records if record.ad_id not in existing_ids]
    merged = existing + added

    library_path.write_text(
        json.dumps(
            {"entries": [record.model_dump() for record in merged]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return added


def render_tiktok_ingest(
    records: list[TikTokSwipeRecord], library_path: Path, console: Console
) -> None:
    """Afiseaza un rezumat al intrarilor noi adaugate in biblioteca.

    Textul liber vine din CSV/JSON furnizat de utilizator — poate contine
    accidental caractere ``[``/``]``, pe care Rich le-ar interpreta ca markup si
    le-ar inghiti din afisaj. Linia per-intrare nu are stilizare Rich intentionata,
    deci foloseste ``markup=False`` — mai robust decat sa scapi manual campurile.
    """
    console.print(
        f"\n[bold]Ingestie TikTok[/bold]  {len(records)} intrari noi -> {library_path.name}"
    )
    for record in records:
        console.print(
            f'  [{record.niche}] {record.format} - hook: "{record.hook_audio[:50]}" '
            f"(activ {record.days_active_proxy}z)",
            markup=False,
        )
    if not records:
        console.print("  [dim]nimic nou - toate intrarile existau deja (acelasi ad_id)[/dim]")
