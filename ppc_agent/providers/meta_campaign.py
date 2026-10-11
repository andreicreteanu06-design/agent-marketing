"""Traduce ``CampaignObjective`` in formatul exact al Meta Marketing API (ODAX).

Totul aici e pur, fara niciun apel de retea: modulul construieste payload-urile,
nu le trimite. Trimiterea (si rollback-ul) sta in
:meth:`ppc_agent.providers.live.meta.LiveMetaMarketingProvider.launch_campaign`,
iar ajunge acolo DOAR dupa aprobarea umana a unei propuneri ``CREATE_CAMPAIGN``.

``objective`` e un camp de CAMPANIE in API-ul real (ODAX: ``OUTCOME_SALES``,
``OUTCOME_LEADS``, ...), dar ``optimization_goal``/``promoted_object`` sunt
campuri de AD SET, nu de campanie - Meta le separa asa, de-asta payload-ul de
mai jos are ambele niveluri, nu un singur dict plat.

Trei campuri pe care Meta le cere si pe care e usor sa le uiti - fiecare da
eroare dura la creare, verificate in documentatia Meta pentru v24-v25:

- ``is_adset_budget_sharing_enabled`` pe campanie, cand bugetul sta pe ad set
  (obligatoriu din v24, altfel eroarea 4834011);
- ``special_ad_categories`` pe campanie, chiar si gol;
- ``targeting_automation.advantage_audience`` pe ad set (obligatoriu din v23).

Optimizarea e fortata pe conversie: orice ad set construit aici are
``optimization_goal=OFFSITE_CONVERSIONS`` si ``promoted_object`` cu pixelul si un
eveniment pe care il trimitem si prin Conversions API (``CAPI_EVENT_TYPES``) - niciodata
click-uri pe link, vizualizari de pagina sau afisari. ``adset_fields`` verifica asta
inainte sa returneze, ca o schimbare viitoare sa nu poata strecura alt obiectiv.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, TypedDict

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.creative.concepts import CONCEPT_TEMPLATES

MetaObjective = Literal["OUTCOME_SALES", "OUTCOME_LEADS"]
MetaOptimizationGoal = Literal["OFFSITE_CONVERSIONS"]
MetaCustomEventType = Literal["PURCHASE", "SUBMIT_APPLICATION"]


class MetaPromotedObject(TypedDict):
    custom_event_type: MetaCustomEventType


class MetaAdSetOptimization(TypedDict):
    optimization_goal: MetaOptimizationGoal
    promoted_object: MetaPromotedObject


class MetaCampaignPayload(TypedDict):
    objective: MetaObjective
    ad_set: MetaAdSetOptimization


def build_meta_campaign_payload(objective: CampaignObjective) -> MetaCampaignPayload:
    """Payload-ul Meta (campanie + ad set) pentru un ``CampaignObjective`` dat.

    Ambele obiective optimizeaza pe conversii urmarite prin pixel/CAPI
    (``OFFSITE_CONVERSIONS``) - diferenta e evenimentul tinta: ``PURCHASE``
    pentru SALES; pentru LEAD_GEN, ``SUBMIT_APPLICATION`` - lead-ul calificat,
    trimis DOAR de server (``tracking/meta_capi.QUALIFIED_LEAD_EVENT``). Nu
    ``LEAD``: pe acela il trimite si pixelul, la orice formular completat.

    Args:
        objective: Obiectivul clientului (citit din ``ClientAccount.objective``,
            niciodata ghicit).

    Returns:
        ``objective`` la nivel de campanie plus ``optimization_goal`` si
        ``promoted_object`` la nivel de ad set.
    """
    event_type: MetaCustomEventType
    meta_objective: MetaObjective
    if objective == CampaignObjective.SALES:
        meta_objective, event_type = "OUTCOME_SALES", "PURCHASE"
    else:
        meta_objective, event_type = "OUTCOME_LEADS", "SUBMIT_APPLICATION"

    return {
        "objective": meta_objective,
        "ad_set": {
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "promoted_object": {"custom_event_type": event_type},
        },
    }


# --- lansarea unei campanii noi ---------------------------------------------

#: Evenimentele standard pe care le accepta ``promoted_object.custom_event_type``.
#: Validate AICI, inainte de orice apel: o greseala de tipar ("PURCHSE") ar fi
#: descoperita abia de Meta, dupa ce campania exista deja - adica rollback.
STANDARD_EVENT_TYPES = frozenset(
    {
        "ADD_PAYMENT_INFO",
        "ADD_TO_CART",
        "ADD_TO_WISHLIST",
        "COMPLETE_REGISTRATION",
        "CONTACT",
        "CONTENT_VIEW",
        "CUSTOMIZE_PRODUCT",
        "DONATE",
        "FIND_LOCATION",
        "INITIATED_CHECKOUT",
        "LEAD",
        "PURCHASE",
        "SCHEDULE",
        "SEARCH",
        "START_TRIAL",
        "SUBMIT_APPLICATION",
        "SUBSCRIBE",
        "OTHER",
    }
)

#: Evenimentele pe care le trimite si serverul nostru, calificate, prin Conversions API
#: (``ppc_agent_server/tracking/meta_capi.py``: Purchase, Lead, Contact si
#: SubmitApplication, lead-ul calificat trimis doar de server). Campania
#: optimizeaza DOAR pe unul dintre ele: pe un eveniment pe care CAPI nu-l trimite, Meta ar
#: invata doar din pixel, fara filtrul nostru de calificare.
CAPI_EVENT_TYPES = frozenset({"PURCHASE", "LEAD", "CONTACT", "SUBMIT_APPLICATION"})

#: Scara de evenimente la lead-uri: ``LEAD`` (trimis si de pixel, la orice formular) cat
#: timp bugetul nu hraneste ~50 de evenimente pe saptamana; peste, lead-ul calificat,
#: trimis doar de server (``ppc_agent_server/services/campaign_orders.optimization_event``).
STANDARD_LEAD_EVENT = "LEAD"
QUALIFIED_LEAD_EVENT = "SUBMIT_APPLICATION"

#: Parametrii adaugati la link-ul fiecarei reclame lansate (parametri dinamici Meta):
#: site-ul clientului citeste ``ad_id`` la intrare si il trimite inapoi cu conversia
#: (``docs/ghid-tracking-clienti.md``), ca lead-ul sa se lege de reclama care l-a adus.
AD_URL_TAGS = (
    "utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}"
    "&utm_content={{ad.id}}&ad_id={{ad.id}}"
)

#: Singura optimizare acceptata: conversii urmarite prin pixel + CAPI.
CONVERSION_OPTIMIZATION_GOAL = "OFFSITE_CONVERSIONS"

#: Butoanele de call-to-action acceptate. Lista e deliberat scurta - doar cele
#: pe care le folosim; Meta are mai multe, iar adaugarea uneia e o linie aici.
CALL_TO_ACTION_TYPES = frozenset(
    {
        "APPLY_NOW",
        "BUY_NOW",
        "CONTACT_US",
        "GET_OFFER",
        "GET_QUOTE",
        "LEARN_MORE",
        "ORDER_NOW",
        "SHOP_NOW",
        "SIGN_UP",
        "SUBSCRIBE",
    }
)

DEFAULT_CALL_TO_ACTION = {
    CampaignObjective.SALES: "SHOP_NOW",
    CampaignObjective.LEAD_GEN: "LEARN_MORE",
}

#: Toate obiectele create pornesc OPRITE - campania, ad set-ul SI anuntul. Daca
#: doar campania ar fi oprita, activarea ei din Ads Manager ar porni instantaneu
#: si un ad set creat activ, fara ca nimeni sa se fi uitat la el.
LAUNCH_STATUS = "PAUSED"

#: Versiunea formei in care specificatia se salveaza in propunere. O propunere
#: aprobata peste luni de zile trebuie sa se execute exact cum a fost aprobata,
#: iar daca forma se schimba, vrem sa refuzam, nu sa ghicim.
LAUNCH_SPEC_VERSION = 1
#: Propunerile cu mai multe reclame se salveaza cu versiunea 2; cele cu o singura
#: reclama raman la 1, deci propunerile deja salvate se citesc neschimbat.
LAUNCH_SPEC_VERSION_MULTI_AD = 2
_READABLE_SPEC_VERSIONS = (LAUNCH_SPEC_VERSION, LAUNCH_SPEC_VERSION_MULTI_AD)

#: Post-Andromeda, Meta cere diversitate de creativ in acelasi ad set (experti: 20+
#: la scara mare). La lansare prin API plafonam la 6: fiecare reclama aduce o
#: imagine de descarcat si un creative de creat, iar bugetul mic nu hraneste mai multe
#: (``decision/budget_strategy.recommend_arm_capacity``).
MAX_ADS_PER_LAUNCH = 6

_DIGITS = re.compile(r"^\d+$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_AD_ACCOUNT = re.compile(r"^(?:act_)?(\d+)$")


def normalize_ad_account_id(raw: str) -> str:
    """Id-ul contului de reclame in forma ceruta de Graph API: ``act_<cifre>``.

    Raises:
        ValueError: id gol sau care nu e numeric.
    """
    match = _AD_ACCOUNT.match(raw.strip())
    if match is None:
        raise ValueError(f"id de cont Meta invalid: '{raw}' (asteptat 'act_123' sau '123')")
    return f"act_{match.group(1)}"


def _require_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"'{name}' nu poate fi gol")
    return cleaned


def _require_https(name: str, value: str) -> str:
    cleaned = _require_text(name, value)
    if not cleaned.lower().startswith("https://"):
        raise ValueError(f"'{name}' trebuie sa fie un URL https:// ('{cleaned}')")
    return cleaned


#: Meta: un carusel are intre 2 si 10 carduri.
MIN_CAROUSEL_CARDS = 2
MAX_CAROUSEL_CARDS = 10


@dataclass(frozen=True, slots=True)
class CarouselCard:
    """Un card dintr-un carusel: imaginea lui si titlul de sub ea."""

    headline: str
    image_url: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_text("headline", self.headline)
        _require_https("image_url", self.image_url)

    def to_payload(self) -> dict[str, str]:
        return {
            "headline": self.headline,
            "image_url": self.image_url,
            "description": self.description,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CarouselCard:
        return cls(
            headline=str(payload["headline"]),
            image_url=str(payload["image_url"]),
            description=str(payload.get("description", "")),
        )


def _check_carousel(cards: tuple[CarouselCard, ...], video_url: str) -> None:
    if not cards:
        return
    if not MIN_CAROUSEL_CARDS <= len(cards) <= MAX_CAROUSEL_CARDS:
        raise ValueError(
            f"un carusel are intre {MIN_CAROUSEL_CARDS} si {MAX_CAROUSEL_CARDS} carduri "
            f"({len(cards)})"
        )
    if video_url:
        raise ValueError("o reclama e fie video, fie carusel, nu amandoua")


@dataclass(frozen=True, slots=True)
class MetaAdCreative:
    """O reclama in plus in acelasi ad set: alt text, alta imagine, alt unghi.

    ``angle`` e argumentul reclamei (de ce ar cumpara cineva), nu formatul. Meta
    grupeaza reclamele cu acelasi mesaj intr-una singura (creative similarity),
    deci o reclama care doar schimba imaginea nu aduce public nou.
    """

    headline: str
    primary_text: str
    #: Imaginea reclamei; la video, coperta (Meta cere una pentru orice reclama video).
    image_url: str
    angle: str = ""
    #: Gol = reclama cu imagine; altfel reclama video (``image_url`` devine coperta).
    video_url: str = ""
    #: Sablonul de concept (``creative/concepts.py``); gol = neetichetata.
    concept_template: str = ""
    #: Carduri de carusel (2-10); gol = o singura imagine. ``image_url`` ramane imaginea
    #: judecata de CCO - de regula cea a primului card.
    carousel: tuple[CarouselCard, ...] = ()

    def __post_init__(self) -> None:
        _require_text("headline", self.headline)
        _require_text("primary_text", self.primary_text)
        _require_https("image_url", self.image_url)
        _check_carousel(self.carousel, self.video_url)
        if self.video_url:
            _require_https("video_url", self.video_url)
        if self.concept_template and self.concept_template not in CONCEPT_TEMPLATES:
            raise ValueError(
                f"sablon de concept necunoscut '{self.concept_template}' - "
                f"accepta: {', '.join(sorted(CONCEPT_TEMPLATES))}"
            )

    @property
    def format(self) -> Literal["image", "video", "carousel"]:
        if self.carousel:
            return "carousel"
        return "video" if self.video_url else "image"

    @property
    def upload_images(self) -> list[str]:
        """Imaginile de urcat in Meta: cardurile caruselului, altfel imaginea (coperta)."""
        return [card.image_url for card in self.carousel] or [self.image_url]

    @property
    def media_url(self) -> str:
        """Ce se evalueaza: video-ul, cand exista; altfel imaginea."""
        return self.video_url or self.image_url

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "headline": self.headline,
            "primary_text": self.primary_text,
            "image_url": self.image_url,
            "angle": self.angle,
        }
        if self.video_url:
            payload["video_url"] = self.video_url
        if self.concept_template:
            payload["concept_template"] = self.concept_template
        if self.carousel:
            payload["carousel"] = [card.to_payload() for card in self.carousel]
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MetaAdCreative:
        try:
            return cls(
                headline=str(payload["headline"]),
                primary_text=str(payload["primary_text"]),
                image_url=str(payload["image_url"]),
                angle=str(payload.get("angle", "")),
                video_url=str(payload.get("video_url", "")),
                concept_template=str(payload.get("concept_template", "")),
                carousel=tuple(
                    CarouselCard.from_payload(card) for card in payload.get("carousel") or []
                ),
            )
        except KeyError as exc:
            raise ValueError(f"reclama in plus nu are campul {exc}") from exc


@dataclass(frozen=True, slots=True)
class MetaLaunchSpec:
    """Tot ce trebuie ca sa lansezi o campanie Meta de conversii, de la zero.

    Se salveaza in propunere la momentul propunerii si se executa, neschimbata,
    la aprobare. De-asta bugetul e in MONEDA CONTULUI (RON), nu in unitati
    minime: conversia se face abia in momentul trimiterii catre Meta, dupa
    moneda contului de atunci.

    Constructorul valideaza tot ce se poate valida fara retea - orice eroare
    prinsa aici e o campanie care nu mai trebuie stearsa dupa.
    """

    campaign_name: str
    objective: CampaignObjective
    daily_budget: Decimal
    pixel_id: str
    custom_event_type: str
    page_id: str
    target_url: str
    headline: str
    primary_text: str
    image_url: str
    country: str
    call_to_action: str
    #: Afacere locala: reclamele merg pe ``radius_km`` in jurul acestui punct, nu in
    #: toata tara (``country``). Toate trei, sau niciunul.
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    radius_km: Decimal | None = None
    #: Prima reclama ca video (``image_url`` devine coperta); gol = imagine.
    video_url: str = ""
    #: Sablonul de concept al primei reclame - de regula cel cerut de CMO.
    concept_template: str = ""
    #: Prima reclama ca carusel (2-10 carduri); gol = o singura imagine.
    carousel: tuple[CarouselCard, ...] = ()
    #: Reclame in plus, in acelasi ad set; prima reclama ramane cea din campurile de sus.
    extra_ads: tuple[MetaAdCreative, ...] = ()

    @property
    def ads(self) -> tuple[MetaAdCreative, ...]:
        """Toate reclamele lansarii, prima fiind cea din campurile principale."""
        first = MetaAdCreative(
            self.headline,
            self.primary_text,
            self.image_url,
            video_url=self.video_url,
            concept_template=self.concept_template,
            carousel=self.carousel,
        )
        return (first, *self.extra_ads)

    def __post_init__(self) -> None:
        _require_text("campaign_name", self.campaign_name)
        _ = self.ads  # valideaza si prima reclama (video, concept), nu doar cele in plus
        if len(self.extra_ads) + 1 > MAX_ADS_PER_LAUNCH:
            raise ValueError(
                f"maxim {MAX_ADS_PER_LAUNCH} reclame per lansare ({len(self.extra_ads) + 1})"
            )
        _require_text("headline", self.headline)
        _require_text("primary_text", self.primary_text)
        _require_https("target_url", self.target_url)
        _require_https("image_url", self.image_url)
        if not self.daily_budget.is_finite() or self.daily_budget <= 0:
            raise ValueError(f"bugetul zilnic trebuie sa fie pozitiv ({self.daily_budget})")
        if not _DIGITS.match(self.pixel_id):
            raise ValueError(f"pixel_id trebuie sa fie numeric ('{self.pixel_id}')")
        if not _DIGITS.match(self.page_id):
            raise ValueError(f"page_id trebuie sa fie numeric ('{self.page_id}')")
        if self.custom_event_type not in STANDARD_EVENT_TYPES:
            raise ValueError(
                f"eveniment necunoscut '{self.custom_event_type}' - "
                f"accepta: {', '.join(sorted(STANDARD_EVENT_TYPES))}"
            )
        if self.custom_event_type not in CAPI_EVENT_TYPES:
            raise ValueError(
                f"campania nu poate optimiza pe '{self.custom_event_type}': serverul trimite "
                f"prin CAPI doar {', '.join(sorted(CAPI_EVENT_TYPES))}, iar fara CAPI Meta ar "
                "invata din conversii necalificate"
            )
        if self.call_to_action not in CALL_TO_ACTION_TYPES:
            raise ValueError(
                f"call-to-action necunoscut '{self.call_to_action}' - "
                f"accepta: {', '.join(sorted(CALL_TO_ACTION_TYPES))}"
            )
        if not _COUNTRY.match(self.country):
            raise ValueError(f"tara trebuie sa fie un cod ISO de 2 litere ('{self.country}')")
        local = (self.latitude, self.longitude, self.radius_km)
        if any(value is not None for value in local):
            if any(value is None for value in local):
                raise ValueError("zona locala cere latitudine, longitudine si raza, toate trei")
            assert self.latitude is not None and self.longitude is not None
            assert self.radius_km is not None
            if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
                raise ValueError("coordonatele zonei nu sunt valide")
            if not (1 <= self.radius_km <= 80):
                raise ValueError(f"raza trebuie sa fie intre 1 si 80 km ({self.radius_km})")

    def to_payload(self) -> dict[str, Any]:
        """Forma JSON salvata in ``ProposedChange.after``.

        Bugetul pleaca SIR, nu float: ``25.10`` ca float ar deveni
        ``25.099999999999998`` dupa un drum prin JSON.
        """
        extended = bool(
            self.extra_ads or self.video_url or self.concept_template or self.carousel
        )
        payload = {
            "launch_spec_version": (
                LAUNCH_SPEC_VERSION_MULTI_AD if extended else LAUNCH_SPEC_VERSION
            ),
            "campaign_name": self.campaign_name,
            "objective": self.objective.value,
            "daily_budget": str(self.daily_budget),
            "pixel_id": self.pixel_id,
            "custom_event_type": self.custom_event_type,
            "page_id": self.page_id,
            "target_url": self.target_url,
            "headline": self.headline,
            "primary_text": self.primary_text,
            "image_url": self.image_url,
            "country": self.country,
            "call_to_action": self.call_to_action,
            "location": (
                {
                    "latitude": str(self.latitude),
                    "longitude": str(self.longitude),
                    "radius_km": str(self.radius_km),
                }
                if self.radius_km is not None
                else None
            ),
        }
        if self.video_url:
            payload["video_url"] = self.video_url
        if self.concept_template:
            payload["concept_template"] = self.concept_template
        if self.carousel:
            payload["carousel"] = [card.to_payload() for card in self.carousel]
        if self.extra_ads:
            payload["extra_ads"] = [ad.to_payload() for ad in self.extra_ads]
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> MetaLaunchSpec:
        """Reconstituie specificatia dintr-o propunere salvata.

        Raises:
            ValueError: versiune necunoscuta, camp lipsa sau invalid.
        """
        version = payload.get("launch_spec_version")
        if version not in _READABLE_SPEC_VERSIONS:
            raise ValueError(
                f"versiunea specificatiei de lansare e '{version}', asteptat "
                f"{LAUNCH_SPEC_VERSION} sau {LAUNCH_SPEC_VERSION_MULTI_AD} - propunerea a "
                "fost salvata de alta versiune a codului"
            )
        location = payload.get("location") or {}
        try:
            return cls(
                campaign_name=str(payload["campaign_name"]),
                objective=CampaignObjective(payload["objective"]),
                daily_budget=Decimal(str(payload["daily_budget"])),
                pixel_id=str(payload["pixel_id"]),
                custom_event_type=str(payload["custom_event_type"]),
                page_id=str(payload["page_id"]),
                target_url=str(payload["target_url"]),
                headline=str(payload["headline"]),
                primary_text=str(payload["primary_text"]),
                image_url=str(payload["image_url"]),
                country=str(payload["country"]),
                call_to_action=str(payload["call_to_action"]),
                latitude=Decimal(location["latitude"]) if location else None,
                longitude=Decimal(location["longitude"]) if location else None,
                radius_km=Decimal(location["radius_km"]) if location else None,
                video_url=str(payload.get("video_url", "")),
                concept_template=str(payload.get("concept_template", "")),
                carousel=tuple(
                    CarouselCard.from_payload(card) for card in payload.get("carousel") or []
                ),
                extra_ads=tuple(
                    MetaAdCreative.from_payload(ad) for ad in payload.get("extra_ads") or []
                ),
            )
        except KeyError as exc:
            raise ValueError(f"specificatia de lansare nu are campul {exc}") from exc
        except InvalidOperation as exc:
            raise ValueError(f"buget ilizibil: '{payload.get('daily_budget')}'") from exc


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """Id-urile obiectelor create in Meta, in ordinea crearii."""

    campaign_id: str
    adset_id: str
    image_hash: str
    creative_id: str
    ad_id: str
    #: Reclamele in plus (``spec.extra_ads``), in ordinea lor; gol la o lansare cu o reclama.
    extra_ad_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str]:
        created = {
            "campaign_id": self.campaign_id,
            "adset_id": self.adset_id,
            "image_hash": self.image_hash,
            "creative_id": self.creative_id,
            "ad_id": self.ad_id,
        }
        if self.extra_ad_ids:
            created["extra_ad_ids"] = ",".join(self.extra_ad_ids)
        return created


def _json(value: Any) -> str:
    """Obiectele imbricate pleaca serializate JSON intr-un corp form-encoded."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def campaign_fields(spec: MetaLaunchSpec) -> dict[str, str]:
    """``POST /act_{id}/campaigns`` - campania, fara buget (bugetul sta pe ad set)."""
    return {
        "name": spec.campaign_name,
        "objective": build_meta_campaign_payload(spec.objective)["objective"],
        "status": LAUNCH_STATUS,
        "special_ad_categories": "[]",
        # Bugetul e pe ad set, iar din v24 Meta cere atunci o decizie explicita
        # despre impartirea lui intre ad set-uri. Cu un singur ad set n-are ce
        # imparti - deci False.
        "is_adset_budget_sharing_enabled": "false",
    }


def adset_fields(
    spec: MetaLaunchSpec, *, campaign_id: str, daily_budget_minor: int
) -> dict[str, str]:
    """``POST /act_{id}/adsets`` - partea complexa a lantului.

    Args:
        daily_budget_minor: Bugetul in unitatea minima a monedei, calculat de
            apelant in momentul trimiterii (2500 = 25,00 RON).
    """
    optimization = build_meta_campaign_payload(spec.objective)["ad_set"]
    fields = {
        "name": f"{spec.campaign_name} - Ad set",
        "campaign_id": campaign_id,
        "status": LAUNCH_STATUS,
        "daily_budget": str(daily_budget_minor),
        "billing_event": "IMPRESSIONS",
        "optimization_goal": optimization["optimization_goal"],
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "destination_type": "WEBSITE",
        "promoted_object": _json(
            {"pixel_id": spec.pixel_id, "custom_event_type": spec.custom_event_type}
        ),
        # Tintire larga: tara (sau raza in jurul afacerii, la una locala), plus
        # Advantage+ audience - care largeste varsta si interesele, nu locatia. Cu
        # advantage_audience=1, Meta accepta age_min doar intre 18 si 25 si
        # fixeaza age_max la 65 - deci nu trimitem restrictii de varsta deloc.
        "targeting": _json(
            {
                "geo_locations": _geo_locations(spec),
                "targeting_automation": {"advantage_audience": 1},
            }
        ),
    }
    require_conversion_optimization(fields)
    return fields


def require_conversion_optimization(fields: dict[str, str]) -> None:
    """Ad set-ul optimizeaza pe conversia trimisa prin CAPI, sau nu pleaca la Meta.

    Raises:
        ValueError: alt ``optimization_goal`` (click-uri, vizualizari de pagina,
            afisari), pixel lipsa, sau un eveniment pe care CAPI nu-l trimite.
    """
    goal = fields.get("optimization_goal")
    if goal != CONVERSION_OPTIMIZATION_GOAL:
        raise ValueError(
            f"ad set-ul trebuie sa optimizeze pe {CONVERSION_OPTIMIZATION_GOAL}, nu pe '{goal}'"
        )
    promoted = json.loads(fields.get("promoted_object") or "{}")
    if not promoted.get("pixel_id"):
        raise ValueError("ad set-ul nu are pixelul pe care trimitem conversiile (promoted_object)")
    if promoted.get("custom_event_type") not in CAPI_EVENT_TYPES:
        raise ValueError(
            f"evenimentul '{promoted.get('custom_event_type')}' nu e trimis prin CAPI - "
            f"accepta: {', '.join(sorted(CAPI_EVENT_TYPES))}"
        )


def _geo_locations(spec: MetaLaunchSpec) -> dict[str, Any]:
    """Toata tara, sau raza in jurul afacerii (``custom_locations``, in km)."""
    if spec.radius_km is None:
        return {"countries": [spec.country]}
    return {
        "custom_locations": [
            {
                "latitude": float(spec.latitude or 0),
                "longitude": float(spec.longitude or 0),
                "radius": float(spec.radius_km),
                "distance_unit": "kilometer",
            }
        ]
    }


def video_fields(spec: MetaLaunchSpec, ad: MetaAdCreative, *, index: int = 0) -> dict[str, str]:
    """``POST /act_{id}/advideos`` - Meta descarca singura video-ul de la ``file_url``."""
    suffix = "Video" if index == 0 else f"Video {index + 1}"
    return {"name": f"{spec.campaign_name} - {suffix}", "file_url": ad.video_url}


def creative_fields(
    spec: MetaLaunchSpec,
    *,
    image_hash: str,
    ad: MetaAdCreative | None = None,
    index: int = 0,
    video_id: str | None = None,
    card_hashes: tuple[str, ...] = (),
) -> dict[str, str]:
    """``POST /act_{id}/adcreatives`` - textul, imaginea (sau video-ul) si pagina.

    Fara ``ad``, creative-ul e cel principal al specificatiei (``index`` 0). Cu
    ``video_id``, creative-ul e video: ``image_hash`` e coperta, iar link-ul sta in
    call-to-action (forma ceruta de Meta pentru ``video_data``). Cu ``card_hashes``
    (cate unul pe card), creative-ul e carusel: ``child_attachments``, ordonate de Meta
    dupa performanta (``multi_share_optimized``).
    """
    ad = ad or spec.ads[0]
    headline = ad.headline
    primary_text = ad.primary_text
    suffix = "Creative" if index == 0 else f"Creative {index + 1}"
    call_to_action = {"type": spec.call_to_action, "value": {"link": spec.target_url}}
    story: dict[str, Any] = {"page_id": spec.page_id}
    if video_id is not None:
        story["video_data"] = {
            "video_id": video_id,
            "image_hash": image_hash,
            "message": primary_text,
            "title": headline,
            "call_to_action": call_to_action,
        }
    elif ad.carousel:
        story["link_data"] = {
            "link": spec.target_url,
            "message": primary_text,
            "child_attachments": [
                {
                    "link": spec.target_url,
                    "image_hash": card_hash,
                    "name": card.headline,
                    **({"description": card.description} if card.description else {}),
                    "call_to_action": call_to_action,
                }
                for card, card_hash in zip(ad.carousel, card_hashes, strict=True)
            ],
            "multi_share_optimized": True,
            "call_to_action": call_to_action,
        }
    else:
        story["link_data"] = {
            "link": spec.target_url,
            "message": primary_text,
            "name": headline,
            "image_hash": image_hash,
            "call_to_action": call_to_action,
        }
    return {
        "name": f"{spec.campaign_name} - {suffix}",
        "object_story_spec": _json(story),
        "url_tags": AD_URL_TAGS,
    }


def ad_fields(
    spec: MetaLaunchSpec, *, adset_id: str, creative_id: str, index: int = 0
) -> dict[str, str]:
    """``POST /act_{id}/ads`` - anuntul, legat de ad set si de creative."""
    suffix = "Ad" if index == 0 else f"Ad {index + 1}"
    return {
        "name": f"{spec.campaign_name} - {suffix}",
        "adset_id": adset_id,
        "creative": _json({"creative_id": creative_id}),
        "status": LAUNCH_STATUS,
    }
