"""Comun ambelor suite (``tests/`` si ``tests_server/``): niciun test pe un cont real.

``Settings()`` citeste ``.env``-ul masinii. Cu pilotul pornit acolo (``PPC_PROVIDER_MODE=live``
si tokenul Meta real), orice test ar citi - sau, printr-o greseala, ar scrie - contul
real de reclame. Variabilele de mediu au prioritate fata de ``.env``: testele pornesc
mereu din ``mock``, fara chei; cele care vor drumul live il cer explicit
(``monkeypatch.setenv``), cu un token fictiv si cererile interceptate.
"""

from __future__ import annotations

import pytest

_NO_REAL_ACCOUNTS = {
    "PPC_PROVIDER_MODE": "mock",
    "PPC_META_ACCESS_TOKEN": "",
    "PPC_META_AD_ACCOUNT_ID": "",
    "PPC_TIKTOK_ACCESS_TOKEN": "",
    "PPC_GOOGLE_ADS_DEVELOPER_TOKEN": "",
    "PPC_GOOGLE_ADS_REFRESH_TOKEN": "",
    "PPC_GOOGLE_OAUTH_REFRESH_TOKEN": "",
    "META_CAPI_TEST_EVENT_CODE": "",
}


@pytest.fixture(autouse=True)
def _no_real_ad_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _NO_REAL_ACCOUNTS.items():
        monkeypatch.setenv(name, value)
