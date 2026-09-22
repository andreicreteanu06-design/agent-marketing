"""Registrul tipurilor de probleme gasite de audit.

Portare 1:1 a ``src/shared/audit-issues.ts`` din ``every-app/open-seo``:
aceleasi id-uri (kebab-case, engleza), aceleasi severitati. Doua adaugiri fata
de original, ambele deliberate:

- ``pillar`` - "seo" sau "geo". Originalul are un singur scor de sanatate; acest
  produs vinde doua (SEO clasic + GEO), asa ca fiecare problema declara pe care
  dintre ele il apasa. Vezi ``scoring.py``.
- blocul GEO de la final - probleme specifice motoarelor generative (ChatGPT,
  AI Overviews, Perplexity), inexistente in original, dar masurate cu aceeasi
  disciplina: fiecare are un prag explicit in ``geo_reporters.py``.

Textele sunt in romana (produsul e romanesc); id-urile NU se traduc - sunt
cheia comuna intre backend, API si UI, exact ca in original.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

IssueSeverity = Literal["critical", "warning", "info"]
IssuePillar = Literal["seo", "geo"]


@dataclass(frozen=True, slots=True)
class AuditIssueDescriptor:
    """Descrierea stabila a unui tip de problema (nu o instanta gasita pe o pagina)."""

    severity: IssueSeverity
    pillar: IssuePillar
    title: str
    explanation: str
    how_to_fix: str


AUDIT_ISSUE_TYPES: Final[dict[str, AuditIssueDescriptor]] = {
    # ---- Crawl / disponibilitate ------------------------------------------
    "blocked-page": AuditIssueDescriptor(
        severity="critical",
        pillar="seo",
        title="Crawler-ul a fost blocat",
        explanation=(
            "Site-ul a raspuns cu o provocare anti-bot sau cu un refuz de acces (ex. un "
            "challenge Cloudflare sau un 403) in loc de pagina. O raportam cinstit, in loc "
            "sa ne prefacem ca pagina e stricata - dar inseamna ca pagina asta nu a putut "
            "fi auditata, iar alte crawler-e (inclusiv cele ale motoarelor de cautare) pot "
            "intampina aceeasi frictiune."
        ),
        how_to_fix=(
            "Daca site-ul e al tau, pune user-agent-ul SeoGeoAgent-Audit pe lista alba in "
            "regulile WAF/anti-bot (pe Cloudflare: o regula WAF care sare peste protectia "
            "anti-bot cand user-agent-ul contine SeoGeoAgent-Audit). Apoi ruleaza auditul din nou."
        ),
    ),
    "rate-limited-page": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Limitare de rata (429)",
        explanation=(
            "Serverul a raspuns 429 Too Many Requests, deci pagina nu a putut fi auditata. "
            "Crawler-ul asteapta si reincearca doar daca racirea ceruta de site incape in "
            "bugetul de timp al auditului."
        ),
        how_to_fix=(
            "Creste limita de rata pentru crawler-e sau pune SeoGeoAgent-Audit pe lista alba "
            "in regulile de rate-limiting. Apoi ruleaza auditul din nou, eventual cu mai "
            "putine pagini."
        ),
    ),
    "crawl-rate-limited": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Crawl oprit devreme: limitare de rata",
        explanation=(
            "Site-ul a cerut crawler-ului sa astepte mai mult decat permitea bugetul de timp "
            "al auditului. Am oprit cererile. Raportul e incomplet: URL-urile neaccesate NU "
            "sunt trecute ca rupte sau limitate."
        ),
        how_to_fix=(
            "Ruleaza auditul din nou dupa ce limita de rata a site-ului se reseteaza, sau "
            "cere administratorului site-ului sa permita crawler-ul."
        ),
    ),
    "server-error": AuditIssueDescriptor(
        severity="critical",
        pillar="seo",
        title="Eroare de server (5xx)",
        explanation=(
            "Pagina a raspuns cu o eroare 5xx. Motoarele de cautare care vad repetat erori "
            "de server crawleaza site-ul mai rar si pot scoate pagina din index."
        ),
        how_to_fix=(
            "Verifica log-urile serverului pentru acest URL si repara cauza. Daca pagina nu "
            "mai exista, raspunde 404/410 sau redirecteaz-o catre o pagina relevanta, in loc "
            "sa dea eroare."
        ),
    ),
    "broken-internal-link": AuditIssueDescriptor(
        severity="critical",
        pillar="seo",
        title="Link intern rupt",
        explanation=(
            "Pagina asta trimite catre un URL intern care raspunde cu eroare (4xx/5xx). "
            "Linkurile rupte risipesc bugetul de crawl, pierd autoritate de link si enerveaza "
            "utilizatorii - sunt printre cele mai frecvente si mai daunatoare probleme "
            "tehnice de SEO."
        ),
        how_to_fix=(
            "Corecteaza linkul catre URL-ul viu sau scoate-l. Daca pagina tinta a fost "
            "mutata, linkuieste direct noul URL, nu te baza pe un redirect."
        ),
    ),
    "missing-title": AuditIssueDescriptor(
        severity="critical",
        pillar="seo",
        title="Lipseste tagul title",
        explanation=(
            "Pagina nu are <title>. Titlul e cel mai puternic semnal de relevanta on-page si "
            "titlul afisat in rezultatele cautarii; fara el, motoarele isi genereaza singure "
            "unul, de obicei prost."
        ),
        how_to_fix=(
            "Adauga un <title> unic si descriptiv, de aproximativ 50-60 de caractere, care "
            "contine subiectul principal al paginii."
        ),
    ),
    "broken-page": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Pagina raspunde cu eroare (4xx)",
        explanation=(
            "URL-ul crawlat a raspuns cu o eroare de client (ex. 404). Daca e referit din "
            "sitemap sau din alte pagini, crawler-ele continua sa consume cereri pe el."
        ),
        how_to_fix=(
            "Daca pagina ar trebui sa existe, repar-o. Daca a disparut intentionat, scoate-o "
            "din sitemap si din linkurile interne si ia in calcul un redirect 301 catre cea "
            "mai apropiata pagina vie."
        ),
    ),
    "duplicate-title": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Titlu duplicat",
        explanation=(
            "Mai multe pagini au acelasi tag title. Motoarele folosesc titlurile ca sa "
            "diferentieze paginile; duplicatele le pun sa concureze intre ele si scad rata "
            "de click."
        ),
        how_to_fix=(
            "Scrie un titlu unic pentru fiecare pagina, care descrie continutul ei specific. "
            "Pentru pagini generate din sablon, include in sablon atributul care le "
            "diferentiaza (nume, categorie, oras)."
        ),
    ),
    "duplicate-meta-description": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Meta description duplicat",
        explanation=(
            "Mai multe pagini au aceeasi meta description, deci rezultatele cautarii arata "
            "fragmente identice si utilizatorul nu poate distinge paginile intre ele."
        ),
        how_to_fix=(
            "Scrie o meta description unica pe pagina, sau sterge-o complet pe cea duplicata "
            "- motoarele vor genera un fragment din continutul paginii, ceea ce bate un "
            "duplicat gresit."
        ),
    ),
    "duplicate-content": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Continut duplicat",
        explanation=(
            "Doua sau mai multe URL-uri servesc exact acelasi text vizibil. Motoarele aleg o "
            "singura versiune pe care o indexeaza si ignora restul, iar semnalele de ranking "
            "se imprastie intre duplicate."
        ),
        how_to_fix=(
            "Consolideaza: alege URL-ul canonic, adauga rel=canonical din celelalte si "
            "redirecteaza 301 unde se poate (cauze frecvente: variante cu/fara slash final, "
            "parametri in URL, http/https sau www)."
        ),
    ),
    "missing-meta-description": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Lipseste meta description",
        explanation=(
            "Pagina nu are meta description. Motoarele vor compune singure un fragment din "
            "textul paginii, de obicei mai putin convingator, ceea ce scade rata de click."
        ),
        how_to_fix=(
            "Adauga o meta description de aproximativ 70-160 de caractere, care rezuma pagina "
            "si da un motiv de click."
        ),
    ),
    "missing-h1": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Lipseste titlul H1",
        explanation=(
            "Pagina nu are H1. H1-ul spune utilizatorilor si motoarelor despre ce e pagina; "
            "paginile fara el au de obicei o claritate tematica mai slaba."
        ),
        how_to_fix=(
            "Adauga un singur H1 care enunta subiectul principal al paginii, consecvent cu "
            "tagul title."
        ),
    ),
    "multiple-h1": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Mai multe titluri H1",
        explanation=(
            "Pagina are mai mult de un H1, ceea ce dilueaza semnalul de subiect principal si "
            "indica de obicei o greseala de sablon (ex. si logoul, si titlul sunt marcate ca H1)."
        ),
        how_to_fix=(
            "Pastreaza un singur H1 pentru titlul principal si coboara-le pe celelalte la "
            "H2/H3 (sau la elemente fara stil de titlu, pentru lucruri care nu sunt titluri, "
            "cum e logoul)."
        ),
    ),
    "redirect-chain": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Lant de redirecturi",
        explanation=(
            "Ca sa ajungi la pagina finala trebuie doua sau mai multe redirecturi "
            "consecutive. Fiecare salt adauga latenta, pierde autoritate de link si consuma "
            "buget de crawl; lanturile lungi pot sa nu fie urmarite deloc."
        ),
        how_to_fix=(
            "Fa ca primul URL (si toate linkurile interne) sa trimita direct catre destinatia "
            "finala, ca sa existe cel mult un redirect."
        ),
    ),
    "redirect-loop": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Bucla de redirecturi",
        explanation=(
            "Redirectul asta ajunge inapoi la el insusi, deci URL-ul nu se rezolva niciodata. "
            "Browserele si crawler-ele renunta cu eroare."
        ),
        how_to_fix=(
            "Urmareste regulile de redirect pentru acest URL si rupe ciclul, ca lantul sa se "
            "termine intr-o pagina reala cu status 200."
        ),
    ),
    "canonical-conflict": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Semnale canonice contradictorii",
        explanation=(
            "Pagina declara URL-uri canonice diferite in HTML (<link rel=canonical>) si in "
            "antetul HTTP Link. Cand semnalele se contrazic, motoarele le ignora pe amandoua "
            "si isi aleg singure canonicul."
        ),
        how_to_fix=(
            "Alege un singur URL canonic si declara-l intr-un singur loc (de obicei in "
            "<head>); scoate sau aliniaza cealalta declaratie."
        ),
    ),
    "thin-content": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Continut subtire",
        explanation=(
            "Pagina are foarte putin text vizibil. Paginile subtiri rareori se claseaza, pot "
            "trage in jos evaluarea de calitate a intregului site si (daca site-ul se "
            "randeaza in browser) pot indica un continut invizibil pentru crawler-ele care "
            "citesc doar HTML."
        ),
        how_to_fix=(
            "Ori extinde pagina cu continut real util, ori pune-o pe noindex, ori "
            "consolideaz-o intr-o pagina mai puternica. Daca textul exista, dar e randat din "
            "JavaScript, asigura-te ca e livrat si in HTML-ul de la server."
        ),
    ),
    "images-missing-alt": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Imagini fara text alternativ",
        explanation=(
            "Una sau mai multe imagini din pagina nu au atributul alt. Textul alternativ e o "
            "cerinta de accesibilitate si principalul mod in care motoarele inteleg imaginile."
        ),
        how_to_fix=(
            "Adauga text alt descriptiv imaginilor cu inteles; foloseste alt gol (alt=\"\") "
            "doar pentru cele pur decorative."
        ),
    ),
    "orphan-page": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Pagina orfana",
        explanation=(
            "Nicio pagina crawlata nu trimite catre acest URL - a fost descoperit doar din "
            "sitemap. Paginile fara linkuri interne primesc putina atentie la crawl si nicio "
            "autoritate interna, iar utilizatorii nu ajung la ele navigand."
        ),
        how_to_fix=(
            "Linkuieste pagina din pagini relevante (navigatie, continut inrudit, "
            "pagini-hub), sau scoate-o din sitemap daca nu ar trebui indexata."
        ),
    ),
    "no-outgoing-links": AuditIssueDescriptor(
        severity="warning",
        pillar="seo",
        title="Pagina nu are niciun link catre alta pagina",
        explanation=(
            "Pagina nu contine niciun link - e o fundatura. Autoritatea care intra in ea se "
            "opreste acolo, crawler-ele nu au unde sa mearga mai departe, iar utilizatorii "
            "trebuie sa dea Back."
        ),
        how_to_fix=(
            "Adauga linkuri catre pagini inrudite, categoria parinte sau pagina principala. "
            "Daca navigatia e randata din JavaScript, asigura-te ca exista si in HTML-ul de "
            "la server."
        ),
    ),
    "title-too-long": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Titlu prea lung",
        explanation=(
            "Titlul depaseste ~60 de caractere, deci rezultatele cautarii il vor taia, posibil "
            "la mijlocul unei expresii."
        ),
        how_to_fix=(
            "Scurteaza titlul la aproximativ 50-60 de caractere, cu cuvintele importante la "
            "inceput."
        ),
    ),
    "title-too-short": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Titlu prea scurt",
        explanation=(
            "Titlul are sub ~10 caractere, de obicei prea generic ca sa descrie pagina sau sa "
            "atraga clickuri."
        ),
        how_to_fix=(
            "Extinde titlul intr-o expresie descriptiva (aproximativ 30-60 de caractere) care "
            "spune ce ofera pagina."
        ),
    ),
    "meta-description-too-long": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Meta description prea lunga",
        explanation=(
            "Meta description depaseste ~160 de caractere, deci motoarele vor taia fragmentul "
            "afisat."
        ),
        how_to_fix=(
            "Taie descrierea la aproximativ 70-160 de caractere, pastrand mesajul central si "
            "indemnul la actiune."
        ),
    ),
    "meta-description-too-short": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Meta description prea scurta",
        explanation=(
            "Meta description are sub ~70 de caractere. Descrierile scurte risipesc spatiul pe "
            "care ti-l da rezultatul cautarii, iar motoarele le ignora des in favoarea unui "
            "text luat din pagina."
        ),
        how_to_fix=(
            "Extinde descrierea la aproximativ 70-160 de caractere care rezuma pagina si dau "
            "un motiv de click."
        ),
    ),
    "heading-order-skip": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Nivelurile de titluri sar",
        explanation=(
            "Ierarhia titlurilor sare peste niveluri (ex. un H4 direct dupa un H2). Asta "
            "slabeste structura documentului pentru tehnologiile asistive si pentru parsarea "
            "continutului."
        ),
        how_to_fix=(
            "Ajusteaza nivelurile ca sa coboare cate un pas (H1 -> H2 -> H3), fara sa sara."
        ),
    ),
    "slow-response": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Raspuns lent al serverului",
        explanation=(
            "Raspunsul HTML a durat peste 1,5 secunde. Un time-to-first-byte lent trage in jos "
            "toate metricile de performanta care vin dupa el si scade rata de crawl pe "
            "site-urile mari."
        ),
        how_to_fix=(
            "Investigheaza timpul de server/baza de date si cache-ul pentru aceasta ruta; "
            "servirea unui HTML din cache sau generat static rezolva de obicei problema."
        ),
    ),
    "noindex-page": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Pagina e pe noindex",
        explanation=(
            "Pagina cere motoarelor sa nu o indexeze (prin meta robots sau antetul "
            "X-Robots-Tag). De multe ori e intentionat - asta e o informare, nu o eroare."
        ),
        how_to_fix=(
            "Daca pagina ar trebui sa se claseze, scoate directiva noindex. Daca e intentionat "
            "(admin, pagini de multumire, filtre), nu e nimic de facut."
        ),
    ),
    "canonicalized-page": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Canonicalizata catre alt URL",
        explanation=(
            "Pagina declara un alt URL drept canonic, spunand motoarelor sa indexeze acel URL "
            "in locul ei. E in regula cand e intentionat (pagini cu parametri, continut "
            "sindicalizat) - e o problema daca pagina asta trebuia sa se claseze."
        ),
        how_to_fix=(
            "Daca pagina trebuie sa se claseze pe cont propriu, seteaza-i canonicul catre ea "
            "insasi. Altfel nu e nimic de facut."
        ),
    ),
    "deep-page": AuditIssueDescriptor(
        severity="info",
        pillar="seo",
        title="Pagina e adanc in structura site-ului",
        explanation=(
            "Pagina e la 5+ clickuri de pagina principala. Paginile adanci sunt crawlate mai "
            "rar si primesc mai putina autoritate interna."
        ),
        how_to_fix=(
            "Adauga linkuri din pagini de nivel superior (hub-uri, categorii, navigatie), ca "
            "sa scurtezi drumul pana la ea."
        ),
    ),
    # ---- GEO: citabilitate in motoare generative --------------------------
    # Adaugire fata de open-seo (care masoara vizibilitatea AI din AFARA
    # site-ului, prin DataForSEO). Aici masuram exact partea pe care o
    # controleaza site-ul si care e verificabila din crawl, cu praguri
    # explicite in geo_reporters.py.
    "ai-crawler-blocked": AuditIssueDescriptor(
        severity="critical",
        pillar="geo",
        title="Crawler-ele AI sunt blocate din robots.txt",
        explanation=(
            "robots.txt interzice explicit unul sau mai multe crawler-e care alimenteaza "
            "raspunsurile generative (GPTBot pentru ChatGPT, ClaudeBot, PerplexityBot, "
            "Google-Extended pentru AI Overviews). Ce nu poate fi citit nu poate fi citat: "
            "site-ul e invizibil in acele raspunsuri, indiferent cat de bun e continutul."
        ),
        how_to_fix=(
            "Scoate regulile Disallow pentru acesti agenti din robots.txt (sau inlocuieste-le "
            "cu Allow: /), daca vrei sa fii citat. Daca blocarea e intentionata, ignora "
            "aceasta problema - dar atunci nu astepta vizibilitate in ChatGPT sau AI Overviews."
        ),
    ),
    "content-requires-javascript": AuditIssueDescriptor(
        severity="critical",
        pillar="geo",
        title="Continutul apare doar dupa rularea JavaScript",
        explanation=(
            "HTML-ul livrat de server e mare, dar aproape fara text vizibil - semnul clasic al "
            "unei pagini randate in browser. Spre deosebire de Googlebot, crawler-ele AI "
            "(GPTBot, ClaudeBot, PerplexityBot) NU executa JavaScript: ele vad exact pagina "
            "goala pe care am vazut-o si noi."
        ),
        how_to_fix=(
            "Livreaza continutul in HTML-ul de la server (SSR, generare statica sau "
            "pre-randare). In Next.js: muta continutul din componente client in Server "
            "Components, sau foloseste generare statica pentru rutele publice."
        ),
    ),
    "missing-structured-data": AuditIssueDescriptor(
        severity="warning",
        pillar="geo",
        title="Pagina nu are date structurate (JSON-LD)",
        explanation=(
            "Pagina nu contine niciun script application/ld+json. Datele structurate sunt "
            "modul cel mai putin ambiguu de a spune unui model ce entitate descrie pagina "
            "(produs, articol, organizatie, FAQ) - fara ele, modelul ghiceste din text."
        ),
        how_to_fix=(
            "Adauga JSON-LD potrivit tipului paginii (Article, Product, FAQPage, "
            "LocalBusiness) in <head>, cu aceleasi valori ca cele vizibile in pagina."
        ),
    ),
    "missing-organization-schema": AuditIssueDescriptor(
        severity="warning",
        pillar="geo",
        title="Lipseste schema Organization pe pagina principala",
        explanation=(
            "Pagina principala nu declara entitatea care detine site-ul. Fara ea, modelele nu "
            "pot lega cu incredere continutul de un brand anume - numele tau ramane un sir de "
            "caractere, nu o entitate."
        ),
        how_to_fix=(
            "Adauga pe pagina principala un JSON-LD de tip Organization cu name, url, logo si "
            "sameAs (profilurile oficiale), plus un WebSite cu publisher care il refera."
        ),
    ),
    "low-entity-salience": AuditIssueDescriptor(
        severity="warning",
        pillar="geo",
        title="Brandul apare prea rar in textul paginii",
        explanation=(
            "Numele brandului apare de cel mult doua ori in tot textul vizibil. Modelele "
            "generative leaga un pasaj de o entitate dupa cat de des apare aceasta explicit, "
            "in context relevant - un text plin de noi si compania noastra nu poate fi "
            "atribuit nimanui la citare."
        ),
        how_to_fix=(
            "Repeta numele brandului explicit in prima propozitie a fiecarei sectiuni "
            "importante, in locul pronumelor, si mentioneaza-l langa termenii pentru care vrei "
            "sa fii citat."
        ),
    ),
    "no-answerable-headings": AuditIssueDescriptor(
        severity="info",
        pillar="geo",
        title="Niciun subtitlu formulat ca intrebare",
        explanation=(
            "Pagina nu are niciun H2/H3 formulat ca intrebare. Motoarele generative extrag "
            "raspunsuri la intrebari; o structura intrebare-raspuns face pasajul direct "
            "reutilizabil, iar o insiruire de titluri de marketing, nu."
        ),
        how_to_fix=(
            "Rescrie subtitlurile ca intrebari reale ale clientilor (Cat costa...? Cum "
            "functioneaza...?) si raspunde in primele doua propozitii de sub fiecare."
        ),
    ),
    "long-passages": AuditIssueDescriptor(
        severity="info",
        pillar="geo",
        title="Propozitii prea lungi pentru extragere",
        explanation=(
            "Propozitia medie din pagina depaseste 30 de cuvinte. Motoarele generative citeaza "
            "pasaje scurte, auto-continute; o fraza lunga, cu subordonate, nu poate fi extrasa "
            "izolat fara sa-si piarda sensul."
        ),
        how_to_fix=(
            "Sparge frazele lungi in propozitii de 15-25 de cuvinte, fiecare inteligibila si "
            "scoasa din context (fara acesta, mai sus, dupa cum am spus)."
        ),
    ),
    "missing-author-signals": AuditIssueDescriptor(
        severity="info",
        pillar="geo",
        title="Lipsesc semnalele de autor si data",
        explanation=(
            "Pagina nu declara autor sau data publicarii (nici in JSON-LD, nici in meta). "
            "Modelele prefera surse cu paternitate si prospetime verificabile - e partea din "
            "E-E-A-T pe care o poti marca tehnic."
        ),
        how_to_fix=(
            "Adauga in JSON-LD-ul paginii author (cu nume si, ideal, sameAs) si "
            "datePublished/dateModified, plus aceleasi informatii vizibile in pagina."
        ),
    ),
    "missing-llms-txt": AuditIssueDescriptor(
        severity="info",
        pillar="geo",
        title="Site-ul nu are /llms.txt",
        explanation=(
            "Nu exista /llms.txt - un fisier care indica modelelor ce pagini conteaza si cum "
            "sa le citeze. E o conventie emergenta, NU un standard: Google Search o ignora, "
            "iar adoptarea variaza. Lipsa lui nu strica nimic; prezenta lui ajuta acolo unde "
            "e citit."
        ),
        how_to_fix=(
            "Publica /llms.txt in radacina: un titlu H1 cu numele site-ului, un paragraf de "
            "rezumat si liste de linkuri markdown catre paginile importante, cu o scurta "
            "descriere fiecare."
        ),
    ),
}

ISSUE_SEVERITY_ORDER: Final[dict[str, int]] = {"critical": 0, "warning": 1, "info": 2}


def get_issue_descriptor(issue_type: str) -> AuditIssueDescriptor | None:
    """Descrierea tipului ``issue_type``, sau ``None`` daca nu e in registru."""
    return AUDIT_ISSUE_TYPES.get(issue_type)
