"""Agentul Regina (CMO): simuleaza clientul ideal si dicteaza unghiul de marketing.

Al treilea agent, deasupra celor de SEO/GEO si PPC. NU executa nimic: citeste ce
au adunat ceilalti doi (cu ce cuvinte cauta oamenii, ce reclame ruleaza si cum
performeaza), construieste "clientul ideal" si intoarce o directiva
(:class:`BrandStrategyDirective`). Ce se face cu ea decide PPC-ul - vezi
``ppc_agent_server/jobs/brand_alignment.py``. Regina sfatuieste, Muschiul executa.

De unde vine modelul - MiroFish (github.com/666ghj/MiroFish)
------------------------------------------------------------
MiroFish e un motor de "inteligenta de roi": din materiale-sursa construieste o
ontologie de tipuri de entitati, genereaza pentru fiecare entitate un profil de
persona (biografie, personalitate/MBTI, interese si mai ales ce il misca si ce
il enerveaza), apoi da fiecarui agent o configuratie de comportament - o
pozitie fata de subiect (``supportive`` / ``opposing`` / ``neutral`` /
``observer``), o inclinatie emotionala si o pondere de influenta - si ii lasa
sa reactioneze la continut.

Codul MiroFish e sub AGPL-3.0: copiat aici, ar obliga publicarea intregului
produs sub aceeasi licenta. De aceea NU contine niciun rand din el - doar
ACELASI MODEL, reimplementat independent si adaptat la reclame:

=====================================  =========================================
MiroFish                                Aici
=====================================  =========================================
material-sursa (seed)                   :class:`BrandSignals`: cautari organice
                                        (Search Console), termeni platiti cu
                                        conversii (Google Ads), reclamele live
ontologie de tipuri de entitati         :data:`ARCHETYPES`: 5 motivatii de
                                        cumparare, cu markerii din cautari
profil de persona (bio, MBTI, ce il     :class:`PersonaArchetype`: dureri,
misca / ce il enerveaza)                dorinte, obiectii, stil de decizie
``influence_weight``                    ponderea profilului: cererea (afisari) si
                                        cumparatorii (conversii) pe care ii aduce
``stance`` fata de un continut          :class:`PersonaReaction`: fiecare profil
                                        "citeste" fiecare reclama si o sustine,
                                        o ignora (observer) sau o respinge
simularea pe runde + raportul           valoarea asteptata a reactiei populatiei
                                        (determinista) + directiva
=====================================  =========================================

Doua abateri deliberate de la MiroFish:

- **Fara aleator.** MiroFish trage la sorti varsta si genul cand nu le stie. Aici
  aceleasi date dau mereu aceeasi directiva, iar demografia NU se inventeaza:
  din cautari nu se poate deduce varsta sau genul cuiva (vezi ``notes``).
- **Fara LLM in decizie.** Profilurile sunt o ontologie explicita, verificabila
  rand cu rand - un om care aproba o rescriere trebuie sa poata vedea DE CE.
  Un LLM apare doar DUPA decizie, ca "voce": explica directiva clientului
  (:meth:`BrandStrategist.generate_cmo_message`), fara sa o poata schimba.

Peste profiluri sta stratul de neuromarketing (``cognitive.py``): cum decide
publicul (Kahneman, Sistemul 1/2), unde se rupe conversia (frictiune, incredere,
valoare perceputa) si pe ce ruta se convinge (ELM) - in
:attr:`BrandStrategyDirective.cognitive_profile` si, per reclama, in
:attr:`AdAlignment.cognitive_note`. Tot determinist.

Modulul e pur: fara DB, fara HTTP. Datele vin printr-un :class:`BrandSignalsSource`
(implementarea din baza de date: ``queen_signals.py``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel

from ppc_agent.texttools import tokenize
from ppc_agent_server.services.cognitive import (
    AdDemand,
    CognitiveProfile,
    DecisionMode,
    ad_demand,
    ad_fit_note,
    cognitive_profile,
)
from ppc_agent_server.services.humanizer import CONSULTANT_VOICE, ai_tells
from ppc_agent_server.services.ro_format import count as _count
from ppc_agent_server.services.ro_format import percent as _percent
from ppc_agent_server.services.ro_format import ron as _ron

logger = logging.getLogger("ppc_agent_server.services.queen_agent")

ArchetypeKey =Literal["price", "urgency", "trust", "convenience", "research"]
#: Pozitia unui profil fata de o reclama - aceleasi patru valori ca in MiroFish.
Stance = Literal["supportive", "neutral", "observer", "opposing"]
SearchOrigin = Literal["organic", "paid"]
DirectiveStatus = Literal["ok", "insufficient_data"]
AdjustmentKind = Literal["delivery", "interest", "audience", "exclusion"]

#: Sub atatea cautari atribuite un profil ar fi o anecdota, nu un client.
MIN_ATTRIBUTED_QUERIES = 3
#: ...si sub atatea afisari atribuite (cand nici conversii nu sunt destule).
MIN_ATTRIBUTED_DEMAND = 200
#: De la atatea conversii, cine CUMPARA cantareste cat cine cauta.
MIN_CONVERSIONS = 5
#: Un profil e "dominant" peste aceasta cota. Doar atunci Regina forteaza
#: rescrieri - intr-o cerere impartita egal, a rescrie totul pentru un singur
#: profil ar pierde restul.
DOMINANT_SHARE = 0.35
#: Doua semnale din ce cauta profilul = rezonanta deplina.
HOOKS_FOR_FULL_RESONANCE = 2
#: De la aceasta densitate (acronime, coduri, termeni tehnici) textul e "tehnic".
TECHNICAL_DENSITY = 0.15
#: Click-uri platite fara nicio conversie de la care un profil merita exclus.
MIN_PAID_CLICKS_FOR_EXCLUSION = 20
#: Meta cere cel putin 100 de oameni in audienta-sursa a unui lookalike.
MIN_CONVERSIONS_FOR_LOOKALIKE = 100
MAX_SAMPLE_QUERIES = 3


# --- semnalele (materialul-sursa) -------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchSignal:
    """O cautare: organica (Search Console) sau termen platit (Google Ads)."""

    query: str
    origin: SearchOrigin
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0

    @property
    def demand(self) -> int:
        # Afisarile sunt cererea. Cand sursa nu le are (termen platit fara
        # coloana), click-urile sunt singura urma - mai putin, dar nu zero.
        return self.impressions or self.clicks


@dataclass(frozen=True, slots=True)
class LiveAd:
    """O reclama care ruleaza, cu textul ei si - daca se stie - performanta."""

    #: Resursa pe care o va purta propunerea de rescriere (ex. ``meta_ad/123``).
    ref: str
    platform: str
    headline: str
    body: str
    spend: Decimal | None = None
    conversions: int | None = None
    target_cpa: Decimal | None = None

    @property
    def text(self) -> str:
        return f"{self.headline} {self.body}".strip()

    @property
    def cpa(self) -> Decimal | None:
        if self.spend is None or not self.conversions:
            return None
        return (self.spend / self.conversions).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class BrandSignals:
    """Tot ce stie Regina despre un client, adunat de la ceilalti agenti."""

    brand: str
    searches: Sequence[SearchSignal]
    ads: Sequence[LiveAd]
    #: Ce lipseste si de ce (ex. Search Console neconectat) - ajunge in directiva.
    notes: Sequence[str] = ()


class BrandSignalsSource(Protocol):
    def load(self, client_account_id: int) -> BrandSignals: ...


# --- ontologia: profilurile de cumparator ------------------------------------


@dataclass(frozen=True, slots=True)
class PersonaArchetype:
    """Un tip de client, definit de motivatia lui de cumparare.

    Markerii, carligele si respingatorii se potrivesc pe jetoane normalizate
    (``texttools.tokenize``: fara diacritice, fara majuscule), deci se scriu
    corect, cu diacritice - asa ajung si in textele citite de oameni.
    """

    key: ArchetypeKey
    name: str
    #: Despre ce vorbeste o reclama care i se adreseaza.
    voice: str
    #: Cuvintele din CAUTARI care arata motivatia.
    query_markers: tuple[str, ...]
    #: Cuvintele din RECLAMA care il atrag.
    hooks: tuple[str, ...]
    #: Cuvintele din reclama care il resping.
    repellers: tuple[str, ...]
    pains: tuple[str, ...]
    desires: tuple[str, ...]
    objections: tuple[str, ...]
    decision_style: str
    #: Declansatorul in vocabularul copywriterului PPC (``copywriter/swipe.py``).
    emotion_trigger: str
    tone: str
    proof_points: tuple[str, ...]
    #: Fraze-exemplu pentru rescriere (titluri si formulari care il prind).
    copy_examples: tuple[str, ...]
    #: Cum se difuzeaza pe Meta pentru acest profil.
    delivery: str
    #: Acelasi lucru ca sintagma nominala, ca sa intre intr-o fraza («Consiliul susține ...»).
    delivery_idea: str
    #: Tipul de interese Meta de exclus cand profilul consuma bani fara sa converteasca,
    #: fara substantiv («de tip ...»): intra si in «Exclude interesele ...», si in
    #: «excluderea intereselor ...».
    exclusion_theme: str | None
    #: Jargonul tehnic il indeparteaza.
    rejects_jargon: bool


ARCHETYPES: tuple[PersonaArchetype, ...] = (
    PersonaArchetype(
        key="price",
        name="Vânătorul de preț",
        voice="preț clar și ofertă",
        query_markers=(
            "preț", "prețuri", "cât costă", "costă", "cost", "costuri", "tarif", "tarife",
            "ieftin", "ieftină", "ieftine", "ofertă", "oferte", "reducere", "reduceri",
            "promoție", "discount",
        ),
        hooks=(
            "preț", "prețuri", "de la", "lei", "ron", "ofertă", "reducere", "discount",
            "promoție", "gratuit", "fără costuri ascunse", "preț fix", "transparent",
        ),
        repellers=("premium", "exclusiv", "lux"),
        pains=(
            "se teme că factura finală va fi mult peste ce i s-a spus",
            "nu poate compara prețuri fără să sune la fiecare firmă",
        ),
        desires=(
            "un preț clar înainte să se angajeze",
            "sentimentul că a făcut o alegere bună pentru bani",
        ),
        objections=(
            "prețuri ascunse sau «de la» fără plafon",
            "să trebuiască să sune ca să afle cât costă",
        ),
        decision_style="comparator: deschide 3-4 variante și alege după preț și claritate",
        emotion_trigger="beneficiu",
        tone="direct, cu cifre: prețul sau intervalul în titlu, fără superlative",
        proof_points=("prețul sau intervalul de preț", "ce e inclus în preț"),
        copy_examples=(
            "Preț fix, spus dinainte",
            "Știi costul înainte să începem",
            "Fără costuri ascunse",
        ),
        delivery=(
            "Buton «Vezi prețurile» / formular de ofertă; testează reclame cu prețul în imagine."
        ),
        delivery_idea=(
            "butonul «Vezi prețurile» (sau un formular de ofertă) și reclame cu prețul în imagine"
        ),
        exclusion_theme="de tip «cupoane», «reduceri», «vânători de oferte»",
        rejects_jargon=False,
    ),
    PersonaArchetype(
        key="urgency",
        name="Omul cu problema acum",
        voice="rezolvare azi, fără așteptare",
        query_markers=(
            "urgent", "urgență", "non stop", "nonstop", "24/24", "24/7", "azi", "acum",
            "rapid", "repede", "imediat", "tractare", "nu pornește", "defect", "defectă",
            "blocat", "blocată", "avarie", "avariat",
        ),
        hooks=(
            "azi", "astăzi", "acum", "rapid", "imediat", "urgent", "urgență", "non-stop",
            "nonstop", "24/7", "în aceeași zi", "fără așteptare", "sunați", "sună acum",
        ),
        repellers=("săptămâna viitoare", "doar cu programare"),
        pains=(
            "problema îl blochează chiar acum",
            "nu știe cât timp rămâne fără soluție",
        ),
        desires=(
            "cineva care preia problema azi",
            "să afle imediat cât durează",
        ),
        objections=(
            "programări peste o săptămână",
            "formulare lungi înainte de orice răspuns",
            "detalii tehnice când el vrea doar să știe «când e gata»",
        ),
        decision_style="decide pe loc, sub stres: alege primul care promite credibil «azi»",
        emotion_trigger="urgenta",
        tone="calm și ferm, orientat pe acțiune: «Te preluăm azi»",
        proof_points=("disponibilitatea de azi / timpul de răspuns", "telefonul, vizibil"),
        copy_examples=("Te preluăm azi", "Sună acum, răspundem imediat", "Rezolvat în aceeași zi"),
        delivery=(
            "Rază geografică mică în jurul locației și butonul «Sună acum» - cine are "
            "o problemă acută nu traversează orașul."
        ),
        delivery_idea="o rază geografică mică în jurul locației și butonul «Sună acum»",
        exclusion_theme=None,
        rejects_jargon=True,
    ),
    PersonaArchetype(
        key="trust",
        name="Scepticul care vrea garanții",
        voice="siguranță, garanții și dovezi",
        query_markers=(
            "garanție", "garanții", "recenzii", "păreri", "review", "autorizat", "autorizată",
            "certificat", "certificată", "de încredere", "original", "originale", "bun",
            "bună", "cel mai bun", "recomandări", "profesionist", "serios", "specializat",
        ),
        hooks=(
            "garanție", "garantat", "garantată", "experiență", "ani de experiență",
            "recenzii", "clienți mulțumiți", "certificat", "autorizat", "original",
            "originale", "specializat", "verificat", "de încredere",
        ),
        repellers=("cel mai ieftin", "ieftin"),
        pains=(
            "a mai fost păcălit cu lucrări inutile sau nefăcute",
            "nu poate verifica singur dacă treaba s-a făcut corect",
        ),
        desires=(
            "garanție scrisă pe ce plătește",
            "dovezi că alții au fost mulțumiți",
        ),
        objections=(
            "promisiuni fără dovezi",
            "prețuri suspect de mici",
            "lipsa garanției",
        ),
        decision_style="prudent: citește recenzii, compară garanții, decide încet dar rămâne fidel",
        emotion_trigger="risc",
        tone="sobru și sigur pe el: dovezi, garanții, cifre verificabile",
        proof_points=("garanția (durată, ce acoperă)", "recenziile sau anii de experiență"),
        copy_examples=(
            "Garanție scrisă pe lucrare",
            "Verificat de clienții noștri",
            "Fără surprize",
        ),
        delivery="Reclame cu recenzii reale (carusel de testimoniale) și butonul «Află mai multe».",
        delivery_idea=(
            "reclame cu recenzii reale (carusel de testimoniale) și butonul «Află mai multe»"
        ),
        exclusion_theme=None,
        rejects_jargon=False,
    ),
    PersonaArchetype(
        key="convenience",
        name="Ocupatul pragmatic",
        voice="timp salvat și zero bătăi de cap",
        query_markers=(
            "programare", "programări", "online", "lângă mine", "aproape", "în apropiere",
            "deschis", "program", "orar", "weekend", "sâmbătă", "duminică", "la domiciliu",
            "ridicare", "fără programare",
        ),
        hooks=(
            "programare online", "programează", "programează-te", "fără cozi",
            "fără așteptare", "ridicăm", "la domiciliu", "aproape", "în weekend", "sâmbătă",
            "gata în", "economisești timp", "simplu", "fără bătăi de cap", "ne ocupăm noi",
            "rapid",
        ),
        repellers=("sunați în timpul programului",),
        pains=(
            "nu are timp să stea la coadă sau să piardă o zi",
            "programul firmelor se suprapune cu al lui",
        ),
        desires=(
            "să rezolve totul din telefon, în două minute",
            "să știe exact când e gata",
        ),
        objections=(
            "să trebuiască să sune în timpul programului",
            "detalii tehnice care nu îl ajută să decidă",
            "nesiguranța despre cât durează",
        ),
        decision_style="pragmatic: alege varianta cu cel mai puțin efort, dacă pare de încredere",
        emotion_trigger="economie de timp",
        tone="simplu și liniștitor: «ne ocupăm noi», fără jargon",
        proof_points=("programarea online și durata", "ora la care e gata"),
        copy_examples=(
            "Programare online în 2 minute",
            "Ne ocupăm noi de tot",
            "Știi dinainte când e gata",
        ),
        delivery=(
            "Butonul «Programează-te» (formular instant) și difuzare pe serile din "
            "timpul săptămânii și în weekend, când își planifică treburile."
        ),
        delivery_idea=(
            "butonul «Programează-te» (formular instant) și difuzarea în serile din timpul "
            "săptămânii și în weekend"
        ),
        exclusion_theme=None,
        rejects_jargon=True,
    ),
    PersonaArchetype(
        key="research",
        name="Cercetătorul",
        voice="explicații și detalii tehnice",
        query_markers=(
            "semne", "simptome", "cauze", "cauza", "diferența", "vs", "tutorial", "singur",
            "ghid", "sfaturi", "merită", "cât de des", "la câți",
        ),
        hooks=(
            "află", "explicăm", "îți explicăm", "ghid", "diagnoză", "diagnosticare",
            "verificare", "consultanță", "de ce", "cum",
        ),
        repellers=(),
        pains=(
            "nu înțelege ce are și se teme să nu fie tras pe sfoară",
            "găsește informații contradictorii",
        ),
        desires=(
            "să înțeleagă problema înainte să plătească",
            "un specialist care explică pe limba lui",
        ),
        objections=(
            "reclame agresive de vânzare",
            "presiunea de a decide pe loc",
        ),
        decision_style=(
            "informațional: nu cumpără azi, dar alege mai târziu pe cine l-a învățat ceva"
        ),
        emotion_trigger="curiozitate",
        tone="educativ și răbdător: explică înainte să vândă",
        proof_points=("răspunsul la întrebarea lui", "o diagnoză sau o consultanță clară"),
        copy_examples=("Află ce are, înainte să plătești", "Îți explicăm pe înțelesul tău"),
        delivery=(
            "Retargeting pe cei care au citit articolele informative - au învățat de la "
            "tine, acum pot cumpăra."
        ),
        delivery_idea="retargeting pe cei care au citit articolele informative",
        exclusion_theme="de tip «Do it yourself» / tutoriale",
        rejects_jargon=False,
    ),
)

_BY_KEY: dict[ArchetypeKey, PersonaArchetype] = {a.key: a for a in ARCHETYPES}
_ORDER: dict[ArchetypeKey, int] = {a.key: i for i, a in enumerate(ARCHETYPES)}

Phrase = tuple[str, ...]


def _phrases(values: Sequence[str]) -> tuple[tuple[str, Phrase], ...]:
    return tuple((value, tuple(tokenize(value))) for value in values)


_MARKERS = {a.key: _phrases(a.query_markers) for a in ARCHETYPES}
_HOOKS = {a.key: _phrases(a.hooks) for a in ARCHETYPES}
_REPELLERS = {a.key: _phrases(a.repellers) for a in ARCHETYPES}

#: O intrebare deschisa ("cum...", "cand...") e o cautare de informare. "Cat"
#: lipseste deliberat: "cat costa" e pret, nu curiozitate.
_QUESTION_START = frozenset({"cum", "ce", "cand", "unde", "care", "cine", "de"})


def _contains(tokens: Sequence[str], phrase: Phrase) -> bool:
    size = len(phrase)
    if not size or size > len(tokens):
        return False
    return any(tuple(tokens[i : i + size]) == phrase for i in range(len(tokens) - size + 1))


def classify_query(query: str, brand: str = "") -> tuple[ArchetypeKey, ...]:
    """Profilurile carora le apartine o cautare (zero, unul sau mai multe).

    Cautarile cu numele brandului nu se atribuie nimanui: omul te cunoaste deja,
    motivatia lui nu spune nimic despre cum sa-i vorbesti unui client nou.
    """
    tokens = tokenize(query)
    brand_tokens = tuple(tokenize(brand))
    if not tokens or (brand_tokens and _contains(tokens, brand_tokens)):
        return ()
    matched = [
        archetype.key
        for archetype in ARCHETYPES
        if any(_contains(tokens, phrase) for _, phrase in _MARKERS[archetype.key])
    ]
    is_question = tokens[0] in _QUESTION_START and not (
        tokens[0] == "de" and tokens[1:2] != ["ce"]
    )
    if is_question and "research" not in matched and "price" not in matched:
        matched.append("research")
    return tuple(matched)


# --- densitatea tehnica a unui text ------------------------------------------

_ACRONYM = re.compile(r"\b[A-Z]{2,5}\b")
_CODE = re.compile(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{3,}\b")
#: Majusculele de accent din reclame, care NU sunt acronime tehnice.
_CAPS_EMPHASIS = frozenset({"NOU", "ACUM", "AZI", "TOP", "RON", "LEI", "SRL", "OK", "NON", "STOP"})
_TECH_WORDS = frozenset(
    {
        "procedura", "specificatii", "specificatie", "tehnologie", "parametri", "aparat",
        "aparatura", "computerizat", "computerizata", "sistem", "dinamic", "dinamica",
        "vascozitate", "tehnic", "tehnica", "tehnice", "calibrare", "tolerante",
    }
)


def technical_density(text: str) -> float:
    """Cat din text e jargon: acronime (ATF, OEM), coduri (5W30) si termeni tehnici."""
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    acronyms = [m for m in _ACRONYM.findall(text) if m not in _CAPS_EMPHASIS]
    codes = _CODE.findall(text)
    words = [token for token in tokens if token in _TECH_WORDS]
    return (len(acronyms) + len(codes) + len(words)) / len(tokens)


# --- directiva (iesirea) -----------------------------------------------------


class AvatarSegment(BaseModel):
    """Un profil si ponderea lui in ce aduce clientul."""

    key: ArchetypeKey
    name: str
    #: Ponderea finala (``influence_weight`` in MiroFish), 0-1.
    share: float
    demand_share: float
    #: Cota din conversii; ``None`` cand nu sunt destule ca sa conteze.
    buyer_share: float | None
    paid_clicks: int
    conversions: float
    sample_queries: list[str]


class AvatarProfile(BaseModel):
    """Clientul ideal, structurat (naratiunea e in ``ideal_avatar_profile``)."""

    key: ArchetypeKey
    name: str
    share: float
    dominant: bool
    pains: list[str]
    desires: list[str]
    objections: list[str]
    decision_style: str
    sample_queries: list[str]


class PersonaReaction(BaseModel):
    """Cum reactioneaza un profil la o reclama."""

    key: ArchetypeKey
    stance: Stance
    resonance: float
    hooks_found: list[str]
    repellers_found: list[str]


class AdAlignment(BaseModel):
    """Verdictul pentru o reclama: vorbeste sau nu clientului ideal."""

    ref: str
    platform: str
    headline: str
    text: str
    #: Reactia asteptata a intregii populatii de profiluri, 0-1.
    alignment_score: float
    avatar_stance: Stance
    #: Profilul caruia ii vorbeste de fapt reclama (cea mai mare rezonanta).
    speaks_to: ArchetypeKey | None
    technical: bool
    cpa: Decimal | None
    target_cpa: Decimal | None
    #: Adevarat = Regina cere rescrierea, oricat de bine ar arata CPA-ul.
    deviates: bool
    reason: str
    reactions: list[PersonaReaction]
    #: Ce sistem de decizie ii cere reclama cititorului (Kahneman).
    cognitive_demand: AdDemand
    #: Nepotrivirea cu felul in care decide publicul, explicata; ``None`` = se potriveste.
    cognitive_note: str | None


class TargetingAdjustment(BaseModel):
    """O sugestie de targetare pentru Meta Ads, cu motivul ei din date."""

    platform: Literal["meta"] = "meta"
    kind: AdjustmentKind
    #: Ce e de facut, la imperativ («Caută ...», «Exclude ...»): pentru agentie.
    suggestion: str
    #: Aceeasi sugestie ca sintagma nominala («un test de interese ...»), ca sa intre
    #: intr-o fraza a consiliului: «Consiliul susține ...», «CFO-ul a tăiat ...».
    idea: str
    reason: str


class CopywritingAngle(BaseModel):
    """Unghiul de copy - in vocabularul copywriterului PPC."""

    #: Fraza pentru om: "Schimbă textele din ... în ...".
    summary: str
    #: Declansatorul pentru ``AdCopyGenerator.generate_emotional_copy``.
    emotion_trigger: str
    tone: str
    hooks: list[str]
    must_include: list[str]
    avoid: list[str]


class DataBasis(BaseModel):
    """Pe ce s-a sprijinit directiva - ca omul sa poata judeca increderea."""

    queries_total: int
    queries_attributed: int
    organic_queries: int
    paid_terms: int
    attributed_demand: int
    conversions: float
    ads_evaluated: int
    ads_with_performance: int


class BrandStrategyDirective(BaseModel):
    """Directiva Reginei pentru un client: cine e clientul ideal si cum i se vorbeste."""

    version: Literal["1.1"] = "1.1"
    client_account_id: int
    generated_at: datetime
    status: DirectiveStatus
    #: Descrierea narativa a clientului ideal.
    ideal_avatar_profile: str
    avatar: AvatarProfile | None
    segments: list[AvatarSegment]
    #: Sugestii de interese si excluderi pentru Meta Ads.
    targeting_adjustments: list[TargetingAdjustment]
    #: Tonul vocii si unghiul recomandat.
    copywriting_angle: CopywritingAngle | None
    ad_alignment: list[AdAlignment]
    #: Psihologia cumparatorului: modul de decizie, bariera, ruta de persuasiune.
    #: ``None`` cand nu exista client ideal (date insuficiente).
    cognitive_profile: CognitiveProfile | None
    data_basis: DataBasis
    notes: list[str]

    @property
    def misaligned_ads(self) -> list[AdAlignment]:
        return [ad for ad in self.ad_alignment if ad.deviates]


# --- atribuirea cererii pe profiluri -----------------------------------------


@dataclass(slots=True)
class _Tally:
    demand: float = 0.0
    paid_clicks: float = 0.0
    conversions: float = 0.0
    queries: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class _Attribution:
    tallies: dict[ArchetypeKey, _Tally]
    queries_attributed: int
    attributed_demand: float
    conversions: float

    def is_sufficient(self) -> bool:
        return self.queries_attributed >= MIN_ATTRIBUTED_QUERIES and (
            self.attributed_demand >= MIN_ATTRIBUTED_DEMAND or self.conversions >= MIN_CONVERSIONS
        )


def _attribute(signals: BrandSignals) -> _Attribution:
    tallies: dict[ArchetypeKey, _Tally] = {a.key: _Tally() for a in ARCHETYPES}
    attributed = 0
    demand = 0.0
    conversions = 0.0
    for signal in signals.searches:
        keys = classify_query(signal.query, signals.brand)
        if not keys:
            continue
        attributed += 1
        demand += signal.demand
        conversions += signal.conversions
        # O cautare cu doua motivatii ("pret garantie") se imparte egal intre ele.
        part = 1 / len(keys)
        for key in keys:
            tally = tallies[key]
            tally.demand += signal.demand * part
            tally.conversions += signal.conversions * part
            if signal.origin == "paid":
                tally.paid_clicks += signal.clicks * part
            # Pentru exemple si teme, cumparatorii cantaresc mai mult decat curiosii.
            weight = (signal.demand + 100 * signal.conversions) * part
            tally.queries[signal.query] = tally.queries.get(signal.query, 0.0) + weight
    return _Attribution(tallies, attributed, demand, conversions)


def _samples(tally: _Tally) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for query, _ in sorted(tally.queries.items(), key=lambda item: (-item[1], item[0])):
        key = " ".join(tokenize(query))
        if key not in seen:
            seen.add(key)
            ordered.append(query)
        if len(ordered) == MAX_SAMPLE_QUERIES:
            break
    return ordered


def _segments(attribution: _Attribution) -> list[AvatarSegment]:
    total_demand = attribution.attributed_demand or 1.0
    use_buyers = attribution.conversions >= MIN_CONVERSIONS
    segments: list[AvatarSegment] = []
    for archetype in ARCHETYPES:
        tally = attribution.tallies[archetype.key]
        if not tally.queries:
            continue
        demand_share = tally.demand / total_demand
        buyer_share = tally.conversions / attribution.conversions if use_buyers else None
        share = demand_share if buyer_share is None else (demand_share + buyer_share) / 2
        segments.append(
            AvatarSegment(
                key=archetype.key,
                name=archetype.name,
                share=round(share, 4),
                demand_share=round(demand_share, 4),
                buyer_share=None if buyer_share is None else round(buyer_share, 4),
                paid_clicks=round(tally.paid_clicks),
                conversions=round(tally.conversions, 2),
                sample_queries=_samples(tally),
            )
        )
    segments.sort(key=lambda s: (-s.share, _ORDER[s.key]))
    return segments


# --- simularea: fiecare profil "citeste" fiecare reclama ----------------------


def _stance(hooks: Sequence[str], repellers: Sequence[str]) -> Stance:
    if hooks and not repellers:
        return "supportive"
    if repellers and not hooks:
        return "opposing"
    if hooks and repellers:
        return "neutral"
    return "observer"


def simulate_reactions(ad: LiveAd) -> tuple[list[PersonaReaction], bool]:
    """Reactia fiecarui profil la ``ad`` si daca textul e tehnic."""
    tokens = tokenize(ad.text)
    technical = technical_density(ad.text) >= TECHNICAL_DENSITY
    reactions: list[PersonaReaction] = []
    for archetype in ARCHETYPES:
        hooks = [text for text, phrase in _HOOKS[archetype.key] if _contains(tokens, phrase)]
        repellers = [
            text for text, phrase in _REPELLERS[archetype.key] if _contains(tokens, phrase)
        ]
        if technical:
            if archetype.key == "research":
                hooks.append("detalii tehnice")
            elif archetype.rejects_jargon:
                repellers.append("jargon tehnic")
        reactions.append(
            PersonaReaction(
                key=archetype.key,
                stance=_stance(hooks, repellers),
                resonance=min(1.0, len(hooks) / HOOKS_FOR_FULL_RESONANCE),
                hooks_found=hooks,
                repellers_found=repellers,
            )
        )
    return reactions, technical


_STANCE_VALUE: dict[Stance, float] = {"neutral": 0.25, "observer": 0.0, "opposing": -0.25}


def _alignment_score(
    reactions: Sequence[PersonaReaction], shares: dict[ArchetypeKey, float]
) -> float:
    """Reactia asteptata a populatiei: suma reactiilor, ponderata cu cota profilurilor."""
    total = 0.0
    for reaction in reactions:
        value = (
            reaction.resonance
            if reaction.stance == "supportive"
            else _STANCE_VALUE[reaction.stance]
        )
        total += shares.get(reaction.key, 0.0) * value
    return round(min(1.0, max(0.0, total)), 2)


def _speaks_to(reactions: Sequence[PersonaReaction]) -> ArchetypeKey | None:
    best = max(reactions, key=lambda r: (r.resonance, -_ORDER[r.key]))
    return best.key if best.resonance > 0 else None


def _quote(values: Sequence[str]) -> str:
    return ", ".join(f"«{value}»" for value in values)


def _cpa_sentence(ad: LiveAd) -> str:
    cpa = ad.cpa
    if cpa is None:
        return " Nu există performanță legată de acest text, deci nici un CPA de apărat."
    if ad.target_cpa is not None and cpa <= ad.target_cpa:
        return (
            f" CPA-ul ({_ron(cpa)} RON) e sub ținta de {_ron(ad.target_cpa)} RON - matematic "
            "reclama pare stabilă, dar vorbește altui profil decât clientului ideal."
        )
    if ad.target_cpa is not None:
        return f" CPA-ul ({_ron(cpa)} RON) e și peste ținta de {_ron(ad.target_cpa)} RON."
    return f" CPA actual: {_ron(cpa)} RON."


def _evaluate_ad(
    ad: LiveAd,
    avatar: AvatarProfile | None,
    shares: dict[ArchetypeKey, float],
    mode: DecisionMode | None = None,
) -> AdAlignment:
    reactions, technical = simulate_reactions(ad)
    demand, why = ad_demand(ad.text, technical=technical)
    speaks_to = _speaks_to(reactions)
    score = _alignment_score(reactions, shares)
    avatar_reaction = next((r for r in reactions if avatar and r.key == avatar.key), None)
    avatar_stance: Stance = avatar_reaction.stance if avatar_reaction else "observer"

    deviates = False
    if avatar is None or avatar_reaction is None:
        reason = "Fără client ideal (date insuficiente) - reclama nu se judecă."
    elif avatar_stance == "opposing":
        deviates = avatar.dominant
        reason = (
            f"Reclama îl respinge pe «{avatar.name}»: conține "
            f"{_quote(avatar_reaction.repellers_found)} - exact ce îl îndepărtează."
        )
    elif avatar_stance == "observer":
        deviates = avatar.dominant
        archetype = _BY_KEY[avatar.key]
        reason = (
            f"Reclama nu îi spune nimic lui «{avatar.name}»: niciun semnal despre "
            f"{archetype.voice}."
        )
        if speaks_to is not None and speaks_to != avatar.key:
            other = _BY_KEY[speaks_to]
            reason += f" Vorbește în schimb «{other.name}» ({other.voice})."
    elif avatar_stance == "neutral":
        reason = (
            f"Parțial aliniată: «{avatar.name}» găsește {_quote(avatar_reaction.hooks_found)}, "
            f"dar și {_quote(avatar_reaction.repellers_found)}."
        )
    else:
        reason = f"Aliniată: «{avatar.name}» găsește {_quote(avatar_reaction.hooks_found)}."

    if avatar is not None and not avatar.dominant and avatar_stance in ("observer", "opposing"):
        reason += (
            " Nu cer rescrierea: cererea e împărțită între profiluri, niciunul peste "
            f"{DOMINANT_SHARE:.0%}."
        )
    if deviates:
        reason += _cpa_sentence(ad)

    return AdAlignment(
        ref=ad.ref,
        platform=ad.platform,
        headline=ad.headline,
        text=ad.text,
        alignment_score=score,
        avatar_stance=avatar_stance,
        speaks_to=speaks_to,
        technical=technical,
        cpa=ad.cpa,
        target_cpa=ad.target_cpa,
        deviates=deviates,
        reason=reason,
        reactions=reactions,
        cognitive_demand=demand,
        cognitive_note=ad_fit_note(mode, ad.headline, demand, why) if mode else None,
    )


# --- asamblarea directivei -----------------------------------------------------

_STOPWORDS = frozenset(
    {
        "de", "la", "cu", "si", "in", "pe", "pentru", "din", "un", "una", "o", "al", "ale",
        "cel", "cea", "cele", "cei", "mai", "se", "este", "sunt", "sa", "nu", "care", "ce",
        "cum", "cand", "unde", "cine", "cat", "cate", "cati", "fara", "sau", "ori", "dupa",
        "prin", "lui", "lor", "meu", "mea", "mele", "tau", "ta", "le", "ma", "te", "ne",
    }
)
_SIGNAL_TOKENS = frozenset(
    token
    for archetype in ARCHETYPES
    for value in (*archetype.query_markers, *archetype.hooks)
    for token in tokenize(value)
)


def _topics(tally: _Tally, brand: str, limit: int = 3) -> list[str]:
    """Temele (produse/servicii) din cautarile unui profil, fara cuvintele de motivatie."""
    brand_tokens = set(tokenize(brand))
    weights: dict[str, float] = {}
    forms: dict[str, dict[str, float]] = {}
    for query, weight in tally.queries.items():
        for token in tokenize(query):
            if (
                len(token) < 4
                or token.isdigit()
                or token in _STOPWORDS
                or token in _SIGNAL_TOKENS
                or token in brand_tokens
            ):
                continue
            # Radacina grosiera: "cutie"/"cutia" si "automata"/"automat" sunt aceeasi tema.
            stem = token[:4]
            weights[stem] = weights.get(stem, 0.0) + weight
            bucket = forms.setdefault(stem, {})
            bucket[token] = bucket.get(token, 0.0) + weight
    top = sorted(weights, key=lambda stem: (-weights[stem], stem))[:limit]
    return [max(forms[stem], key=lambda form: (forms[stem][form], form)) for stem in top]


def _targeting(
    avatar: AvatarProfile, attribution: _Attribution, segments: Sequence[AvatarSegment], brand: str
) -> list[TargetingAdjustment]:
    archetype = _BY_KEY[avatar.key]
    adjustments = [
        TargetingAdjustment(
            kind="delivery",
            suggestion=archetype.delivery,
            idea=archetype.delivery_idea,
            reason=f"«{avatar.name}» e {_percent(avatar.share)} din ce aduce contul.",
        )
    ]
    topics = _topics(attribution.tallies[avatar.key], brand)
    if topics:
        adjustments.append(
            TargetingAdjustment(
                kind="interest",
                suggestion=(
                    "Caută în Detailed Targeting interese apropiate de "
                    f"{_quote(topics)} și testează-le ca set separat."
                ),
                idea=f"un test de interese apropiate de {_quote(topics)}, ca set separat",
                reason=f"Temele care revin în căutările lui «{avatar.name}».",
            )
        )
    if attribution.conversions >= MIN_CONVERSIONS_FOR_LOOKALIKE:
        adjustments.append(
            TargetingAdjustment(
                kind="audience",
                suggestion="Lookalike 1% pornind de la cei care au convertit.",
                idea="o audiență Lookalike 1% pornind de la cei care au convertit",
                reason=(
                    f"{_count(attribution.conversions, 'conversii')} în fereastră - destule "
                    "pentru audiența-sursă minimă a Meta (100 de oameni)."
                ),
            )
        )
    for segment in segments:
        other = _BY_KEY[segment.key]
        if (
            segment.key != avatar.key
            and other.exclusion_theme
            and segment.paid_clicks >= MIN_PAID_CLICKS_FOR_EXCLUSION
            and segment.conversions == 0
        ):
            adjustments.append(
                TargetingAdjustment(
                    kind="exclusion",
                    suggestion=f"Exclude interesele {other.exclusion_theme}.",
                    idea=f"excluderea intereselor {other.exclusion_theme}",
                    reason=(
                        f"Profilul «{other.name}» a adus "
                        f"{_count(segment.paid_clicks, 'click-uri plătite')} și nicio "
                        "conversie în fereastră."
                    ),
                )
            )
    return adjustments


def _angle(avatar: AvatarProfile, alignments: Sequence[AdAlignment]) -> CopywritingAngle:
    archetype = _BY_KEY[avatar.key]
    if not alignments:
        summary = (
            f"Nu există încă reclame cu text în sistem. Scrie-le despre {archetype.voice}, "
            f"pentru «{archetype.name}». Ton: {archetype.tone}."
        )
    elif sum(ad.deviates for ad in alignments) * 2 >= len(alignments) and any(
        ad.deviates for ad in alignments
    ):
        technical = sum(ad.technical for ad in alignments) * 2 >= len(alignments)
        voices = [ad.speaks_to for ad in alignments if ad.speaks_to and ad.speaks_to != avatar.key]
        if technical:
            current = "tehnice"
        elif voices:
            common = max(set(voices), key=lambda key: (voices.count(key), -_ORDER[key]))
            current = f"despre {_BY_KEY[common].voice}"
        else:
            current = "generice"
        summary = (
            f"Schimbă textele din {current} în texte despre {archetype.voice}. "
            f"Ton: {archetype.tone}."
        )
    else:
        summary = (
            f"Reclamele vorbesc deja pe limba lui «{archetype.name}» - păstrează unghiul "
            f"({archetype.voice}) și testează variații pe {archetype.proof_points[0]}."
        )
    avoid = list(archetype.objections)
    if archetype.rejects_jargon:
        avoid.append("jargon tehnic (acronime, coduri de piese)")
    return CopywritingAngle(
        summary=summary,
        emotion_trigger=archetype.emotion_trigger,
        tone=archetype.tone,
        hooks=list(archetype.copy_examples),
        must_include=list(archetype.proof_points),
        avoid=avoid,
    )


def _narrative(avatar: AvatarProfile, segments: Sequence[AvatarSegment]) -> str:
    archetype = _BY_KEY[avatar.key]
    top = segments[0]
    share_text = f"{_percent(top.demand_share)} din cererea atribuită"
    if top.buyer_share is not None:
        share_text += f" și {_percent(top.buyer_share)} din conversii"
    parts = [
        f"Clientul ideal: «{archetype.name}» - {share_text}.",
        f"Caută: {_quote(avatar.sample_queries)}.",
        f"Ce îl doare: {'; '.join(archetype.pains)}.",
        f"Ce vrea: {'; '.join(archetype.desires)}.",
        f"Ce îl enervează: {'; '.join(archetype.objections)}.",
        f"Cum decide: {archetype.decision_style}.",
    ]
    if len(segments) > 1:
        second = _BY_KEY[segments[1].key]
        parts.append(
            f"Al doilea profil ca pondere: «{second.name}» ({_percent(segments[1].share)}) - "
            f"vrea {second.desires[0]}."
        )
    if not avatar.dominant:
        parts.append(
            f"Cererea e împărțită: niciun profil nu trece de {_percent(DOMINANT_SHARE)}, "
            "deci unghiul e de testat A/B, nu de impus."
        )
    return " ".join(parts)


_DEMOGRAPHICS_NOTE = (
    "Vârsta și genul nu se pot deduce din căutări, deci directiva nu le inventează. "
    "Pentru ele, vezi în Meta Ads Manager defalcarea pe vârstă și gen a celor care au convertit."
)


def build_directive(
    client_account_id: int, signals: BrandSignals, *, generated_at: datetime
) -> BrandStrategyDirective:
    """Directiva completa din semnale - functie pura, determinista."""
    attribution = _attribute(signals)
    segments = _segments(attribution)
    basis = DataBasis(
        queries_total=len(signals.searches),
        queries_attributed=attribution.queries_attributed,
        organic_queries=sum(s.origin == "organic" for s in signals.searches),
        paid_terms=sum(s.origin == "paid" for s in signals.searches),
        attributed_demand=round(attribution.attributed_demand),
        conversions=round(attribution.conversions, 2),
        ads_evaluated=len(signals.ads),
        ads_with_performance=sum(ad.spend is not None for ad in signals.ads),
    )
    notes = [*signals.notes, _DEMOGRAPHICS_NOTE]

    if not attribution.is_sufficient() or not segments:
        queries = _count(attribution.queries_attributed, "căutări atribuite", "căutare atribuită")
        return BrandStrategyDirective(
            client_account_id=client_account_id,
            generated_at=generated_at,
            status="insufficient_data",
            ideal_avatar_profile=(
                f"Date insuficiente pentru un client ideal: {queries}, cu "
                f"{_count(round(attribution.attributed_demand), 'afișări', 'afișare')} și "
                f"{_count(attribution.conversions, 'conversii', 'conversie')} (minimul: "
                f"{_count(MIN_ATTRIBUTED_QUERIES, 'căutări')} și "
                f"{_count(MIN_ATTRIBUTED_DEMAND, 'afișări')} sau "
                f"{_count(MIN_CONVERSIONS, 'conversii')}). "
                "Regina nu construiește un avatar din ghicit - conectează Search Console și "
                "lasă campaniile să adune termeni de căutare."
            ),
            avatar=None,
            segments=segments,
            targeting_adjustments=[],
            copywriting_angle=None,
            ad_alignment=[_evaluate_ad(ad, None, {}) for ad in signals.ads],
            cognitive_profile=None,
            data_basis=basis,
            notes=notes,
        )

    top = segments[0]
    archetype = _BY_KEY[top.key]
    avatar = AvatarProfile(
        key=top.key,
        name=top.name,
        share=top.share,
        dominant=top.share >= DOMINANT_SHARE,
        pains=list(archetype.pains),
        desires=list(archetype.desires),
        objections=list(archetype.objections),
        decision_style=archetype.decision_style,
        sample_queries=top.sample_queries,
    )
    shares = {segment.key: segment.share for segment in segments}
    psychology = cognitive_profile(segments)
    alignments = [
        _evaluate_ad(ad, avatar, shares, psychology.decision_mode) for ad in signals.ads
    ]
    return BrandStrategyDirective(
        client_account_id=client_account_id,
        generated_at=generated_at,
        status="ok",
        ideal_avatar_profile=_narrative(avatar, segments),
        avatar=avatar,
        segments=segments,
        targeting_adjustments=_targeting(avatar, attribution, segments, signals.brand),
        copywriting_angle=_angle(avatar, alignments),
        ad_alignment=alignments,
        cognitive_profile=psychology,
        data_basis=basis,
        notes=notes,
    )


# --- vocea CMO: directiva explicata clientului --------------------------------
#
# Un LLM (Hugging Face, vezi ``hf_client.py``) doar TRADUCE directiva in limbaj
# de consultant. Nu decide nimic: primeste faptele deja calculate, iar textul
# lui trece prin ``check_cmo_message`` inainte sa ajunga la client. Orice cifra
# pe care n-a primit-o, orice vorba despre buget sau licitari, orice link ->
# se foloseste mesajul din template, determinist. Nimic din raspunsul LLM nu se
# citeste inapoi in vreo decizie.


class TextGenerator(Protocol):
    """Un LLM: prompt de sistem + prompt de utilizator -> text."""

    @property
    def model(self) -> str: ...

    def complete(self, *, system: str, user: str) -> str: ...


MessageSource = Literal["llm", "template"]


class CmoMessage(BaseModel):
    """Mesajul Reginei catre client, cu sursa lui (LLM sau template)."""

    client_account_id: int
    message: str
    source: MessageSource
    #: Modelul care a formulat mesajul; ``None`` pentru template.
    model: str | None
    #: De ce s-a folosit template-ul (fara cheie, eroare, mesaj respins).
    fallback_reason: str | None
    directive_status: DirectiveStatus
    generated_at: datetime


#: Cate reclame deviate ajung in mesaj - restul se numara, nu se enumera.
MAX_ADS_IN_MESSAGE = 2
MAX_MESSAGE_CHARS = 1600
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
#: Subiectele pe care directiva nu le atinge niciodata - daca LLM-ul le aduce
#: in discutie fara sa fi aparut in fapte, inventeaza decizii.
_OFF_LIMITS = ("buget", "licit", "bid")

CMO_SYSTEM_PROMPT = (
    "Ești Senior AI Chief Marketing Officer al agenției AC Media. Scrii clientului "
    "(proprietarul afacerii) un mesaj scurt, B2B, în limba română, care explică DE CE "
    "sistemul a propus deciziile din secțiunea FAPTE.\n"
    "Reguli stricte:\n"
    "1. Folosești DOAR faptele primite. Nu inventa cifre, procente, prețuri, date sau "
    "rezultate promise. Orice număr din mesaj trebuie să apară în FAPTE.\n"
    "2. Nu anunța și nu propune nimic în afara FAPTELOR, în special nimic despre "
    "bugete sau licitări. Deciziile sunt deja calculate și așteaptă aprobarea "
    "clientului; tu doar le explici.\n"
    "3. Structură: cine e publicul ideal și pe ce se bazează concluzia; cum decide și ce îl "
    "oprește să cumpere (psihologia din FAPTE); ce reclamă nu îi vorbește și de ce; ce am "
    "propus și că totul așteaptă aprobarea lui.\n"
    "4. Maximum 150 de cuvinte, la persoana I plural («am observat»), adresându-te cu «tu». "
    "Fără markdown, fără liste, fără linkuri.\n\n"
    f"{CONSULTANT_VOICE}"
)


def cmo_facts(directive: BrandStrategyDirective) -> str:
    """Faptele pe care le primeste LLM-ul - singura lui sursa de adevar."""
    lines = [directive.ideal_avatar_profile]
    psychology = directive.cognitive_profile
    if psychology is not None:
        lines.append(
            f"Psihologia cumpărătorului (calculată determinist): {psychology.summary} "
            f"{psychology.decision_mode.evidence} {psychology.barrier.evidence}"
        )
        lines.append(
            "Legendă Kahneman: Sistemul 1 = decizie rapidă, pe intuiție; Sistemul 2 = decizie "
            "cântărită, cu efort."
        )
    misaligned = directive.misaligned_ads
    for ad in misaligned[:MAX_ADS_IN_MESSAGE]:
        line = f"Reclamă care nu îi vorbește clientului ideal ({ad.platform}): «{ad.headline}». "
        line += ad.reason
        if ad.cognitive_note:
            line += f" {ad.cognitive_note}"
        lines.append(line)
    if len(misaligned) > MAX_ADS_IN_MESSAGE:
        extra = len(misaligned) - MAX_ADS_IN_MESSAGE
        lines.append(f"Încă {_count(extra, 'reclame', 'reclamă')} în aceeași situație.")
    aligned = len(directive.ad_alignment) - len(misaligned)
    if aligned:
        lines.append(f"Reclame deja aliniate cu clientul ideal: {aligned}.")
    angle = directive.copywriting_angle
    if angle is not None:
        lines.append(
            f"Unghiul de copy propus: {angle.summary} De inclus: {'; '.join(angle.must_include)}. "
            f"De evitat: {'; '.join(angle.avoid)}."
        )
    for adjustment in directive.targeting_adjustments:
        lines.append(f"Ajustare Meta Ads: {adjustment.suggestion} Motiv: {adjustment.reason}")
    lines.append(
        "Starea deciziilor: toate sunt propuneri care așteaptă aprobarea clientului; "
        "nimic nu s-a aplicat încă."
    )
    return "\n".join(f"- {line}" for line in lines)


def build_cmo_prompt(directive: BrandStrategyDirective) -> tuple[str, str]:
    """Promptul de sistem si cel de utilizator pentru vocea CMO."""
    return CMO_SYSTEM_PROMPT, f"FAPTE:\n{cmo_facts(directive)}\n\nScrie mesajul către client."


def _numbers(text: str) -> set[str]:
    found: set[str] = set()
    for raw in _NUMBER.findall(text):
        value = Decimal(raw.replace(",", ".")).normalize()
        found.add(format(value, "f"))
    return found


def check_cmo_message(message: str, *, facts: str) -> str | None:
    """De ce NU se poate trimite mesajul LLM-ului clientului, sau ``None`` daca se poate.

    Garda care tine LLM-ul in rolul de traducator: nu are voie sa aduca cifre,
    subiecte (bugete, licitari) sau linkuri pe care nu le-a primit.
    """
    text = message.strip()
    if not text:
        return "Modelul a întors un mesaj gol - mesaj din template."
    if len(text) > MAX_MESSAGE_CHARS:
        return "Mesajul modelului era prea lung - mesaj din template."
    if "http" in text.lower() or "www." in text.lower():
        return "Mesajul modelului conținea linkuri - mesaj din template."
    invented = sorted(_numbers(text) - _numbers(facts))
    if invented:
        return (
            f"Mesajul modelului conținea cifre care nu sunt în date ({', '.join(invented)}) "
            "- mesaj din template."
        )
    message_tokens = tokenize(text)
    fact_tokens = tokenize(facts)
    for topic in _OFF_LIMITS:
        mentioned = any(token.startswith(topic) for token in message_tokens)
        if mentioned and not any(token.startswith(topic) for token in fact_tokens):
            return (
                f"Mesajul modelului vorbea despre «{topic}...», subiect pe care Regina nu îl "
                "atinge - mesaj din template."
            )
    return None


def _lower_first(text: str) -> str:
    """Prima litera mica, pentru continuarea unei fraze - dar nu intr-un acronim ("LCP", "CPA")."""
    if text[1:2].isupper():
        return text
    return text[:1].lower() + text[1:]


def _why_not(ad: AdAlignment, avatar: AvatarProfile) -> str:
    """De ce nu ii vorbeste reclama clientului ideal, pe scurt."""
    reaction = next((r for r in ad.reactions if r.key == avatar.key), None)
    if reaction is not None and reaction.repellers_found:
        return f"conține {_quote(reaction.repellers_found)}, exact ce îl îndepărtează"
    why = f"nu îi spune nimic despre {_BY_KEY[avatar.key].voice}"
    if ad.speaks_to is not None and ad.speaks_to != avatar.key:
        why += f", ci vorbește despre {_BY_KEY[ad.speaks_to].voice}"
    return why


def template_cmo_message(directive: BrandStrategyDirective) -> str:
    """Mesajul determinist - fallback-ul vocii CMO, cu aceleasi fapte."""
    avatar = directive.avatar
    angle = directive.copywriting_angle
    if directive.status != "ok" or avatar is None or angle is None or not directive.segments:
        return f"Încă nu pot contura clientul tău ideal. {directive.ideal_avatar_profile}"

    top = directive.segments[0]
    detail = f"{_percent(top.demand_share)} din căutări"
    if top.buyer_share is not None:
        detail += f" și {_percent(top.buyer_share)} din conversii"
    parts = [
        "Am analizat căutările și reclamele contului tău. Publicul tău ideal este "
        f"«{avatar.name}» ({detail}): vrea {_BY_KEY[avatar.key].desires[0]}."
    ]
    misaligned = directive.misaligned_ads
    if misaligned:
        ad = misaligned[0]
        parts.append(f"Reclama «{ad.headline}» nu îi vorbește: {_why_not(ad, avatar)}.")
        if ad.cpa is not None and ad.target_cpa is not None and ad.cpa <= ad.target_cpa:
            parts.append(
                f"Chiar dacă CPA-ul ei ({_ron(ad.cpa)} RON) e sub țintă, aduce alt public decât "
                "cel care contează."
            )
        if len(misaligned) > 1:
            others = _count(len(misaligned) - 1, "reclame", "reclamă")
            parts.append(f"La fel și încă {others}.")
        parts.append(f"Ce am propus: {_lower_first(angle.summary)}")
    else:
        parts.append(angle.summary)
    delivery = next((t for t in directive.targeting_adjustments if t.kind == "delivery"), None)
    if delivery is not None:
        parts.append(f"Pe Meta Ads recomandăm: {_lower_first(delivery.suggestion)}")
    exclusion = next((t for t in directive.targeting_adjustments if t.kind == "exclusion"), None)
    if exclusion is not None:
        parts.append(f"Tot acolo: {_lower_first(exclusion.suggestion)} {exclusion.reason}")
    parts.append("Toate sunt propuneri: nimic nu se aplică până nu le aprobi tu.")
    return " ".join(parts)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class BrandStrategist:
    """Regina: evalueaza alinierea brandului unui client si intoarce directiva.

    Nu scrie nimic si nu apeleaza nicio platforma de reclame - doar citeste
    semnalele prin ``signals`` si decide. ``voice`` (optional) e LLM-ul care
    explica directiva clientului - vezi :meth:`generate_cmo_message`.
    """

    def __init__(
        self,
        signals: BrandSignalsSource,
        *,
        voice: TextGenerator | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._signals = signals
        self._voice = voice
        self._clock = clock

    def evaluate_brand_alignment(self, client_account_id: int) -> BrandStrategyDirective:
        signals = self._signals.load(client_account_id)
        return build_directive(client_account_id, signals, generated_at=self._clock())

    def generate_cmo_message(
        self, client_account_id: int, directive: BrandStrategyDirective
    ) -> CmoMessage:
        """Directiva, explicata clientului ca de un CMO.

        LLM-ul primeste doar faptele directivei si doar formuleaza. Fara voce,
        cand pica sau cand raspunsul lui nu trece :func:`check_cmo_message`,
        mesajul vine din :func:`template_cmo_message` - deci ruta nu pica niciodata.

        Raises:
            ValueError: directiva e a altui client decat ``client_account_id``.
        """
        if directive.client_account_id != client_account_id:
            raise ValueError("directiva apartine altui client - nu o comunic")

        def _template(reason: str) -> CmoMessage:
            return CmoMessage(
                client_account_id=client_account_id,
                message=template_cmo_message(directive),
                source="template",
                model=None,
                fallback_reason=reason,
                directive_status=directive.status,
                generated_at=self._clock(),
            )

        if directive.status != "ok":
            return _template("Nu există încă un client ideal de explicat - mesajul standard.")
        if self._voice is None:
            return _template("Vocea LLM nu e configurată - mesaj din template.")

        system, user = build_cmo_prompt(directive)
        try:
            text = self._voice.complete(system=system, user=user)
        except Exception as exc:  # vocea e optionala: orice eroare -> template
            logger.warning(
                "[Regina] vocea CMO a picat pentru clientul %s: %s", client_account_id, exc
            )
            return _template(f"Modelul nu a răspuns ({type(exc).__name__}) - mesaj din template.")

        problem = check_cmo_message(text, facts=user)
        if problem is not None:
            logger.warning(
                "[Regina] mesaj LLM respins pentru clientul %s: %s", client_account_id, problem
            )
            return _template(problem)
        tells = ai_tells(text)
        if tells:  # stil, nu halucinatie: mesajul pleaca, dar se vede cat tine vocea
            logger.info("[Regina] tic-uri de text generat: %s", ", ".join(tells))
        return CmoMessage(
            client_account_id=client_account_id,
            message=text.strip(),
            source="llm",
            model=self._voice.model,
            fallback_reason=None,
            directive_status=directive.status,
            generated_at=self._clock(),
        )
