"""Schema relationala a serverului: Tenant -> ClientAccount -> (ProposedChange,
AdQueueItem, CreativeArtifact).

Inlocuieste fisierele JSON locale ale CLI-ului (``proposed_changes_*.json``,
``proposed_ads_queue.json``, ``creative_output/``) cu randuri persistente,
per agentie si per cont gestionat.

DELIBERAT fara ``from __future__ import annotations`` (singurul fisier din
proiect fara el) — limitare cunoscuta SQLModel: adnotarile devin string-uri
lazy (PEP 563), iar rezolverul de relatii al SQLAlchemy nu le mai poate parsa
corect (``list["ClientAccount"]`` ajunge sa fie tratat ca text literal
``"list['ClientAccount']"`` in loc de tipul generic), ceea ce crapa la runtime
cu ``InvalidRequestError``. Referintele catre clase definite mai jos in fisier
raman ghilimele native (forward refs Python obisnuite), nu PEP 563.
"""

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Column, Numeric, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ppc_agent.campaign_objective import CampaignObjective


def _money_column() -> Column[Decimal]:
    """``Numeric(10, 2)`` explicit pe fiecare camp banesc: fara scala explicita,
    SQLModel infera un ``sa.Numeric()`` gol, iar SQLite/SQLAlchemy pot intoarce
    ``Decimal`` cu 10 zecimale in loc de 2 la citire (vazut real: "75.0000000000"
    in loc de "75.00"). ``nullable=False`` explicit — un ``sa_column`` custom
    ocoleste inferenta normala de nullability a SQLModel din adnotarea de tip.
    O functie (nu o singura instanta Column module-level) pentru ca fiecare
    coloana are nevoie de propriul ei obiect Column — SQLAlchemy nu permite
    refolosirea aceluiasi Column pe mai multe tabele."""
    return Column(Numeric(10, 2), nullable=False)


class SubscriptionStatus(enum.StrEnum):
    """SQLModel nu mapeaza ``Literal[...]`` la o coloana SQL — doar ``Enum``
    (vezi ``issubclass()`` in ``sqlmodel.main.get_sqlalchemy_type``) — de-asta
    aceste campuri de stare folosesc ``enum.StrEnum``, ca ``ProviderMode`` din
    ``ppc_agent.config`` (nu ``class X(str, enum.Enum)`` — ruff UP042)."""

    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class ChangeOp(enum.StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    PAUSE = "PAUSE"
    #: Lansarea unei campanii noi, de la zero. Distinct de CREATE (care creeaza
    #: o piesa intr-o structura existenta, ex. un cuvant cheie negativ): aici
    #: ``after`` poarta specificatia completa a campaniei, iar la aprobare se
    #: creeaza campanie + ad set + anunt, toate oprite.
    CREATE_CAMPAIGN = "CREATE_CAMPAIGN"


class ChangeStatus(enum.StrEnum):
    """Starile prin care trece o propunere.

    ``EXECUTED`` e starea de "aplicat pe platforma" - nu s-a adaugat un
    ``APPLIED`` separat, ar fi fost acelasi lucru sub alt nume si ar fi lasat
    doua stari terminale de succes, dintre care UI-ul ar trebui sa le stie pe
    amandoua. ``FAILED`` exista fiindca lipsea: pana acum o executie cazuta
    lasa propunerea pe ``pending``, adica exact ca si cum nimeni n-ar fi
    incercat-o - iar omul o reincerca la nesfarsit fara sa afle de ce pica.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class AdQueueStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Platform(enum.StrEnum):
    GOOGLE = "google"
    TIKTOK = "tiktok"


class SerpSource(enum.StrEnum):
    """De unde stim pozitia inregistrata in :class:`SerpPosition`.

    Distinctia conteaza la interpretare, nu doar la evidenta: ``GSC`` e pozitia
    MEDIE masurata de Google pe traficul real al site-ului (poate fi 4.7), in
    timp ce ``OPENSERP`` e o fotografie a SERP-ului la un moment dat, dintr-o
    locatie, deci un numar intreg. Nu se compara direct si nu se amesteca in
    acelasi grafic fara eticheta.
    """

    GSC = "gsc"
    OPENSERP = "openserp"


class KeywordIntent(enum.StrEnum):
    """Intentia din spatele unei interogari urmarite.

    Decide ce TIP de pagina raspunde interogarii: una tranzactionala cere o
    pagina de produs/serviciu, una informationala un articol. Completata de om
    sau de agent, niciodata ghicita tacit.
    """

    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"
    UNKNOWN = "unknown"


class ConversionEventType(enum.StrEnum):
    PURCHASE = "purchase"
    LEAD = "lead"
    PHONE_CALL = "phone_call"
    CONTACT = "contact"


class AdFatiguePlatform(enum.StrEnum):
    """Platforma pe care ruleaza anuntul urmarit de monitorul de oboseala.

    Distinct de :class:`Platform` (folosit de ``AdQueueItem``/``CreativeArtifact``
    pentru creatie, doar Google/TikTok azi) — aici sunt cele 3 platforme pe care
    ``ppc_agent.decision.fatigue_monitor`` le intelege, Meta inclus."""

    META = "meta"
    TIKTOK = "tiktok"
    GOOGLE = "google"


class AdLifecycleStatus(enum.StrEnum):
    NEW = "new"
    PROFITABLE = "profitable"
    FATIGUED = "fatigued"


class AdPlatform(enum.StrEnum):
    """Platformele pe care ``BaseMarketingProvider`` (ppc_agent/providers/base.py)
    le poate targeta - un al treilea enum de platforma, distinct de
    :class:`Platform` (creatie de copy, doar Google/TikTok azi) si de
    :class:`AdFatiguePlatform` (monitorul de oboseala, Google/Meta/TikTok) -
    acelasi principiu ca de ce exista deja doua: fiecare enum e scopat la
    subsistemul lui, nu exista un enum universal "toate platformele".

    ``CHATGPT`` are un provider real, dar stub (acces API limitat la
    parteneri OpenAI aprobati - vezi
    ``providers.live.LiveGenerativeEngineProvider``). ``PERPLEXITY`` e inclus
    pentru completitudine viitoare, dar NU are azi niciun produs de reclame de
    integrat - Perplexity a abandonat reclamele in februarie 2026
    (subscription-only). Niciun cont/camp de conectare Perplexity nu exista pe
    ``ClientAccount`` - ar fi o optiune UI care nu ar putea face nimic.
    """

    META = "meta"
    CHATGPT = "chatgpt"
    PERPLEXITY = "perplexity"


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Tenant(SQLModel, table=True):
    """O agentie: cont, cheie API (doar hash-ul se stocheaza), abonament."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    api_key_hash: str = Field(unique=True, index=True)
    subscription_status: SubscriptionStatus = SubscriptionStatus.TRIAL
    created_at: datetime = Field(default_factory=_now)

    client_accounts: list["ClientAccount"] = Relationship(back_populates="tenant")


class ClientAccount(SQLModel, table=True):
    """Un cont de reclame gestionat de o agentie (client-ul agentiei)."""

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    name: str
    target_domain: str = ""
    geo: str = "RO"
    language: str = "ro"

    google_ads_customer_id: str = ""
    meta_ad_account_id: str = ""
    tiktok_advertiser_id: str = ""
    # OpenAI Ads (ChatGPT) - vezi AdPlatform.CHATGPT si
    # providers.live.LiveGenerativeEngineProvider (stub: acces API limitat la
    # parteneri aprobati de OpenAI). Campul exista din azi ca sa nu ceara o a
    # doua migratie cand providerul devine real - neexpus inca in nicio ruta a
    # serverului (nimic nu-l citeste/scrie azi, la fel ca celelalte 3 pana la
    # implementarea lor).
    chatgpt_ads_account_id: str = ""

    # Secrete per-client, criptate (Fernet - vezi security.py), NICIODATA in
    # clar in DB. Gol = clientul nu si-a conectat inca acel cont; in acel caz
    # ProviderFactory cade pe Settings global din .env (comportament CLI
    # neschimbat) - vezi jobs/tasks.py::_app_config_for.
    google_ads_refresh_token_enc: str = ""
    meta_access_token_enc: str = ""
    tiktok_access_token_enc: str = ""
    chatgpt_ads_api_key_enc: str = ""
    # Search Console: token SEPARAT de cel de Google Ads, nu din neglijenta -
    # un refresh token Google e legat de scope-urile pentru care s-a dat
    # consimtamant, iar 'adwords' nu acopera 'webmasters.readonly' (vezi
    # ppc_agent/search_data/google_oauth.py).
    gsc_refresh_token_enc: str = ""
    # Proprietatea din Search Console, exact ca acolo: 'sc-domain:exemplu.ro'
    # (domeniu) sau 'https://exemplu.ro/' (prefix URL). Gol = neconectat.
    gsc_site_url: str = ""
    # Google Analytics 4 - acelasi tipar ca Search Console: token separat
    # (scope 'analytics.readonly'), criptat, plus proprietatea aleasa - ID-ul
    # ei numeric ('123456789'), NU ID-ul de masurare al fluxului ('G-...').
    ga4_refresh_token_enc: str = ""
    ga4_property_id: str = ""
    # Numele brandului, pentru verificarea GEO de entity salience din audit.
    # Gol = se deduce din domeniu (vezi seo_geo_agent/audit/geo_reporters.py).
    brand_name: str = ""
    # Contractul de tracking pentru testul sintetic (jobs/synthetic.py): pagina din
    # site, CTA-ul pe care se da click, butonul de consimtamant (gol = cele uzuale) si
    # evenimentele asteptate, separate prin virgula (gol = page_view / PageView, cand
    # platforma e conectata). Se completeaza din Setari (PATCH /api/v1/me/site).
    journey_path: str = ""
    journey_cta_selector: str = ""
    journey_consent_selector: str = ""
    ga4_expected_events: str = ""
    meta_expected_events: str = ""

    max_daily_spend: Decimal = Field(default=Decimal("50.00"), sa_column=_money_column())
    # Valoare proxy pentru conversii "lead"/"phone_call" fara valoare explicita
    # (vezi ppc_agent_server.tracking.qualification.ConversionQualifier).
    default_lead_value: Decimal = Field(default=Decimal("300.00"), sa_column=_money_column())
    # Niciodata ghicit - citit de RAG-ul de copy, payload-ul Meta si calificarea
    # conversiilor (vezi ppc_agent.campaign_objective). Implicit LEAD_GEN: pastreaza
    # comportamentul deja existent al randurilor vechi de ConversionEvent (fallback
    # pe default_lead_value pentru orice conversie fara valoare explicita).
    objective: CampaignObjective = CampaignObjective.LEAD_GEN
    created_at: datetime = Field(default_factory=_now)

    tenant: Tenant = Relationship(back_populates="client_accounts")
    proposed_changes: list["ProposedChange"] = Relationship(back_populates="client_account")
    ad_queue_items: list["AdQueueItem"] = Relationship(back_populates="client_account")
    creative_artifacts: list["CreativeArtifact"] = Relationship(back_populates="client_account")
    conversion_events: list["ConversionEvent"] = Relationship(back_populates="client_account")
    ad_performance_records: list["AdPerformanceRecord"] = Relationship(
        back_populates="client_account"
    )
    tracked_keywords: list["TrackedKeyword"] = Relationship(back_populates="client_account")
    serp_positions: list["SerpPosition"] = Relationship(back_populates="client_account")
    search_term_conversions: list["SearchTermConversion"] = Relationship(
        back_populates="client_account"
    )
    # Optional["X"] (bracket syntax), nu "X | None" (pipe) - vezi nota din
    # capul fisierului: rezolverul de nume al SQLAlchemy pentru forward refs
    # string cauta explicit sintaxa Optional[...]/List[...] cu paranteze
    # patrate (regex intern), nu recunoaste "X | None" si crapa la mapper
    # configure cu InvalidRequestError.
    client_user: Optional["ClientUser"] = Relationship(
        back_populates="client_account", sa_relationship_kwargs={"uselist": False}
    )


class ClientUser(SQLModel, table=True):
    """Login-ul unui client (autentificare self-service prin parola).

    Distinct de :class:`Tenant` (agentia, autentificata prin cheie API - vezi
    ``auth.py``) - aici e clientul FINAL al agentiei, care isi creeaza singur
    cont pe site public (``POST /api/v1/signup``) ca sa-si conecteze conturile
    de reclame. 1:1 cu :class:`ClientAccount` (``unique=True`` pe FK) - un
    client are azi un singur utilizator, nu o echipa cu roluri multiple.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", unique=True, index=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="client_user")


class ProposedChange(SQLModel, table=True):
    """Echivalentul DB al ``ppc_agent.guardrails.models.ProposedChange``.

    Aceeasi forma (``op``/``resource``/``resource_type``/``rationale``/
    ``source_module``), plus ``status`` — poarta HITL traieste in tranzitia
    ``pending`` -> ``approved``/``rejected`` -> ``executed``, nu intr-un fisier.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    op: ChangeOp
    resource: str
    resource_type: str
    before: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    projected_daily_spend: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    rationale: str
    source_module: str

    status: ChangeStatus = ChangeStatus.PENDING
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
    decided_by: str | None = None
    #: De ce a picat executia, cand ``status`` e ``FAILED``. Textul ajunge in
    #: interfata: omul trebuie sa stie daca reincercarea are sens (token expirat)
    #: sau nu (resursa nu mai exista pe platforma).
    error_message: str | None = None
    #: Ce a intors platforma cand propunerea s-a aplicat - la o lansare, id-urile
    #: obiectelor create. Separat de ``after``, care ramane exact ce s-a aprobat.
    execution_result: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    client_account: ClientAccount = Relationship(back_populates="proposed_changes")


class AdQueueItem(SQLModel, table=True):
    """Echivalentul DB al ``proposed_ads_queue.json`` — un anunt in asteptare.

    ``ad_copy`` e JSON, nu coloane fixe: schema difera intre Google (``AdCopy``,
    3 campuri) si TikTok (``TikTokAdCopy``, 6 campuri, ``text_overlay`` e lista) —
    aceeasi eterogenitate pe care ``TikTokAdCopy.as_dict()`` o trateaza deja
    (``dict[str, Any]``) in modulul copywriter.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    platform: Platform = Platform.GOOGLE
    target_keyword: str
    emotion_trigger: str
    product_usp: str
    ad_copy: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    status: AdQueueStatus = AdQueueStatus.PENDING_REVIEW
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="ad_queue_items")


class CreativeArtifact(SQLModel, table=True):
    """Urmareste o creatie generata (voce + video) — echivalentul ``creative_output/``."""

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    platform: Platform = Platform.GOOGLE
    keyword: str
    wav_path: str
    mp4_path: str
    duration_seconds: float
    manifest: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="creative_artifacts")


class ConversionEvent(SQLModel, table=True):
    """O conversie normalizata, cu PII deja hash-uit (SHA-256) - niciodata in clar.

    Pastrata pentru audit + deduplicare (``event_id`` unic per client) - NU e
    sursa de adevar pentru starea unui anunt (asta e ``AdPerformanceRecord``,
    actualizat doar cand conversia e calificata si are un ``ad_id`` cunoscut).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)

    event_id: str = Field(unique=True, index=True)
    event_type: ConversionEventType
    value: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    currency: str = "RON"
    email_sha256: str | None = None
    phone_sha256: str | None = None
    source_platform: str
    lead_status: str | None = None
    call_duration_seconds: int | None = None
    ad_id: str | None = Field(default=None, index=True)

    qualified: bool
    disqualification_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="conversion_events")


class AdPerformanceRecord(SQLModel, table=True):
    """Rollup persistat per (client, anunt) - alimenteaza direct AdPerformanceState.

    Doar campurile pe care o conversie le poate schimba legitim
    (``conversions``, ``revenue``) se actualizeaza la fiecare conversie
    CALIFICATA cu ``ad_id`` cunoscut — restul (impressions/clicks/ctr/spend si
    variantele lor de baza) raman la valoarea cu care randul a fost creat pana
    cand un proces separat de sincronizare cu platformele de reclame le
    actualizeaza; acel proces e in afara scopului acestui task (semnalat
    explicit, ca OAuth-ul real sau upload-ul de b-roll in alte module).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    ad_id: str = Field(index=True)

    platform: AdFatiguePlatform
    status: AdLifecycleStatus = AdLifecycleStatus.NEW
    launch_time: datetime

    spend: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    target_cpa: Decimal = Field(sa_column=_money_column())
    conversions: int = Field(default=0, ge=0)
    revenue: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    ctr: float = 0.0
    account_median_ctr: float = 0.0
    frequency_7d: float = 0.0
    six_second_view_rate: float = 0.0
    cpa_3d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    cpa_baseline_14d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    bad_days_last_5: int = Field(default=0, ge=0)
    ctr_3d: float = 0.0
    ctr_baseline_14d: float = 0.0
    ctr_baseline_7d: float = 0.0
    cpa_baseline_7d: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    six_second_view_rate_baseline: float = 0.0
    bad_days_last_3: int = Field(default=0, ge=0)

    updated_at: datetime = Field(default_factory=_now)

    @property
    def roas(self) -> float:
        """Return on ad spend (venit / cost); 0 daca nu exista cost (ca ArmStats.roas)."""
        return float(self.revenue / self.spend) if self.spend > 0 else 0.0

    client_account: ClientAccount = Relationship(back_populates="ad_performance_records")


class TrackedKeyword(SQLModel, table=True):
    """Un cuvant cheie pe care clientul vrea sa-l urmareasca organic.

    Distinct de interogarile care apar SINGURE in Search Console: acelea sunt
    ce s-a intamplat, astea sunt ce vrem sa se intample. Un cuvant urmarit
    poate sa nu apara niciodata in GSC (nu ranchezi inca) - exact de aceea
    exista verificarea externa de SERP (vezi ``SerpSource.OPENSERP``).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    keyword: str = Field(index=True)
    intent: KeywordIntent = KeywordIntent.UNKNOWN
    #: Pagina care AR TREBUI sa ranchezeze pe acest cuvant. Gol = nedecis inca.
    #: Cand e completata, o pozitie buna obtinuta de ALTA pagina e semnal de
    #: canibalizare interna, nu de succes.
    target_url: str = ""
    #: Fals = pastram istoricul, dar nu mai consumam credite pe el.
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="tracked_keywords")


class SerpPosition(SQLModel, table=True):
    """Unde statea un domeniu pe o interogare, la o data anume.

    Tabela de fapte a partii organice: un rand per (zi, interogare, domeniu,
    sursa). ``domain`` exista ca sa putem stoca si pozitiile CONCURENTILOR cu
    aceeasi forma - nu doar pe ale noastre.

    ``rank`` e nullable INTENTIONAT si inseamna "am verificat si nu apare in
    primele rezultate citite". Un rand lipsa inseamna altceva ("n-am verificat
    in ziua aia"), iar confuzia dintre cele doua ar strica orice grafic de
    evolutie.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    checked_on: datetime = Field(index=True)
    keyword: str = Field(index=True)
    domain: str = Field(index=True)
    source: SerpSource
    rank: float | None = None
    #: Pagina care a ranchezat (utila ca sa vezi daca e cea intentionata).
    page_url: str = ""
    #: Doar pentru randurile din Search Console - o citire de SERP nu le stie.
    clicks: int | None = None
    impressions: int | None = None
    ctr: float | None = None
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="serp_positions")


class SearchTermConversion(SQLModel, table=True):
    """Ce a facut o interogare REALA in contul de reclame, intr-o zi.

    Sursa: raportul de termeni de cautare din Google Ads - interogarile pe care
    le-au tastat oamenii, nu cuvintele cheie licitate si nu volume estimate de
    nimeni. Asta e partea care, imbinata cu :class:`SerpPosition`, produce
    analizele din ``ppc_agent/search_data/insights.py``.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    day: datetime = Field(index=True)
    search_term: str = Field(index=True)
    #: Cuvantul cheie licitat pe care l-a declansat interogarea (poate diferi
    #: mult de ea la potrivire larga) - util ca sa stii ce sa pui pe pauza.
    matched_keyword: str = ""
    clicks: int = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    cost: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    #: Zecimal, nu intreg: Google raporteaza conversii fractionate (atribuire
    #: pe mai multe canale imparte o conversie intre ele).
    conversions: float = Field(default=0.0, ge=0)
    conversions_value: Decimal = Field(default=Decimal("0"), sa_column=_money_column())
    created_at: datetime = Field(default_factory=_now)

    client_account: ClientAccount = Relationship(back_populates="search_term_conversions")


class SiteSpeedSample(SQLModel, table=True):
    """O masuratoare PageSpeed Insights a site-ului unui client (strategia mobil).

    Scrisa noaptea de ``jobs/tasks.py::run_speed_check_job``, cu masuratoarea
    agentului SEO/GEO (``seo_geo_agent.external_data.fetch_pagespeed_insights``);
    citita de Tehnician (``services/technician.py``), care judeca viteza pe
    mobil dupa pragurile Core Web Vitals. Istoric, nu suprascriere: se vede si
    de cand a inceput site-ul sa se incarce greu. Un camp ``None`` = PageSpeed
    nu a raportat metrica - nu se completeaza cu nimic.
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    url: str
    strategy: str = "mobile"
    #: Scorul de performanta Lighthouse, 0-100.
    performance_score: int | None = None
    #: Largest Contentful Paint, in milisecunde.
    lcp_ms: int | None = None
    #: Cumulative Layout Shift (CLS, fara unitate). Nu ``cls``: numele e rezervat
    #: de constructorul SQLModel (``__new__(cls, ...)``).
    layout_shift: float | None = None
    #: Total Blocking Time, in milisecunde (proxy-ul de laborator pentru INP).
    tbt_ms: int | None = None
    #: Cate rulari PageSpeed reusite dau mediana de mai sus (se cer 3).
    runs: int = 1
    #: Date de teren CrUX (utilizatori reali, percentila 75), cand Google le are.
    field_lcp_ms: int | None = None
    field_cls: float | None = None
    field_inp_ms: int | None = None
    measured_at: datetime = Field(default_factory=_now, index=True)


class TrackingEvidence(SQLModel, table=True):
    """Pachetul de dovezi al unui test sintetic de tracking (Playwright, in worker).

    Scris de ``jobs/synthetic.py``, citit de Tehnician: veto-ul pe atribuire se
    sprijina pe transportul dovedit (cerere prinsa + eveniment din contract +
    raspuns 2xx), nu pe prezenta unui script in HTML. ``*_transport_ok`` ``None`` =
    platforma nu era in contract sau n-a putut fi judecata (consimtamant).
    """

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    url: str
    started_at: datetime = Field(default_factory=_now, index=True)
    finished_at: datetime = Field(default_factory=_now)
    navigation_status: int | None = None
    cta_selector: str = ""
    cta_ok: bool | None = None
    ga4_transport_ok: bool | None = None
    meta_transport_ok: bool | None = None
    #: Motivul exact al esecului (``tracking_contract.FailureReason``); ``None`` = trecut.
    failure_reason: str | None = None
    #: Verdictul complet si cererile prinse (platforma, eveniment, ID, status).
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class WeeklyReport(SQLModel, table=True):
    """Raportul saptamanal al unui client, salvat exact cum l-a servit API-ul.

    ``payload`` e JSON-ul ``WeeklyReportPayload``, nu coloane: forma raportului
    evolueaza (``report_version``), iar un raport vechi trebuie sa se poata
    citi exact cum a fost generat, cu cifrele de atunci. O saptamana are un
    singur raport pe client - regenerarea il inlocuieste (vezi constrangerea).
    """

    __table_args__ = (
        UniqueConstraint("client_account_id", "week_start", name="uq_weeklyreport_client_week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    client_account_id: int = Field(foreign_key="clientaccount.id", index=True)
    week_start: date = Field(index=True)
    week_end: date
    generated_at: datetime = Field(default_factory=_now)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
