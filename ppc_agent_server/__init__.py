"""Backend B2B multi-tenant pentru agentii, peste pipeline-urile ``ppc_agent``.

Decuplat de CLI: importa functii pure din ``ppc_agent`` (nu duplica logica de
decizie/copywriting/creatie), le orchestreaza in spatele unui API FastAPI cu
persistenta relationala (SQLModel) si autentificare per-agentie (cheie API).

Submodule:

- ``settings``: configurare server (``DATABASE_URL``, ``REDIS_URL``, ...)
- ``db``: motor + sesiuni SQLModel
- ``models``: schema relationala (``Tenant``, ``ClientAccount``,
  ``ProposedChange``, ``AdQueueItem``, ``CreativeArtifact``)
- ``auth``: chei API (generare, hash, dependinta ``get_current_tenant``)
- ``app``: fabrica aplicatiei FastAPI
"""

from __future__ import annotations
