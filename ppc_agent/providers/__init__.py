"""Adaptoare catre sistemele externe de date.

Fiecare furnizor are:

- o interfata abstracta in :mod:`ppc_agent.providers.base`,
- o implementare ``mock`` deterministica (:mod:`ppc_agent.providers.mock`),
- un stub ``live`` (:mod:`ppc_agent.providers.live`).

Selectia intre ``mock`` si ``live`` se face prin
:class:`ppc_agent.providers.factory.ProviderFactory`, pe baza configuratiei.
"""

from __future__ import annotations
