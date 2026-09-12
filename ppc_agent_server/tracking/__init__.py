"""Urmarire de conversii omnicanal: normalizare, hash PII, calificare business.

Accepta date de la platforme e-commerce (Gomag), backend-uri web proprii, si
surse offline (call tracking), le aduce la o schema unica
(:class:`~ppc_agent_server.tracking.models.StandardizedConversion`), le
califica (:mod:`~ppc_agent_server.tracking.qualification`) si le leaga de
motorul de decizie (:mod:`~ppc_agent_server.tracking.pipeline`).
"""

from __future__ import annotations
