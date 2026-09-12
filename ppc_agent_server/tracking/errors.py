"""Tipuri de exceptii pentru modulul de urmarire a conversiilor."""

from __future__ import annotations


class TrackingError(Exception):
    """Un payload de conversie nu a putut fi transformat/validat.

    Ridicata de adaptoare (sursa necunoscuta, payload malformat) - stratul
    FastAPI (``routers/tracking.py``) o traduce in ``HTTPException(422, ...)``,
    la fel cum ``deps.get_owned_client`` ridica ``HTTPException`` direct pentru
    erori de validare specifice unui singur endpoint.
    """
