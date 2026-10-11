"""Filtrare business a conversiilor brute inainte sa ajunga la motorul de decizie.

``ConversionQualifier`` aplica doua reguli, in aceasta ordine:

1. Valoare proxy - determinata de OBIECTIVUL CONTULUI, niciodata ghicit din
   tipul evenimentului: la ``LEAD_GEN``, orice conversie fara valoare explicita
   primeste valoarea implicita a contului (``ClientAccount.default_lead_value``);
   la ``SALES``, valoarea ramane cea trimisa de webhook-ul de e-commerce (ROAS
   se calculeaza din ea, fara proxy).
2. Poarta de durata a apelului - un "phone_call" sub pragul minim (sau fara
   durata cunoscuta) e descalificat: NU se numara ca o conversie reusita.
3. ``lead_status`` - backend-ul clientului poate marca un lead necalificat (ex. a
   raspuns la intrebarea de calificare din formular sub pragul de buget):
   ``unqualified``, ``disqualified`` sau ``spam``; ori il poate lasa in asteptare
   (``pending``, ``new``) pana il califica vanzarile din CRM. Fara status, lead-ul ramane
   calificat. Un status schimbat mai tarziu reface verdictul
   (``pipeline.record_conversion``).
"""

from __future__ import annotations

from pydantic import BaseModel

from ppc_agent.campaign_objective import CampaignObjective
from ppc_agent_server.tracking.models import StandardizedConversion

_MIN_CALL_DURATION_SECONDS = 60
_UNQUALIFIED_STATUSES = frozenset({"unqualified", "disqualified", "spam"})
_PENDING_STATUSES = frozenset({"pending", "new"})


class QualificationResult(BaseModel):
    """Rezultatul calificarii: conversia (cu valoarea proxy aplicata, daca a fost
    cazul) plus verdictul de calificare."""

    conversion: StandardizedConversion
    qualified: bool
    reason: str | None = None


class ConversionQualifier:
    """Aplica valorile proxy si poarta de durata a apelului unei conversii brute."""

    def __init__(self, default_lead_value: float, objective: CampaignObjective) -> None:
        """Configureaza calificatorul pentru un singur cont client.

        Args:
            default_lead_value: Valoarea proxy pentru o conversie fara valoare
                explicita, la conturi ``LEAD_GEN`` (``ClientAccount.default_lead_value``).
            objective: Obiectivul contului (``ClientAccount.objective``) - obligatoriu,
                niciodata ghicit: determina daca se aplica valoarea proxy (vezi
                :meth:`qualify`).
        """
        self._default_lead_value = default_lead_value
        self._objective = objective

    def qualify(self, conversion: StandardizedConversion) -> QualificationResult:
        """Aplica valoarea proxy (daca obiectivul contului e LEAD_GEN), apoi
        poarta de durata a apelului.

        Args:
            conversion: Conversia normalizata (deja trecuta prin adaptorul de
                sursa), inainte de orice calificare.

        Returns:
            Conversia (posibil cu valoarea completata) plus verdictul.
        """
        resolved = conversion
        if resolved.value is None and self._objective == CampaignObjective.LEAD_GEN:
            resolved = resolved.model_copy(update={"value": self._default_lead_value})

        status = (resolved.lead_status or "").strip().lower()
        if status in _UNQUALIFIED_STATUSES:
            return QualificationResult(
                conversion=resolved, qualified=False, reason=f"marcat de client: {status}"
            )
        if status in _PENDING_STATUSES:
            return QualificationResult(
                conversion=resolved, qualified=False, reason="in asteptarea calificarii (CRM)"
            )

        if resolved.event_type == "phone_call":
            duration = resolved.call_duration_seconds
            if duration is None or duration < _MIN_CALL_DURATION_SECONDS:
                observed = "necunoscuta" if duration is None else f"{duration}s"
                return QualificationResult(
                    conversion=resolved,
                    qualified=False,
                    reason=(
                        f"durata apelului ({observed}) sub minimul de "
                        f"{_MIN_CALL_DURATION_SECONDS}s"
                    ),
                )

        return QualificationResult(conversion=resolved, qualified=True)
