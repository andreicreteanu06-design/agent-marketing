"""Teste pentru maparea eroare -> cod HTTP.

SetupRequiredError (503), ApprovalRequiredError (403) si SpendLimitExceeded
(409) sunt exercitate end-to-end in altă parte (test_auth_router.py,
test_proposals.py) — apar sincron in router, inainte de orice dispecerizare.
CopywriterError (422) si fallback-ul generic PpcAgentError (500) NU apar
azi pe niciun traseu HTTP live: erorile din interiorul unui job dispecerizat
sunt raportate prin starea job-ului (JobResult.error), nu ca raspuns HTTP —
comportamentul corect pentru un job async deja acceptat (202). Testate direct,
unitar, pe handler.
"""

from __future__ import annotations

import asyncio

from ppc_agent.errors import CopywriterError, DecisionError, PpcAgentError
from ppc_agent_server.app import _error_handler


def test_error_handler_maps_status_code_and_message() -> None:
    handler = _error_handler(422)
    response = asyncio.run(handler(None, CopywriterError("cuvant cheie prea lung")))  # type: ignore[arg-type]
    assert response.status_code == 422
    assert response.body == b'{"detail":"cuvant cheie prea lung"}'


def test_error_handler_generic_fallback_covers_any_ppc_agent_error() -> None:
    """PpcAgentError inregistrat ca fallback acopera si subclase nemetionate explicit
    (aici DecisionError, care nu are propriul handler)."""
    handler = _error_handler(500)
    response = asyncio.run(handler(None, DecisionError("eroare neprevazuta")))  # type: ignore[arg-type]
    assert response.status_code == 500


def test_ppc_agent_error_is_the_common_base() -> None:
    assert issubclass(CopywriterError, PpcAgentError)
    assert issubclass(DecisionError, PpcAgentError)
