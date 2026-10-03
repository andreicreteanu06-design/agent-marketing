"""Schema unificata a unei conversii, indiferent de sursa (Gomag/web/call tracking).

``StandardizedConversion`` e forma de TRANSPORT (in memorie) - contine PII in
clar (``customer_email``/``customer_phone``), asa cum a fost ceruta explicit
in schema. PII-ul NU se persista niciodata in clar: ``routers/tracking.py``
hash-uieste (SHA-256) imediat, iar randul salvat in baza de date
(``ConversionEvent`` din ``ppc_agent_server/models.py``) pastreaza doar
hash-urile - vezi :func:`hash_pii`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel

EventType = Literal["purchase", "lead", "phone_call", "contact"]


class StandardizedConversion(BaseModel):
    """O conversie normalizata, indiferent de platforma sursa.

    ``ad_id``/``ad_platform`` NU erau in lista de campuri ceruta explicit, dar
    fara ele Sectiunea 5 (leaga de motorul de decizie) e imposibil de
    implementat: nimic altceva din schema nu spune CARUI anunt ii apartine
    conversia. Optionale (``None`` = conversie neatribuita, ex. lead organic) -
    cand lipsesc, conversia tot se inregistreaza (audit/deduplicare), doar nu
    actualizeaza starea niciunui anunt. Cand ``ad_id`` e nou (nu exista inca
    un ``AdPerformanceRecord``) si ``ad_platform`` e prezent, se creeaza un rand
    nou cu status "new" - fara sincronizare reala cu platformele de reclame
    (impressions/clicks/ctr raman 0 pana la un proces separat, in afara
    scopului acestui task, semnalat explicit in pipeline.py).
    """

    event_id: str
    event_type: EventType = "purchase"
    value: float | None = None
    currency: str = "RON"
    customer_email: str | None = None
    customer_phone: str | None = None
    client_id: str
    source_platform: str
    lead_status: str | None = None
    call_duration_seconds: int | None = None

    # Adaugate fata de lista explicita din cerere - vezi docstring-ul de mai sus.
    ad_id: str | None = None
    ad_platform: Literal["meta", "tiktok", "google"] | None = None

    # Semnale de browser pentru Meta Conversions API (tracking/meta_capi.py):
    # cresc potrivirea cu utilizatorul Meta. Trimise DOAR mai departe, in aceeasi
    # cerere - nu se persista (IP-ul si user-agentul sunt date personale).
    # ``event_time``: cand a avut loc conversia (Unix, secunde); lipsa = la primire.
    event_time: int | None = None
    event_source_url: str | None = None
    client_user_agent: str | None = None
    client_ip_address: str | None = None
    fbp: str | None = None
    fbc: str | None = None

    # ID-urile de click pe care site-ul le prinde din URL la intrare (si le pastreaza
    # in cookie pana la comanda): ``gclid``/``gbraid``/``wbraid`` de la Google,
    # ``ttclid`` si cookie-ul ``_ttp`` de la TikTok, ``oppref`` de la ChatGPT. Ca
    # semnalele de mai sus: trimise mai departe, nesalvate.
    gclid: str | None = None
    gbraid: str | None = None
    wbraid: str | None = None
    ttclid: str | None = None
    ttp: str | None = None
    oppref: str | None = None
    # Consimtamantul de marketing din bannerul de cookie-uri al site-ului. ``False`` =
    # conversia nu pleaca la nicio platforma (ramane doar la noi); ``None`` = site-ul
    # nu-l transmite - pleaca fara semnal de consimtamant, ca pana acum.
    marketing_consent: bool | None = None


def _normalize_email(email: str) -> str:
    """Normalizare Meta CAPI / Google Enhanced Conversions: lowercase + trim.

    Fara normalizare, hash-ul nostru nu s-ar potrivi cu ce calculeaza Meta/
    Google pe acelasi email din alta sursa (ex. formularul lor de checkout) -
    ambele platforme cer explicit lowercase inainte de SHA-256.
    """
    return email.strip().lower()


def _normalize_phone(phone: str) -> str:
    """Normalizare telefon: E.164 fara '+' (doar cifre, cu prefixul tarii), cum cer Meta/Google.

    Gomag si call tracking-ul dau de obicei numarul national ("0712 345 678"); fara
    prefixul tarii, hash-ul nu se potriveste niciodata cu al Meta/Google. "0040..."
    si "+40..." sunt acelasi numar.

    ponytail: presupune Romania pentru numerele nationale (0 + 9 cifre); alte tari
    au nevoie de ``geo``-ul clientului aici.
    """
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        return digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return "40" + digits[1:]
    return digits


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email_google(email: str | None) -> str | None:
    """Emailul in forma ceruta de Google Enhanced Conversions.

    Ca la Meta (litere mici, fara spatii), plus: la ``gmail.com``/``googlemail.com``
    punctele din partea dinaintea ``@`` nu conteaza, deci Google le scoate inainte de hash.
    """
    if not email:
        return None
    normalized = _normalize_email(email)
    local, _, domain = normalized.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        normalized = f"{local.replace('.', '')}@{domain}"
    return _sha256(normalized) if normalized else None


def hash_phone_e164(phone: str | None) -> str | None:
    """Telefonul in E.164 *cu* ``+`` (``+40712345678``), cum il cer Google si TikTok.

    Meta si OpenAI vor aceleasi cifre fara ``+`` - hash-ul salvat la noi
    (:func:`hash_pii`) e in forma lor, deci pentru Google si TikTok se calculeaza din
    numarul in clar, cat conversia e inca in memorie.
    """
    digits = _normalize_phone(phone) if phone else ""
    return _sha256(f"+{digits}") if digits else None


def hash_pii(value: str | None, *, is_phone: bool = False) -> str | None:
    """SHA-256 (hex) al unei valori PII normalizate, sau ``None`` daca lipseste.

    Args:
        value: Email-ul sau telefonul in clar, sau ``None``.
        is_phone: ``True`` pentru normalizare de telefon (doar cifre), altfel
            normalizare de email (lowercase + trim).

    Returns:
        Hash-ul hex, sau ``None`` daca ``value`` e ``None``/gol.
    """
    if not value:
        return None
    normalized = _normalize_phone(value) if is_phone else _normalize_email(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
