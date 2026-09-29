"""Vocea de consultant senior: stratul "humanizer" din prompturile Reginei.

De unde vine - humanizer (github.com/blader/humanizer, licenta MIT)
------------------------------------------------------------------
Un skill care rescrie textul ce "suna a AI", pornind de la ghidul Wikipedia
"Signs of AI writing". Observatia lui centrala: un model alege mereu varianta
care se potriveste celor mai multi cititori, un om alege pentru UN cititor - de
aici tic-urile. Aici nu e copiat textul lui; principiile sunt reformulate in
romana, ca instructiuni de stil, pentru un director de marketing care ii
vorbeste unui antreprenor:

- **structura inaintea vocabularului** (tic-urile care supravietuiesc oricarei
  versiuni de model): contrastul "nu X, ci Y" cu un X pe care nu l-a spus
  nimeni, concluzia de un rand care repeta, introducerea regizata ("Hai sa
  vedem"), triada fortata, liniuta pusa intre orice doua idei, aforismul;
- **ritmul** (perplexitate si "burstiness"): propozitii foarte scurte, de
  doua-cinci cuvinte, intre fraze lungi, explicative; fara structuri simetrice;
  diateza activa (cine face ce); fara resturi de chatbot ("Sper ca te ajuta"),
  fara scuze si politeturi de umplutura;
- **o lista scurta de cuvinte-tic**, in echivalentele lor romanesti.

Ce NU s-a preluat: pasul de "draft + verificare" (ar dubla apelurile LLM) si
exemplele inainte/dupa - un model mic le copiaza continutul, iar o fraza
copiata ("reclama asta pierde bani") ar fi o afirmatie falsa fara nicio cifra
de prins de garda. Regula "nu adauga niciun fapt ca sa suni uman" a lui
humanizer e aici dublata de garzile deterministe (``check_cmo_message``,
``check_council_text``), care raman ultimul cuvant: stilul nu relaxeaza nimic.
:func:`ai_tells` doar MASOARA cat de bine tine modelul vocea (jurnal, teste) -
nu respinge nimic, un tic de stil nu e o halucinatie.

Vocea e :data:`CONSULTANT_VOICE` (directorul de marketing la o cafea): o poarta
singurele texte scrise de model - mesajul CMO si sinteza consiliului. Membrii
consiliului nu mai scriu cu LLM-ul (pozitiile lor sunt calculate din date), deci
nici vocile lor separate (inginerul, analistul) nu mai exista.
"""

from __future__ import annotations

import re

from ppc_agent.texttools import normalize

#: Cuvintele pe care modelele le folosesc mult mai des decat oamenii - lista din
#: humanizer (crucial, delve, landscape, pivotal, robust...), in romana: cum
#: apar in prompt si radacina dupa care le recunoaste :func:`ai_tells`.
AI_SPEAK_WORDS: tuple[tuple[str, str], ...] = (
    ("crucial", "crucial"),
    ("esențial", "esential"),
    ("tapiserie", "tapiseri"),
    ("a rezona / rezonare", "rezon"),
    ("vital", "vital"),
    ("fundamental", "fundamental"),
    ("peisaj", "peisaj"),
    ("a naviga", "navig"),
    ("aprofundare", "aprofund"),
    ("a explora", "explor"),
    ("a valorifica", "valorific"),
    ("a debloca", "deblo"),
    ("a sublinia", "sublini"),
    ("a evidenția", "evidenti"),
    ("robust", "robust"),
    ("holistic", "holistic"),
    ("sinergie", "sinergi"),
    ("dinamic", "dinamic"),
    ("inovator", "inovat"),
    ("revoluționar", "revolutionar"),
    ("călătorie", "calatori"),
    ("în era digitală", "era digitala"),
    ("în lumea de azi", "in lumea de azi"),
    ("la nivelul următor", "nivelul urmator"),
    ("potențialul maxim", "potentialul maxim"),
    ("în concluzie", "in concluzie"),
)

#: Deschideri si incheieri de chatbot - cel mai sigur semn de text generat.
CHATBOT_RESIDUE = (
    "Desigur",
    "Excelentă întrebare",
    "Hai să vedem",
    "Iată ce trebuie să știi",
    "Adevărul e că",
    "Să analizăm",
    "Este important să notăm",
    "Este important de menționat",
    "Îmi pare rău",
    "Mulțumesc pentru întrebare",
    "Sper că te ajută",
    "Spune-mi dacă mai ai întrebări",
)

#: Conectori de umplutura la inceput de fraza.
FILLER_OPENERS = ("De asemenea,", "În plus,", "Mai mult,", "Pe scurt,")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"«{value}»" for value in values)


_VOICE_HEADER = (
    "VOCEA (regulile de mai sus au prioritate; stilul nu schimbă și nu adaugă niciun fapt):\n"
)

#: Regulile anti-"AI-speak" comune tuturor vocilor: structura, conectorii, cuvintele.
_PLAIN_TEXT_RULES = (
    "- Intri direct în subiect și te oprești după ultimul fapt util. Fără "
    f"{_quoted(CHATBOT_RESIDUE)} sau alte formule de chatbot, anunțuri și scuze.\n"
    "- Nu folosi «nu doar X, ci și Y» sau «nu e vorba de X, ci de Y» când nimeni n-a spus X: "
    "spune direct Y. Fără concluzii de un rând care repetă ce ai spus deja, fără aforisme "
    "(«cheia succesului este…») și fără enumerări în trei doar ca să sune complet.\n"
    "- Fără liniuțe ca legătură între idei: alege punctul, virgula sau două puncte.\n"
    f"- Fără conectori de umplutură la început de frază: {_quoted(FILLER_OPENERS)}.\n"
    "- Cuvinte interzise, tipice textelor generate: "
    f"{', '.join(word for word, _ in AI_SPEAK_WORDS)}.\n"
    "- Fără limbaj de vânzări și fără superlative («extraordinar», «uimitor», «fantastic»)."
)

CONSULTANT_VOICE = (
    f"{_VOICE_HEADER}"
    "Scrii ca un consultant senior pentru firme, un director de marketing care îi vorbește unui "
    "antreprenor la o cafea: profesionist, direct, asertiv și empatic. Spui lucrurilor pe nume. "
    "Fără scuze și fără politețuri de umplutură: prezinți faptele și soluția direct. Empatia "
    "vine din faptul că îi înțelegi situația din date, nu din complimente sau consolări.\n"
    "- Ritm: alternează propoziții foarte scurte, percutante, de două până la cinci cuvinte, "
    "cu fraze lungi, care explică de ce. Evită structurile simetrice: fraze paralele, perechi "
    "echilibrate, aceeași lungime de mai multe ori la rând. Nu începe două fraze la rând cu "
    "același cuvânt.\n"
    "- Diateza activă: spune cine face ce («am văzut», «CFO-ul a tăiat», «reclama aduce»), "
    "nu «s-a constatat» sau «este de menționat».\n"
    f"{_PLAIN_TEXT_RULES}"
)

_AI_SPEAK = tuple((word, re.compile(rf"\b{stem}")) for word, stem in AI_SPEAK_WORDS)
_RESIDUE = tuple(
    (phrase, re.compile(rf"\b{re.escape(normalize(phrase))}\b")) for phrase in CHATBOT_RESIDUE
)
_OPENERS = tuple(
    (opener, re.compile(rf"(?:^|[.!?:]\s+){re.escape(normalize(opener))}"))
    for opener in FILLER_OPENERS
)


def ai_tells(text: str) -> list[str]:
    """Tic-urile de text generat din ``text``, in ordinea listelor de mai sus.

    Insensibil la diacritice si majuscule. Doar masoara - vezi docstring-ul modulului.
    """
    plain = normalize(text)
    return [
        label
        for label, pattern in (*_AI_SPEAK, *_RESIDUE, *_OPENERS)
        if pattern.search(plain)
    ]
