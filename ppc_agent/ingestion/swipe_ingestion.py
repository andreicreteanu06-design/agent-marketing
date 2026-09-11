"""Ingestie CSV universala pentru biblioteca omnicanal (Google/Meta/TikTok).

Spre deosebire de :mod:`ppc_agent.ingestion.tiktok_ingestion` (care scrie
intr-un fisier separat, generat, ``tiktok_swipe_library.json``), aici tinta e
chiar cheia ``omnichannel_swipe_library`` din ``swipe_file.json`` — fisierul
sursa, comis in git. Ingestia e deci un instrument de curatare a bibliotecii
(adauga anunturi dovedite, validate), nu de acumulare bruta. Nu e nevoie de
niciun LLM: intrarile sunt deja structurate.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console

from ppc_agent.copywriter.models import OmniPlatform, OmniSwipeRecord
from ppc_agent.copywriter.swipe import default_swipe_path
from ppc_agent.errors import SwipeIngestError

# CSV-ul de intrare nu are coloane platform/ad_id: platforma vine din
# argumentul --platform (un CSV = un lot dintr-o singura platforma), iar
# ad_id se deriva stabil din continut (ca la tiktok_ingestion.py).
_REQUIRED_CSV_COLUMNS = frozenset(
    {
        "niche",
        "format",
        "longevity_days",
        "variation_count",
        "performance_signal",
        "hook_type",
        "hook_text",
        "problem_agitation",
        "mechanism_proof",
        "offer_cta",
    }
)


def _stable_ad_id(platform: str, row: dict[str, str]) -> str:
    """Id stabil derivat din continut — re-rularea aceluiasi CSV da acelasi id."""
    seed = "|".join(
        [platform, row.get("niche", ""), row.get("format", ""), row.get("hook_text", "")]
    )
    return f"om_{platform}_{hashlib.md5(seed.encode('utf-8')).hexdigest()[:10]}"


def _optional_int(raw: str) -> int | None:
    value = raw.strip()
    return int(value) if value else None


def _record_from_csv_row(platform: OmniPlatform, row: dict[str, str]) -> OmniSwipeRecord:
    missing = _REQUIRED_CSV_COLUMNS - set(row)
    if missing:
        raise SwipeIngestError(f"coloane lipsa in CSV: {', '.join(sorted(missing))}")
    try:
        return OmniSwipeRecord(
            ad_id=_stable_ad_id(platform, row),
            platform=platform,
            niche=row["niche"],
            format=row["format"],
            longevity_days=_optional_int(row["longevity_days"]),
            variation_count=_optional_int(row["variation_count"]),
            performance_signal=row["performance_signal"],
            hook_type=row["hook_type"],
            hook_text=row["hook_text"],
            problem_agitation=row["problem_agitation"],
            mechanism_proof=row["mechanism_proof"],
            offer_cta=row["offer_cta"],
        )
    except ValidationError as exc:
        raise SwipeIngestError(f"rand CSV invalid: {exc}") from exc
    except ValueError as exc:
        raise SwipeIngestError(f"rand CSV invalid: {exc}") from exc


def _load_csv(platform: OmniPlatform, path: Path) -> list[OmniSwipeRecord]:
    if not path.is_file():
        raise SwipeIngestError(f"fisierul CSV nu a fost gasit: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise SwipeIngestError(f"fisierul CSV este gol: {path}")
        rows = list(reader)
    if not rows:
        raise SwipeIngestError(f"fisierul CSV nu contine niciun rand: {path}")
    return [_record_from_csv_row(platform, row) for row in rows]


def run_swipe_ingest(
    csv_path: Path | str,
    platform: OmniPlatform,
    swipe_path: Path | str | None = None,
) -> list[OmniSwipeRecord]:
    """Valideaza randurile CSV si le adauga in ``omnichannel_swipe_library``.

    Scrie direct in ``swipe_file.json``, pastrand neatinse toate celelalte chei
    (``_comment``, ``frameworks``, ``tiktok_swipe_library``) — citeste JSON-ul
    brut in loc sa treaca prin modelul :class:`~ppc_agent.copywriter.models.SwipeFile`
    la scriere, ca sa nu piarda campuri nemodelate. Deduplica dupa ``ad_id``
    (derivat stabil din continut) — re-rularea aceluiasi CSV nu creeaza duplicate.

    Args:
        csv_path: CSV cu coloanele cerute (fara ``platform``/``ad_id`` — primul
            vine din argumentul ``platform``, al doilea se deriva automat).
        platform: Platforma tuturor randurilor din acest CSV.
        swipe_path: Cale catre ``swipe_file.json``; implicit radacina proiectului.

    Returns:
        Doar intrarile noi validate acum (nu toata biblioteca).

    Raises:
        SwipeIngestError: CSV-ul lipseste/e gol/are coloane lipsa sau un rand
            invalid; sau ``swipe_file.json`` lipseste / nu e JSON valid.
    """
    resolved_swipe_path = Path(swipe_path) if swipe_path is not None else default_swipe_path()
    new_records = _load_csv(platform, Path(csv_path))

    if not resolved_swipe_path.is_file():
        raise SwipeIngestError(f"swipe_file.json nu a fost gasit la {resolved_swipe_path}")
    try:
        raw = json.loads(resolved_swipe_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SwipeIngestError(f"swipe_file.json nu e JSON valid: {exc}") from exc

    existing_raw = raw.get("omnichannel_swipe_library", [])
    existing_ids = {item.get("ad_id") for item in existing_raw}
    added = [record for record in new_records if record.ad_id not in existing_ids]

    raw["omnichannel_swipe_library"] = existing_raw + [
        record.model_dump() for record in added
    ]
    resolved_swipe_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return added


def render_swipe_ingest(
    records: list[OmniSwipeRecord], swipe_path: Path, console: Console
) -> None:
    """Afiseaza un rezumat al intrarilor noi adaugate in biblioteca omnicanal.

    Textul liber vine din CSV-ul furnizat de utilizator — poate contine
    accidental ``[``/``]``, pe care Rich le-ar interpreta ca markup; foloseste
    ``markup=False`` (acelasi motiv ca in ``tiktok_ingestion.render_tiktok_ingest``).
    """
    console.print(
        f"\n[bold]Ingestie swipe omnicanal[/bold]  {len(records)} intrari noi -> {swipe_path.name}"
    )
    for record in records:
        console.print(
            f'  [{record.platform}/{record.niche}] {record.format} - '
            f'hook: "{record.hook_text[:50]}"',
            markup=False,
        )
    if not records:
        console.print("  [dim]nimic nou - toate intrarile existau deja (acelasi ad_id)[/dim]")
