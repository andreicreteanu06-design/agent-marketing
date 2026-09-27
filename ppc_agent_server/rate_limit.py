"""Limitarea frecventei cererilor, in memoria procesului.

Doua rute au nevoie de ea acum:

- ``POST /api/v1/login`` - forta bruta pe parole. Doua limite: una larga pe IP
  (impotriva cuiva care incearca multe conturi) si una stricta pe email, care
  numara doar ESECURILE (impotriva cuiva care incearca multe parole pe acelasi
  cont, din oricate IP-uri). Un login reusit sterge esecurile acelui email.
- ``POST /api/v1/queen/chat`` - fiecare mesaj inseamna pana la sase generari pe
  modelul local (Ollama: GPU/CPU-ul masinii, partajat de toti clientii), cateva
  apeluri Jev si un fir din pool-ul API-ului tinut ocupat zeci de secunde. Limita
  e per client: o rafala scurta si un plafon pe ora.

Fereastra e glisanta (se tin momentele cererilor, nu un contor resetat la fix),
deci nu exista "granita" la care cineva sa trimita dublu. Sigur pentru fire:
rutele sincrone ruleaza in pool-ul de fire al FastAPI.

Limitare cunoscuta, asumata: memoria e a procesului. Cu N workeri uvicorn,
limita efectiva devine de N ori mai mare; o limita comuna intre replici ar
cere Redis (il avem deja pentru ARQ). IP-ul vine din ``request.client`` - in
spatele unui proxy, uvicorn trebuie pornit cu ``--proxy-headers`` si
``FORWARDED_ALLOW_IPS`` (vezi ``docker-compose.yml``), altfel toti clientii ar
parea sa vina de la proxy.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from ppc_agent_server.services.ro_format import count

#: Peste atatea chei tinute in memorie, cele expirate se curata la urmatoarea cerere.
_SWEEP_ABOVE_KEYS = 10_000


class RateLimiter:
    """``limit`` cereri pe ``window_seconds``, per cheie, cu fereastra glisanta."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> float | None:
        """Secundele pana la urmatoarea cerere permisa, sau ``None`` daca e permisa acum."""
        now = self._clock()
        with self._lock:
            hits = self._live(key, now)
            if len(hits) < self.limit:
                return None
            return hits[0] + self.window_seconds - now

    def hit(self, key: str) -> float | None:
        """Inregistreaza o cerere. ``None`` daca a fost permisa, altfel ``retry_after``."""
        now = self._clock()
        with self._lock:
            if len(self._hits) > _SWEEP_ABOVE_KEYS:
                horizon = now - self.window_seconds
                stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= horizon]
                for old_key in stale:
                    del self._hits[old_key]
            hits = self._live(key, now)
            if len(hits) >= self.limit:
                return hits[0] + self.window_seconds - now
            hits.append(now)
            return None

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Oricate conturi, de pe acelasi IP. Larga: mai multi oameni pot iesi pe acelasi IP.
LOGIN_BY_IP = RateLimiter(limit=30, window_seconds=60)
#: Parole gresite pe acelasi email, de oriunde. Stricta: asta opreste forta bruta.
LOGIN_FAILURES_BY_EMAIL = RateLimiter(limit=5, window_seconds=15 * 60)
#: Mesaje catre Regina: rafala scurta...
CHAT_BURST = RateLimiter(limit=6, window_seconds=60)
#: ...si plafonul pe ora (modelul local e partajat, Jev se plateste pe token).
CHAT_HOURLY = RateLimiter(limit=60, window_seconds=60 * 60)

ALL_LIMITERS = (LOGIN_BY_IP, LOGIN_FAILURES_BY_EMAIL, CHAT_BURST, CHAT_HOURLY)


def reset_rate_limits() -> None:
    """Goleste toate limitele - pentru teste."""
    for limiter in ALL_LIMITERS:
        limiter.reset()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "necunoscut"


def too_many_requests(retry_after: float, message: str) -> HTTPException:
    """429 cu ``Retry-After`` (secunde, rotunjit in sus) si un mesaj pentru om."""
    seconds = max(1, math.ceil(retry_after))
    return HTTPException(
        status_code=429,
        detail=f"{message} Încearcă din nou peste {_wait(seconds)}.",
        headers={"Retry-After": str(seconds)},
    )


def _wait(seconds: int) -> str:
    if seconds < 60:
        return count(seconds, "secunde", "secundă")
    minutes = math.ceil(seconds / 60)
    return "un minut" if minutes == 1 else count(minutes, "minute")
