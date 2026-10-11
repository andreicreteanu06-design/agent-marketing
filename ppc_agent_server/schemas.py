"""Scheme Pydantic pentru request/response API.

Distincte deliberat de modelele SQLModel (tabele) din ``models.py`` — API-ul nu
expune direct structura interna a bazei de date (id-uri interne, campuri de
audit) si poate evolua independent de schema DB.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent.creative.concepts import ConceptTemplate
from ppc_agent_server.models import KeywordIntent, SerpSource
from seo_geo_agent.audit.url_policy import is_blocked_host

AdPlatform = Literal["google", "tiktok"]
McConnectPlatform = Literal["google_ads", "meta", "tiktok_ads"]
JobStatusLabel = Literal["queued", "running", "success", "failed"]


# --- Clienti gestionati ---

#: ID-ul pixelului Meta ajunge in calea URL-ului catre Graph API: doar cifre.
_PIXEL_ID = r"^\d{0,32}$"
#: ID-ul actiunii de conversie Google Ads intra in numele resursei: doar cifre.
_CONVERSION_ACTION_ID = r"^\d{0,20}$"
#: Codul pixelului TikTok si ID-ul pixelului OpenAI Ads: litere, cifre, "_" si "-".
_PIXEL_CODE = r"^[A-Za-z0-9_-]{0,64}$"


class ClientAccountCreate(BaseModel):
    """Corpul cererii ``POST /api/v1/clients``."""

    name: str
    target_domain: str = ""
    geo: str = "RO"
    language: str = "ro"
    google_ads_customer_id: str = ""
    meta_ad_account_id: str = ""
    tiktok_advertiser_id: str = ""
    meta_pixel_id: str = Field(default="", pattern=_PIXEL_ID)
    google_ads_conversion_action_id: str = Field(default="", pattern=_CONVERSION_ACTION_ID)
    tiktok_pixel_code: str = Field(default="", pattern=_PIXEL_CODE)
    chatgpt_pixel_id: str = Field(default="", pattern=_PIXEL_CODE)
    max_daily_spend: Decimal = Decimal("50.00")
    default_lead_value: Decimal = Decimal("300.00")
    objective: CampaignObjective = CampaignObjective.LEAD_GEN
    min_roas: Decimal | None = Field(default=None, gt=0)


class ClientAccountUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/clients/{id}`` - doar campurile trimise se schimba.

    Motivatie: ``default_lead_value`` (proxy-ul de valoare pentru lead-uri) e o
    estimare initiala a agentiei - fara o cale de corectare dupa ce se afla rata
    reala de inchidere a vanzarilor, orice eroare initiala ramane permanenta in
    calculele de ROAS/CPA. La fel pentru ``max_daily_spend``/``objective``, care
    se pot schimba pe parcursul relatiei cu clientul.
    """

    name: str | None = None
    target_domain: str | None = None
    geo: str | None = None
    language: str | None = None
    google_ads_customer_id: str | None = None
    meta_ad_account_id: str | None = None
    tiktok_advertiser_id: str | None = None
    meta_pixel_id: str | None = Field(default=None, pattern=_PIXEL_ID)
    google_ads_conversion_action_id: str | None = Field(
        default=None, pattern=_CONVERSION_ACTION_ID
    )
    tiktok_pixel_code: str | None = Field(default=None, pattern=_PIXEL_CODE)
    chatgpt_pixel_id: str | None = Field(default=None, pattern=_PIXEL_CODE)
    max_daily_spend: Decimal | None = Field(default=None, gt=0)
    default_lead_value: Decimal | None = Field(default=None, gt=0)
    objective: CampaignObjective | None = None
    #: Pragul de rentabilitate (ROAS minim); ``null`` revine la implicitul obiectivului.
    min_roas: Decimal | None = Field(default=None, gt=0)


class ClientAccountRead(BaseModel):
    """Randul ``ClientAccount``, forma expusa prin API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_domain: str
    geo: str
    language: str
    google_ads_customer_id: str
    meta_ad_account_id: str
    tiktok_advertiser_id: str
    meta_pixel_id: str
    google_ads_conversion_action_id: str
    tiktok_pixel_code: str
    chatgpt_pixel_id: str
    brand_name: str
    max_daily_spend: Decimal
    default_lead_value: Decimal
    objective: CampaignObjective
    min_roas: Decimal | None
    created_at: datetime


# --- Job-uri (plan / copy / creative) ---


class PlanJobRequest(BaseModel):
    client_id: int


class CopyJobRequest(BaseModel):
    client_id: int
    keyword: str
    usp: str
    trigger: str = "aida"
    platform: AdPlatform = "google"


class CreativeJobRequest(BaseModel):
    client_id: int
    keyword: str
    broll_path: str
    trigger: str = "aida"
    usp: str | None = None
    platform: AdPlatform = "google"


class JobAccepted(BaseModel):
    """Raspunsul imediat la dispecerizarea unui job — 202, nu rezultatul final."""

    task_id: str
    status: JobStatusLabel = "queued"


class JobStatusResponse(BaseModel):
    """Raspunsul ``GET /api/v1/jobs/{task_id}``."""

    task_id: str
    status: JobStatusLabel
    result: dict[str, Any] | None = None
    error: str | None = None


# --- Propuneri (poarta HITL) ---


class ProposedChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_account_id: int
    op: str
    resource: str
    resource_type: str
    projected_daily_spend: Decimal
    rationale: str
    source_module: str
    status: str
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    #: Contextul deciziei - la o lansare, brief-ul agentilor SEO/GEO si PPC
    #: (pagina de destinatie, faza de invatare, Kelly/Thompson, semnale GSC/GBP).
    before: dict[str, Any] = Field(default_factory=dict)
    #: Starea dorita - la o lansare, specificatia completa a campaniei. Omul care
    #: aproba trebuie sa vada EXACT ce se va crea, nu un rezumat.
    after: dict[str, Any] = Field(default_factory=dict)
    #: De ce a picat executia (doar la ``failed``).
    error_message: str | None = None
    #: Ce a intors platforma la aplicare - la o lansare, id-urile create.
    execution_result: dict[str, Any] | None = None


class WeeklyReportListItem(BaseModel):
    """O intrare in istoricul rapoartelor - pentru selectorul de saptamani din UI."""

    week_start: date
    week_end: date
    generated_at: datetime
    summary_source: str


class CarouselCardRequest(BaseModel):
    """Un card de carusel: imaginea si titlul de sub ea."""

    headline: str = Field(min_length=1, max_length=255)
    image_url: str = Field(min_length=9, max_length=2048)
    description: str = Field(default="", max_length=255)


class ExtraAdRequest(BaseModel):
    """O reclama in plus in acelasi ad set (post-Andromeda: diversitate de mesaj)."""

    headline: str = Field(min_length=1, max_length=255)
    primary_text: str = Field(min_length=1, max_length=2200)
    image_url: str = Field(min_length=9, max_length=2048)
    #: Argumentul reclamei (de ce ar cumpara cineva); ajuta la detectarea duplicatelor.
    angle: str = Field(default="", max_length=200)
    #: Reclama video: ``image_url`` devine coperta.
    video_url: str | None = Field(default=None, min_length=9, max_length=2048)
    #: Sablonul de concept (poveste de fondator, noi vs. ei, inainte/dupa...).
    concept_template: ConceptTemplate | None = None
    #: Carusel: 2-10 carduri (``image_url`` ramane imaginea judecata de CCO).
    carousel: list[CarouselCardRequest] = Field(default_factory=list, max_length=10)


class CampaignLaunchRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/campaigns/propose_launch``.

    Obiectivul NU e aici: se ia din ``ClientAccount.objective``, niciodata
    ghicit si niciodata suprascris per cerere - acelasi camp schimba si RAG-ul
    de copy, si logica de urmarire a conversiilor.
    """

    campaign_name: str = Field(min_length=1, max_length=200)
    #: In MONEDA CONTULUI (RON), nu in unitati minime. Conversia in bani se face
    #: abia la trimiterea catre Meta, dupa aprobare.
    daily_budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    pixel_id: str = Field(pattern=r"^\d+$")
    page_id: str = Field(pattern=r"^\d+$")
    target_url: str = Field(min_length=9, max_length=2048)
    headline: str = Field(min_length=1, max_length=255)
    primary_text: str = Field(min_length=1, max_length=2200)
    image_url: str = Field(min_length=9, max_length=2048)
    #: Implicit: evenimentul obiectivului (PURCHASE la vanzari, LEAD la lead-uri).
    custom_event_type: str | None = None
    #: Implicit: ``ClientAccount.geo``.
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    #: Implicit: SHOP_NOW la vanzari, LEARN_MORE la lead-uri.
    call_to_action: str | None = None
    #: Prima reclama ca video: ``image_url`` devine coperta.
    video_url: str | None = Field(default=None, min_length=9, max_length=2048)
    #: Implicit: sablonul cerut de CMO pentru bariera clientului.
    concept_template: ConceptTemplate | None = None
    #: Prima reclama ca carusel: 2-10 carduri.
    carousel: list[CarouselCardRequest] = Field(default_factory=list, max_length=10)
    #: Reclame in plus in acelasi ad set; prima ramane cea din campurile de mai sus.
    extra_ads: list[ExtraAdRequest] = Field(default_factory=list, max_length=5)


class ExecuteProposalRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/proposals/{id}/execute``.

    ``confirm`` implicit ``False`` — poarta HITL: fara confirmare explicita,
    nimic nu se executa (la fel ca ``execute --confirm`` in CLI).
    """

    confirm: bool = False


# --- Auth (schimb OAuth) ---


# --- Autentificare client (self-service, distinct de cheia API de agentie) ---


#: Forma minima a unei adrese de email, fara dependinta email-validator: ceva@domeniu.tld.
_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _normalize_email(value: str) -> str:
    """``Ana@X.ro `` si ``ana@x.ro`` sunt acelasi cont."""
    return value.strip().lower()


class ClientSignupRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/signup`` - creeaza ClientAccount + ClientUser.

    Lungimi maxime pe toate campurile (un robot nu trimite un nume de 10 MB, iar
    Argon2 nu primeste o parola de un megabyte). Emailul se salveaza cu litere mici.
    """

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        email = _normalize_email(value)
        if not _EMAIL_SHAPE.fullmatch(email):
            raise ValueError("Adresa de email nu e validă.")
        return email


class ClientLoginRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/login``. Emailul nu se valideaza aici: o adresa
    gresita primeste acelasi 401 ca o parola gresita."""

    email: str = Field(max_length=254)
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return _normalize_email(value)


class ClientTokenResponse(BaseModel):
    """Raspunsul la signup/login - token JWT de folosit ca ``Authorization: Bearer``."""

    access_token: str
    token_type: str = "bearer"


class ClientUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    client_account_id: int
    created_at: datetime


class ClientMeResponse(BaseModel):
    """Raspunsul ``GET /api/v1/me`` - identitatea + contul clientului autentificat.

    ``*_connected`` - DOAR daca secretul e prezent (criptat), niciodata
    valoarea - interfata poate arata "deja conectat" fara sa expuna nimic.
    """

    user: ClientUserRead
    account: ClientAccountRead
    google_ads_connected: bool
    meta_connected: bool
    tiktok_connected: bool
    chatgpt_connected: bool


class ClientCredentialsUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/me/credentials``.

    Doar campurile trimise se cripteaza si se salveaza (acelasi pattern ca
    ``ClientAccountUpdate``) - niciun camp nu e obligatoriu, clientul isi
    conecteaza conturile pe rand, pe masura ce le are.

    ``chatgpt_ads_api_key`` e cheia Ads API din OpenAI Ads (un cont de reclame per
    cheie): citirea campaniilor si mutatiile. ``chatgpt_conversions_key`` e cheia
    separata a Conversions API, cu care pleaca conversiile spre OpenAI.
    """

    google_ads_refresh_token: str | None = None
    meta_access_token: str | None = None
    tiktok_access_token: str | None = None
    chatgpt_ads_api_key: str | None = None
    chatgpt_conversions_key: str | None = None


class ClientCredentialsUpdateResponse(BaseModel):
    """Raspunsul la actualizarea de credentiale - NICIODATA valorile, nici criptate."""

    updated_fields: list[str]


_HOSTNAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")


#: Numele unui eveniment GA4/Meta: litere, cifre si "_" (ca in platforme).
_EVENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")


class SiteSettingsUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/me/site`` - site-ul clientului, din Setari.

    Doar campurile trimise se schimba; un sir gol sterge valoarea.
    """

    #: Salvat ca origine (``https://exemplu.ro``): agentul il crawleaza ca URL
    #: (vezi ``AppConfig.target_domain``), deci nu ramane doar un nume de domeniu.
    target_domain: str | None = Field(default=None, max_length=300)
    brand_name: str | None = Field(default=None, max_length=200)

    @field_validator("target_domain")
    @classmethod
    def _origin(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None if value is None else ""
        raw = value.strip()
        parts = urlsplit(raw if "://" in raw else f"https://{raw}")
        try:
            host = (parts.hostname or "").encode("idna").decode("ascii")
        except UnicodeError:
            host = ""
        if parts.scheme not in ("http", "https") or not _HOSTNAME.fullmatch(host):
            raise ValueError(
                "Domeniul nu pare valid. Scrie-l ca 'exemplu.ro' sau 'https://exemplu.ro'."
            )
        # Agentul crawleaza domeniul: o adresa interna nu are ce cauta aici. (Numele
        # care se REZOLVA intern le opreste scutul SSRF, la fiecare cerere.)
        if is_blocked_host(host):
            raise ValueError("Domeniul trebuie să fie un site public, nu o adresă internă.")
        port = f":{parts.port}" if parts.port is not None else ""
        return f"{parts.scheme}://{host}{port}"

    @field_validator("brand_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    # Contractul testului sintetic de tracking (jobs/synthetic.py). Selectorii si
    # evenimentele ajung intr-un browser: se valideaza strict, un sir gol sterge.
    journey_path: str | None = Field(default=None, max_length=300)
    journey_cta_selector: str | None = Field(default=None, max_length=200)
    journey_consent_selector: str | None = Field(default=None, max_length=200)
    ga4_expected_events: str | None = Field(default=None, max_length=200)
    meta_expected_events: str | None = Field(default=None, max_length=200)

    @field_validator("journey_path")
    @classmethod
    def _same_site_path(cls, value: str | None) -> str | None:
        # Doar o cale pe site-ul clientului: browserul nu primeste alt host de aici.
        if value is None or not value.strip():
            return None if value is None else ""
        path = value.strip()
        if not path.startswith("/") or path.startswith("//") or any(c.isspace() for c in path):
            raise ValueError("Pagina testată trebuie să fie o cale din site, ca «/contact».")
        return path

    @field_validator("journey_cta_selector", "journey_consent_selector")
    @classmethod
    def _one_line_selector(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value.splitlines()) > 1:
            raise ValueError("Selectorul trebuie să fie pe un singur rând, ca «#contact-btn».")
        return value.strip()

    @field_validator("ga4_expected_events", "meta_expected_events")
    @classmethod
    def _event_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        events = [part.strip() for part in value.split(",") if part.strip()]
        if len(events) > 5 or not all(_EVENT_NAME.fullmatch(event) for event in events):
            raise ValueError(
                "Evenimentele: cel mult 5 nume, separate prin virgulă, ca "
                "«page_view, generate_lead»."
            )
        return ", ".join(events)


# --- Integrari Google (Search Console, Analytics) ---


class IntegrationState(BaseModel):
    """Starea unei integrari: DOAR daca token-ul exista, niciodata valoarea lui."""

    connected: bool
    #: Proprietatea aleasa (``sc-domain:...``/URL la Search Console, ID numeric la GA4).
    property_id: str


class IntegrationsStatus(BaseModel):
    """Raspunsul ``GET /api/v1/integrations``."""

    #: ``False`` = serverul n-are client OAuth Google configurat, deci butoanele
    #: de conectare n-ar avea unde sa duca - interfata spune asta, nu esueaza.
    oauth_configured: bool
    gsc: IntegrationState
    ga4: IntegrationState


class IntegrationAuthUrl(BaseModel):
    """URL-ul ecranului de consimtamant Google, pe care il deschide site-ul."""

    auth_url: str


class IntegrationPropertyRead(BaseModel):
    """O proprietate din contul Google conectat, de ales dintr-o lista."""

    id: str
    label: str


class IntegrationUpdate(BaseModel):
    """Corpul cererii ``PATCH /api/v1/integrations/{gsc|ga4}``."""

    property_id: str = Field(min_length=1, max_length=300)


# --- Urmarire conversii ---


class McpKeyCreate(BaseModel):
    """Corpul cererii ``POST /api/v1/me/mcp-keys``: cui ii dai cheia."""

    name: str = Field(min_length=1, max_length=100)


class McpKeyRead(BaseModel):
    """O cheie MCP, fara cheia in clar (aceea se arata o singura data, la creare)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    revoked_at: datetime | None


class McpKeyCreated(McpKeyRead):
    """Raspunsul la creare: cheia in clar (singura data) si adresa serverului MCP."""

    key: str
    mcp_url: str


class ConversionOutcome(BaseModel):
    """Raspunsul ``POST /api/v1/tracking/conversion/{client_id}``."""

    event_id: str
    qualified: bool
    reason: str | None = None
    deduplicated: bool = False
    #: Conversia era deja primita, dar ``lead_status`` s-a schimbat (CRM): verdictul s-a refacut.
    requalified: bool = False
    #: Meta Conversions API: ``sent``/``failed`` cand s-a incercat acum, ``None``
    #: cand nu era cazul (necalificata, deja trimisa, fara pixel, mod mock).
    meta_capi: Literal["sent", "failed"] | None = None
    #: La fel, pentru Google Ads, TikTok Events API si OpenAI Ads (ChatGPT).
    google_ads: Literal["sent", "failed"] | None = None
    tiktok: Literal["sent", "failed"] | None = None
    chatgpt: Literal["sent", "failed"] | None = None


class McConnectRequest(BaseModel):
    """Corpul cererii ``POST /api/v1/auth/mcc-connect``.

    Stub deliberat (ca toti clientii ``live`` din ``ppc_agent``): niciun schimb
    OAuth real nu are loc inca — endpoint-ul valideaza forma cererii si ridica
    ``SetupRequiredError`` (-> 503) pana la integrarea reala.
    """

    platform: McConnectPlatform
    authorization_code: str


# ---------------------------------------------------------------------------
# Motorul hibrid PPC+SEO (routers/hybrid_insights.py)
# ---------------------------------------------------------------------------


class TrackedKeywordCreate(BaseModel):
    """Cererea de adaugare a unui cuvant urmarit organic."""

    keyword: str = Field(min_length=1, max_length=300)
    intent: KeywordIntent = KeywordIntent.UNKNOWN
    target_url: str = Field(
        default="",
        max_length=2048,
        description=(
            "Pagina care AR TREBUI sa ranchezeze pe acest cuvant. Cand e completata, "
            "o pozitie obtinuta de alta pagina devine semnal de canibalizare interna."
        ),
    )


class TrackedKeywordRow(BaseModel):
    """Un cuvant urmarit, cu ultima pozitie si cu ce face el in reclame.

    Campurile de pozitie si cele de plata sunt toate optionale, si lipsa lor
    inseamna lucruri DIFERITE: fara pozitie = inca nu s-a verificat; fara date
    de plata = nu s-a licitat pe el in fereastra ceruta. Un zero in locul lor
    ar sterge distinctia.
    """

    id: int
    keyword: str
    intent: KeywordIntent
    target_url: str
    is_active: bool
    latest_rank: float | None = None
    latest_rank_source: SerpSource | None = None
    latest_checked_on: datetime | None = None
    ranking_url: str = ""
    paid_clicks: int | None = None
    paid_cost: Decimal | None = None
    paid_conversions: float | None = None
    paid_cpa: Decimal | None = None


class CannibalizationItem(BaseModel):
    """Un termen pe care il detinem organic, dar pentru care platim."""

    term: str
    organic_position: float
    paid_clicks: int
    paid_cost: Decimal
    paid_conversions: float
    potential_saving: Decimal = Field(
        description=(
            "Cheltuiala pe fereastra analizata - LIMITA SUPERIOARA a economiei, nu "
            "economia garantata: o parte din click-uri nu s-ar muta pe organic."
        )
    )


class CannibalizationReport(BaseModel):
    """Raportul de canibalizare, cu pragul folosit la vedere."""

    window_days: int
    top_position_threshold: float
    total_potential_saving: Decimal
    items: list[CannibalizationItem]


class SeoOpportunityItem(BaseModel):
    """Un termen care converteste platit, dar unde organic lipsim."""

    term: str
    paid_conversions: float
    paid_cost: Decimal
    paid_cpa: Decimal | None
    roas: float
    organic_position: float | None = Field(
        default=None, description="None = nu aparem deloc in datele organice."
    )


class SeoOpportunityReport(BaseModel):
    """Raportul de oportunitati, cu pragul folosit la vedere."""

    window_days: int
    weak_position_threshold: float
    items: list[SeoOpportunityItem]


# --- Costurile si zona clientului (inaintea primei campanii) ---


class ClientEconomicsUpdate(BaseModel):
    """Corpul ``PUT /api/v1/me/economics`` (si al agentiei) - doar campurile trimise.

    Aceleasi raspunsuri ca in interviul din chat (``services/client_intake.py``); cand nu
    mai lipseste nimic, consiliul calculeaza pragurile si raza.
    """

    average_order_value: Decimal | None = Field(default=None, gt=0)
    product_cost: Decimal | None = Field(default=None, ge=0)
    shipping_cost: Decimal | None = Field(default=None, ge=0)
    payment_fee_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    return_rate_pct: Decimal | None = Field(default=None, ge=0, lt=100)
    customer_profit: Decimal | None = Field(default=None, gt=0)
    close_rate_pct: Decimal | None = Field(default=None, gt=0, le=100)
    service_area: Literal["local", "national"] | None = None
    business_address: str | None = Field(default=None, min_length=5, max_length=300)
    business_kind: Literal["zilnic", "programat", "destinatie", "livrare"] | None = None
    #: Limita clientului; raza o alege consiliul, cel mult atat. ``null`` = decide consiliul.
    max_travel_km: Decimal | None = Field(default=None, gt=0, le=80)


class ClientEconomicsRead(BaseModel):
    """Costurile, zona si ce a calculat consiliul din ele."""

    objective: CampaignObjective
    average_order_value: Decimal | None
    product_cost: Decimal | None
    shipping_cost: Decimal | None
    payment_fee_pct: Decimal | None
    return_rate_pct: Decimal | None
    customer_profit: Decimal | None
    close_rate_pct: Decimal | None
    service_area: str
    business_address: str
    business_kind: str
    location_label: str
    target_radius_km: Decimal | None
    max_travel_km: Decimal | None
    #: Completat = se pot propune campanii.
    economics_confirmed_at: datetime | None
    max_cac: Decimal | None = None
    max_cpl: Decimal | None = None
    break_even_roas: Decimal | None = None
    #: Ce intreaba consiliul acum (``None`` = nu lipseste nimic).
    next_question: str | None = None
    #: Ce a inteles consiliul: pragurile si zona, ca in chat.
    summary: str | None = None
    #: De ce raza asta (cand a fost aleasa acum).
    radius_reason: str | None = None
