"""Semnalele de afacere locala: telefon, program, cod postal (NAP).

NAP = Name, Address, Phone. Pentru o afacere locala, aceleasi date trebuie sa
apara identic pe site, in Google Business Profile si pe platformele unde e
listata (Wolt, Glovo, Tazz, Booking, directoare). Cand difera, motoarele de
cautare si cele generative nu mai stiu care e corect, iar clientul suna la un
numar vechi. Cazul real care a dus la modulul asta: un restaurant cu programul,
telefonul si codul postal diferite intre site, Google si platforma de livrare.

Doua lucruri separate, ambele functii pure peste ``CrawledPage``:

- detectia unei pagini de locatie (telefon + interval orar vizibil), folosita de
  verificarea GEO ``missing-local-business-schema`` din ``geo_reporters.py``;
- comparatia cu listari externe date explicit de om (:class:`ReferenceListing`).
  Auditul NU cauta singur listarile externe: ar insemna sa ghiceasca ce fisa
  Google sau ce pagina Wolt e a clientului. Fara referinte, nu se compara nimic
  si nu se raporteaza nimic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from seo_geo_agent.audit.page_reporters import DetectedIssue
from seo_geo_agent.audit.types import CrawledPage

#: Un numar de telefon scris de om: cifre cu spatii, puncte, cratime sau
#: paranteze intre ele, optional cu prefix international. Validarea reala se
#: face dupa normalizare (lungimea in cifre), nu din expresie.
_PHONE_CANDIDATE_RE = re.compile(r"(?:\+|\b00)?\(?\d[\d\s().\-]{7,17}\d")
_MIN_PHONE_DIGITS = 9
_MAX_PHONE_DIGITS = 15

#: Un interval orar: 10:30 - 22:00, 9.00-18.00, 11:00 pana la 21:30.
_HOURS_RANGE_RE = re.compile(
    r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\s*"
    # cratima, en dash, em dash, "pana la" cu si fara diacritice, "to"
    "(?:-|\u2013|\u2014|pana la|p\u00e2n\u0103 la|to)"
    r"\s*([01]?\d|2[0-4])[:.]([0-5]\d)\b",
    re.I,
)
#: Coduri postale din 6 cifre (Romania). Folosite doar ca sa verificam daca un
#: cod DAT de o referinta apare in pagina, nu ca sa descoperim coduri.
_POSTAL_CODE_RE = re.compile(r"\b\d{6}\b")


def normalize_phone(raw: str) -> str | None:
    """Forma comparabila a unui numar: doar cifre, prefixul romanesc unificat.

    ``0773 957 224``, ``+40 773 957 224``, ``0040773957224`` si ``(0773) 957-224``
    dau toate ``0773957224``. Numerele straine raman in forma internationala
    (fara ``00``/``+``). Sub 9 sau peste 15 cifre nu e un telefon.
    """
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("40") and len(digits) == 11:
        digits = "0" + digits[2:]
    if not _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
        return None
    return digits


def phones_in_text(text: str) -> set[str]:
    """Numerele de telefon recunoscute intr-un text, normalizate."""
    found: set[str] = set()
    for match in _PHONE_CANDIDATE_RE.finditer(text):
        candidate = match.group(0)
        # Un interval orar sau o data nu e telefon, chiar daca are destule cifre.
        if ":" in candidate:
            continue
        phone = normalize_phone(candidate)
        if phone is not None:
            found.add(phone)
    return found


def page_phones(page: CrawledPage) -> set[str]:
    """Toate telefoanele paginii: linkuri ``tel:``, text vizibil, JSON-LD."""
    phones = {phone for raw in page.phone_links if (phone := normalize_phone(raw))}
    phones |= phones_in_text(page.body_text)
    phones |= {phone for raw in page.structured_data.telephones if (phone := normalize_phone(raw))}
    return phones


def normalize_hours_range(raw: str) -> str | None:
    """``"10.30 - 22:00"`` -> ``"10:30-22:00"``; ``None`` daca nu e un interval."""
    match = _HOURS_RANGE_RE.search(raw)
    if match is None:
        return None
    start_h, start_m, end_h, end_m = match.groups()
    return f"{int(start_h):02d}:{start_m}-{int(end_h):02d}:{end_m}"


def hours_ranges_in_text(text: str) -> set[str]:
    """Intervalele orare din text, normalizate (``HH:MM-HH:MM``)."""
    return {
        f"{int(m.group(1)):02d}:{m.group(2)}-{int(m.group(3)):02d}:{m.group(4)}"
        for m in _HOURS_RANGE_RE.finditer(text)
    }


def is_location_page(page: CrawledPage) -> bool:
    """O pagina care prezinta un loc fizic: are telefon SI program.

    Ambele semnale, nu unul: aproape orice site are telefonul in subsol, deci
    telefonul singur ar transforma fiecare pagina intr-o "pagina de locatie".
    Programul (un interval orar) e ce o deosebeste.
    """
    if not page.is_html or page.fetch_class != "ok" or not 200 <= page.status_code < 300:
        return False
    has_hours = page.structured_data.has_opening_hours or bool(hours_ranges_in_text(page.body_text))
    return has_hours and bool(page_phones(page))


@dataclass(frozen=True, slots=True)
class ReferenceListing:
    """O listare externa a aceleiasi afaceri, data explicit de om.

    Attributes:
        source: De unde vin datele ("Google Business Profile", "Wolt"...), apare
            in raport ca omul sa stie ce sa corecteze.
        phone: Telefonul din listare, in orice forma (se normalizeaza).
        postal_code: Codul postal din listare.
        hours: Intervalele orare din listare (``"10:30-22:00"``, orice forma).
        page_url: Pagina de pe site care descrie aceeasi locatie. Gol => se cauta
            pagina care afiseaza telefonul listarii.
    """

    source: str
    phone: str | None = None
    postal_code: str | None = None
    hours: tuple[str, ...] = field(default_factory=tuple)
    page_url: str | None = None


def _match_page(pages: list[CrawledPage], reference: ReferenceListing) -> CrawledPage | None:
    ok_pages = [page for page in pages if page.is_html and page.fetch_class == "ok"]
    if reference.page_url:
        wanted = reference.page_url.rstrip("/").lower()
        return next((p for p in ok_pages if p.url.rstrip("/").lower() == wanted), None)
    phone = normalize_phone(reference.phone) if reference.phone else None
    if phone is None:
        return None
    with_phone = [page for page in ok_pages if phone in page_phones(page)]
    # Pagina de locatie bate pagina care are telefonul doar in subsol.
    return next(
        (p for p in with_phone if is_location_page(p)), with_phone[0] if with_phone else None
    )


def find_nap_mismatches(
    pages: list[CrawledPage], references: list[ReferenceListing], *, site_url: str
) -> list[DetectedIssue]:
    """Diferentele dintre site si listarile externe date de om.

    Pentru fiecare listare se gaseste pagina locatiei (dupa ``page_url`` sau
    dupa telefon) si se compara telefonul, codul postal si programul. Fiecare
    diferenta e o problema ``nap-mismatch`` separata, cu ambele valori in
    detalii - raportul spune exact ce difera si unde.
    """
    issues: list[DetectedIssue] = []

    def report(
        page_url: str, reference: ReferenceListing, field_name: str, **details: object
    ) -> None:
        issues.append(
            DetectedIssue(
                issue_type="nap-mismatch",
                page_url=page_url,
                details={"source": reference.source, "field": field_name, **details},
                dedupe_key=f"{reference.source}:{field_name}",
            )
        )

    for reference in references:
        page = _match_page(pages, reference)
        if page is None:
            report(
                reference.page_url or site_url,
                reference,
                "page",
                source_value=reference.page_url or reference.phone,
                site_value=None,
                note="Nicio pagina crawlata nu corespunde listarii (URL sau telefon).",
            )
            continue

        site_phones = page_phones(page)
        if reference.phone:
            wanted_phone = normalize_phone(reference.phone)
            if wanted_phone is not None and wanted_phone not in site_phones:
                report(
                    page.url,
                    reference,
                    "phone",
                    source_value=reference.phone,
                    site_value=sorted(site_phones) or None,
                )

        if reference.postal_code:
            wanted_code = reference.postal_code.strip()
            declared = set(page.structured_data.postal_codes)
            visible = set(_POSTAL_CODE_RE.findall(page.body_text))
            if wanted_code not in declared | visible:
                report(
                    page.url,
                    reference,
                    "postal_code",
                    source_value=wanted_code,
                    site_value=sorted(declared | visible) or None,
                )

        wanted_hours = {h for raw in reference.hours if (h := normalize_hours_range(raw))}
        site_hours = hours_ranges_in_text(page.body_text)
        if wanted_hours and site_hours and not wanted_hours <= site_hours:
            report(
                page.url,
                reference,
                "hours",
                source_value=sorted(wanted_hours),
                site_value=sorted(site_hours),
            )

    return issues
