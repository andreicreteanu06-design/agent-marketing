"""Orchestrare CLI pentru modulul de copywriting si scrierea in coada HITL."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from ppc_agent.copywriter.engine import AdCopyGenerator
from ppc_agent.copywriter.models import AdCopy, AdQueue, QueuedAd, char_count
from ppc_agent.copywriter.swipe import load_swipe_file, retrieve_framework

QUEUE_FILENAME = "proposed_ads_queue.json"


def append_to_queue(
    entry: QueuedAd, directory: Path | str = "."
) -> Path:
    """Adauga o intrare in ``proposed_ads_queue.json`` (creeaza fisierul daca lipseste).

    Coada este bariera human-in-the-loop: nimic nu se publica online, utilizatorul
    citeste acest fisier si aproba manual.

    Args:
        entry: Intrarea de adaugat.
        directory: Directorul fisierului de coada.

    Returns:
        Calea fisierului de coada.
    """
    path = Path(directory) / QUEUE_FILENAME
    queue = AdQueue()
    if path.is_file():
        queue = AdQueue.model_validate_json(path.read_text(encoding="utf-8"))
    queue.queue.append(entry)
    path.write_text(queue.model_dump_json(indent=2), encoding="utf-8")
    return path


def run_copy(
    generator: AdCopyGenerator,
    *,
    product_usp: str,
    target_keyword: str,
    emotion_trigger: str,
    swipe_path: Path | str | None = None,
) -> QueuedAd:
    """Genereaza copy si construieste intrarea pentru coada (fara sa o scrie).

    Args:
        generator: Generatorul configurat cu un client.
        product_usp: Propunerea unica de valoare.
        target_keyword: Cuvantul cheie exact-match.
        emotion_trigger: Declansatorul emotional.
        swipe_path: Cale swipe file, pentru a citi numele/stilul framework-ului.

    Returns:
        Intrarea de coada, cu status ``pending_review``.
    """
    ad_dict = generator.generate_emotional_copy(
        product_usp, target_keyword, emotion_trigger
    )
    swipe = load_swipe_file(swipe_path)
    framework = retrieve_framework(swipe, emotion_trigger)
    return QueuedAd(
        created_at=datetime.now(tz=UTC),
        target_keyword=target_keyword,
        emotion_trigger=emotion_trigger,
        framework_name=framework.name,
        framework_style=framework.style,
        product_usp=product_usp,
        ad=AdCopy.model_validate(ad_dict),
    )


def render_copy(entry: QueuedAd, console: Console) -> None:
    """Afiseaza copy-ul generat in consola, cu lungimile de caractere."""
    ad = entry.ad
    console.print(
        f"\n[bold]Copy generat[/bold]  keyword='{entry.target_keyword}'  "
        f"trigger='{entry.emotion_trigger}'  framework={entry.framework_style}"
    )
    console.print(f"  H1 ({char_count(ad.headline_1):>2}/30)  {ad.headline_1}")
    console.print(f"  H2 ({char_count(ad.headline_2):>2}/30)  {ad.headline_2}")
    console.print(f"  D  ({char_count(ad.description):>2}/90)  {ad.description}")
