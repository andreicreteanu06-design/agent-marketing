"""Filtrare business a conversiilor brute inainte sa ajunga la motorul de decizie.

``ConversionQualifier`` aplica doua reguli, in aceasta ordine:

1. Valoare proxy - un "lead"/"phone_call" fara valoare primeste valoarea
   implicita a contului (``ClientAccount.default_lead_value``).
2. Poarta de durata a apelului - un "phone_call" sub pragul minim (sau fara
   durata cunoscuta) e descalificat: NU se numara ca o conversie reusita.
"""

from __future__ import annotations

from pydantic import BaseModel

from ppc_agent_server.tracking.models import StandardizedConversion

_MIN_CALL_DURATION_SECONDS = 60
_PROXY_VALUE_EVENT_TYPES = frozenset({"lead", "phone_call"})


class QualificationResult(BaseModel):
    """Rezultatul calificarii: conversia (cu valoarea proxy aplicata, daca a fost
    cazul) plus verdictul de calificare."""

    conversion: StandardizedConversion
    qualified: bool
    reason: str | None = None


class ConversionQualifier:
    """Aplica valorile proxy si poarta de durata a apelului unei conversii brute."""

    def __init__(self, default_lead_value: float) -> None:
        """Configureaza calificatorul pentru un singur cont client.

        Args:
            default_lead_value: Valoarea proxy pentru "lead"/"phone_call" fara
                valoare explicita (``ClientAccount.default_lead_value``).
        """
        self._default_lead_value = default_lead_value

    def qualify(self, conversion: StandardizedConversion) -> QualificationResult:
        """Aplica valoarea proxy, apoi poarta de durata a apelului.

        Args:
            conversion: Conversia normalizata (deja trecuta prin adaptorul de
                sursa), inainte de orice calificare.

        Returns:
            Conversia (posibil cu valoarea completata) plus verdictul.
        """
        resolved = conversion
        if resolved.value is None and resolved.event_type in _PROXY_VALUE_EVENT_TYPES:
            resolved = resolved.model_copy(update={"value": self._default_lead_value})

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
