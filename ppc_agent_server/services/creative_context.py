"""Ce circula intre agenti in jurul unei creative: contextul CCO-ului si feedback-ul PPC.

Organismul, pe scurt::

    interviul clientului --CustomerAvatar (JTBD)--> CCO
    CMO (Regina) --ipoteza (Experiment)---------> CCO
    GitHub Actions (luni) --TrendPayload--> /trends/ingest --vectori--> trends_db
    trends_db --ce merge ACUM pe Meta/TikTok-----> CCO
    CCO --verdict + scoruri (creativeevaluation)--> lansare (PPC)
    PPC --PerformanceFeedback (hook rate, CTR, ROAS)--> CCO --lectii--> urmatoarea evaluare

Aici stau doar interfetele (Pydantic) si regulile pure de calibrare: o prezicere a CCO-ului
contrazisa de piata devine o lectie (``CalibrationLesson``), iar lectiile unui cont
corecteaza scorurile urmatoarelor creative de pe el; un concept care a esuat deja (acelasi
fisier sau acelasi hook, spus putin altfel) nu mai primeste un scor mare. Ce citeste si
scrie in baza de date e in ``creative_memory.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from ppc_agent.creative.concepts import ConceptTemplate
from ppc_agent.texttools import tokenize
from ppc_agent_server.services.avatar_builder import CustomerAvatar
from ppc_agent_server.services.propensity import Experiment
from ppc_agent_server.services.ro_format import percent

Purpose = Literal["ad", "page"]
AdPlatform = Literal["meta", "tiktok"]
TrendPlatform = Literal["meta", "tiktok", "all"]
CalibratedScore = Literal["hook_power", "message_match"]
FeedbackMetric = Literal["hook_rate", "ctr", "roas"]
Direction = Literal["overestimated", "underestimated"]

#: Sub atatea afisari, hook rate-ul si CTR-ul sunt zgomot.
MIN_IMPRESSIONS = 1000
#: Sub atatea click-uri, ROAS-ul e zgomot (ca la experimentele CMO-ului).
MIN_CLICKS_FOR_ROAS = 100
#: Un scor "puternic" al CCO-ului, care promite...
STRONG_SCORE = 8
#: ...si unul "slab", care nu promite nimic.
WEAK_SCORE = 4
#: Hook rate = vizionari de 3 secunde / afisari. Sub 20%, deschiderea nu tine.
HOOK_RATE_FLOOR = 0.20
HOOK_RATE_STRONG = 0.35
#: La imagini, CTR-ul e masura hook-ului (feed-ul Meta e pe la 1%).
CTR_FLOOR = 0.008
CTR_STRONG = 0.02
#: Un ROAS de atatea ori pragul = un mesaj subestimat.
ROAS_STRONG_RATIO = 1.5
#: Cat de departe in trecut citeste CCO-ul lectiile unui cont.
CALIBRATION_WINDOW_DAYS = 90
#: Cu cat muta lectiile un scor, cel mult.
MAX_BIAS = 3
#: Peste atat nu urca un scor pe un concept care a esuat deja pe cont.
FAILED_CONCEPT_CAP = 5
#: Doua hook-uri sunt acelasi concept de la atata suprapunere a cuvintelor (Jaccard).
SAME_CONCEPT = 0.6
#: Cat traieste un trend in trends_db: dupa, il sterge urmatoarea ingestie.
TREND_TTL_DAYS = 30


class TrendInsight(BaseModel):
    """O nota din trends_db: ce merge acum pe o platforma, intr-o industrie."""

    platform: TrendPlatform
    #: Industria, in cuvinte cheie ("service auto, piese"); gol = orice industrie.
    industry: str = Field(max_length=120)
    insight: str = Field(min_length=5, max_length=800)
    source: str = Field(default="", max_length=200)
    observed_at: date


class CalibrationLesson(BaseModel):
    """O corectie din piata: ce a prezis CCO-ul si ce a aratat platforma."""

    score: CalibratedScore
    predicted: int = Field(ge=0, le=10)
    metric: FeedbackMetric
    actual: float
    threshold: float
    direction: Direction
    lesson: str
    #: Creativa care a esuat: fisierul si conceptul (hook-ul), ca sa fie recunoscuta.
    asset_sha256: str = ""
    concept: str = ""


class CreativeEvaluationContext(BaseModel):
    """Ce afla CCO-ul de la ceilalti agenti inainte sa judece o creativa.

    Obligatoriu la orice evaluare (``evaluate_creative(context=...)``): rutele il aduna cu
    ``creative_memory.build_context``. Avatarul si ipoteza pot lipsi doar cand nu exista
    inca (clientul n-a facut interviul, CMO-ul n-are o bariera) - verdictul o spune.
    """

    #: ``ad`` = reclama; ``page`` = imagine pentru landing page/blog (judecata pe GEO).
    purpose: Purpose = "ad"
    platform: AdPlatform | None = None
    #: Clientul ideal (JTBD), din interviul clientului.
    avatar: CustomerAvatar | None = None
    #: Ipoteza CMO-ului (experimentul pe bariera dominanta): ce trebuie sa faca reclama.
    cmo_hypothesis: Experiment | None = None
    #: Sablonul de concept pe care trebuie sa-l respecte ACEASTA reclama. ``None`` = cel
    #: din ipoteza CMO-ului (daca exista); o reclama de diversitate isi aduce sablonul ei.
    concept_template: ConceptTemplate | None = None
    #: Ce a gresit CCO-ul pe acest cont, dupa cifrele din piata.
    lessons: list[CalibrationLesson] = Field(default_factory=list)
    #: Ce merge ACUM pe platforma, in industria clientului (trends_db).
    trends: list[TrendInsight] = Field(default_factory=list)
    #: La ``page``: textul alternativ al imaginii, din pagina (agentul SEO).
    alt_text: str | None = Field(default=None, max_length=500)


class PerformanceMetrics(BaseModel):
    """Cifrele unei reclame, de la lansare: numaratorile, iar ratele calculate din ele."""

    impressions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    #: Vizionarile de 3 secunde (Meta ``video_view``); ``None`` la imagini.
    video_views_3s: int | None = Field(default=None, ge=0)
    spend: Decimal = Field(ge=0)
    revenue: Decimal = Field(ge=0)
    conversions: float = Field(ge=0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hook_rate(self) -> float | None:
        """Cati dintre cei care au vazut reclama au privit primele 3 secunde."""
        if self.video_views_3s is None or not self.impressions:
            return None
        return round(self.video_views_3s / self.impressions, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ctr(self) -> float | None:
        return round(self.clicks / self.impressions, 4) if self.impressions else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def roas(self) -> float | None:
        return round(float(self.revenue / self.spend), 2) if self.spend else None


class PerformanceFeedback(BaseModel):
    """PPC -> CCO: cum a mers in piata o creativa pe care CCO-ul a judecat-o."""

    #: Evaluarea CCO-ului (``creativeevaluation.id``) - de acolo vin scorurile prezise.
    evaluation_id: int
    platform: AdPlatform
    ad_id: str = Field(min_length=1, max_length=64)
    window_days: int = Field(ge=1, le=365)
    metrics: PerformanceMetrics
    #: Pragul de rentabilitate al contului; fara el, ROAS-ul nu se judeca.
    break_even_roas: float | None = Field(default=None, gt=0)


class TrendPayload(BaseModel):
    """Un trend trimis de automatizarea saptamanala (``scripts/trend_scraper.py``)."""

    title: str = Field(min_length=3, max_length=120)
    #: Cum incepe reclama care merge (primele secunde).
    hook: str = Field(min_length=5, max_length=300)
    #: Formatul vizual: "UGC 9:16, 15 s, subtitrari mari".
    visual_format: str = Field(min_length=2, max_length=120)
    #: De ce se viralizeaza.
    virality_reason: str = Field(min_length=5, max_length=300)
    platform: TrendPlatform = "all"
    #: Industria, in cuvinte cheie; gol = orice industrie.
    industry: str = Field(default="", max_length=120)
    source: str = Field(default="", max_length=200)
    #: Cand a fost vazut; gol = azi.
    observed_at: date | None = None

    def insight(self) -> str:
        """Ce vede CCO-ul in prompt."""
        return (
            f"{self.title}: {self.hook} Format: {self.visual_format}. "
            f"De ce merge: {self.virality_reason}"
        )


class TrendIngest(BaseModel):
    """Corpul ``POST /api/v1/trends/ingest``."""

    trends: list[TrendPayload] = Field(min_length=1, max_length=200)


class TrendIngestResult(BaseModel):
    received: int
    created: int
    updated: int
    #: Sterse acum: mai vechi de ``TREND_TTL_DAYS`` sau expirate.
    expired_deleted: int
    #: Modelul care a dat vectorii (``hash-trigram-256`` = lexicali, fara model).
    embedding_model: str


def _words(text: str) -> set[str]:
    return {word for word in tokenize(text) if len(word) >= 3}


def same_concept(left: str, right: str) -> bool:
    """Acelasi hook, spus poate putin altfel ("Revizie în 24h" ~ "Revizie completă în 24h")."""
    a, b = _words(left), _words(right)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= SAME_CONCEPT


def _two(value: float) -> str:
    """Doua zecimale, cu virgula romaneasca: 0,80."""
    return f"{value:.2f}".replace(".", ",")


def _platform(name: AdPlatform) -> str:
    return "Meta" if name == "meta" else "TikTok"


def calibrate(
    scores: Mapping[str, int | None], asset_type: str, feedback: PerformanceFeedback
) -> list[CalibrationLesson]:
    """Lectiile din piata: unde a promis CCO-ul mai mult (sau mai putin) decat a dat reclama.

    Hook-ul se judeca pe hook rate la video si pe CTR la imagini; alinierea mesajului,
    pe ROAS fata de pragul contului. Sub esantionul minim, nicio lectie.
    """
    metrics = feedback.metrics
    where = _platform(feedback.platform)
    lessons: list[CalibrationLesson] = []
    hook = scores.get("hook_power")
    if hook is not None and metrics.impressions >= MIN_IMPRESSIONS:
        video = asset_type == "video" and metrics.hook_rate is not None
        actual = metrics.hook_rate if video else metrics.ctr
        floor, strong = (HOOK_RATE_FLOOR, HOOK_RATE_STRONG) if video else (CTR_FLOOR, CTR_STRONG)
        seen = "au privit primele 3 secunde" if video else "au dat click"
        metric: FeedbackMetric = "hook_rate" if video else "ctr"
        assert actual is not None  # afisari > 0
        if hook >= STRONG_SCORE and actual < floor:
            lessons.append(
                CalibrationLesson(
                    score="hook_power", predicted=hook, metric=metric, actual=actual,
                    threshold=floor, direction="overestimated",
                    lesson=(
                        f"Hook-ul a primit {hook}/10, dar pe {where} doar {percent(actual)} "
                        f"{seen} (pragul: {percent(floor)}): deschiderea a promis mai mult "
                        "decât a ținut."
                    ),
                )
            )
        elif hook <= WEAK_SCORE and actual >= strong:
            lessons.append(
                CalibrationLesson(
                    score="hook_power", predicted=hook, metric=metric, actual=actual,
                    threshold=strong, direction="underestimated",
                    lesson=(
                        f"Hook-ul a primit doar {hook}/10, dar pe {where} {percent(actual)} "
                        f"{seen}: publicul acestui cont reacționează mai bine decât a crezut "
                        "CCO-ul."
                    ),
                )
            )
    match = scores.get("message_match")
    roas, floor_roas = metrics.roas, feedback.break_even_roas
    if (
        match is not None
        and roas is not None
        and floor_roas is not None
        and metrics.clicks >= MIN_CLICKS_FOR_ROAS
    ):
        if match >= STRONG_SCORE and roas < floor_roas:
            lessons.append(
                CalibrationLesson(
                    score="message_match", predicted=match, metric="roas", actual=roas,
                    threshold=floor_roas, direction="overestimated",
                    lesson=(
                        f"Mesajul a fost notat aliniat ({match}/10), dar ROAS-ul pe {where} e "
                        f"{_two(roas)}, sub pragul de {_two(floor_roas)}: alinierea pe hârtie "
                        "n-a adus vânzări."
                    ),
                )
            )
        elif match <= WEAK_SCORE and roas >= ROAS_STRONG_RATIO * floor_roas:
            lessons.append(
                CalibrationLesson(
                    score="message_match", predicted=match, metric="roas", actual=roas,
                    threshold=ROAS_STRONG_RATIO * floor_roas, direction="underestimated",
                    lesson=(
                        f"Mesajul a fost notat nealiniat ({match}/10), dar ROAS-ul pe {where} e "
                        f"{_two(roas)}: clientul ideal răspunde și la altceva decât a crezut "
                        "CCO-ul."
                    ),
                )
            )
    return lessons


def score_bias(lessons: Sequence[CalibrationLesson], score: CalibratedScore) -> tuple[int, int]:
    """Cu cat muta lectiile contului un scor (cel mult ``MAX_BIAS``) si din cate lectii."""
    over = sum(1 for item in lessons if item.score == score and item.direction == "overestimated")
    under = sum(
        1 for item in lessons if item.score == score and item.direction == "underestimated"
    )
    return max(-MAX_BIAS, min(MAX_BIAS, under - over)), over + under
