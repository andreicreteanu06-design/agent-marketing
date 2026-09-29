"""Cifre scrise ca in romana, pentru textele Reginei, ale consiliului si ale profilului cognitiv."""

from __future__ import annotations

from decimal import Decimal


def count(value: float, plural: str, singular: str = "") -> str:
    """Numeral + substantiv, acordat ca in romana.

    "o conversie", "19 conversii", "35 de click-uri", "100 de afisari".
    """
    if value == 1 and singular:
        return f"o {singular}"
    whole = int(value)
    needs_de = whole == value and whole > 0 and (whole % 100 >= 20 or whole % 100 == 0)
    return f"{value:g} {'de ' if needs_de else ''}{plural}"


def ron(value: Decimal) -> str:
    """Suma in forma romaneasca: "68,89", "80"."""
    if value == value.to_integral_value():
        return str(int(value))
    return f"{value:.2f}".replace(".", ",")


def percent(value: float) -> str:
    """O cota 0-1 ca procent intreg: "47%"."""
    return f"{value * 100:.0f}%"


def rate(value: float) -> str:
    """O rata 0-1 cu o zecimala, fara ",0": "6,7%", "12%"."""
    text = f"{value * 100:.1f}".replace(".", ",").removesuffix(",0")
    return f"{text}%"


def decimal(value: float, digits: int = 1) -> str:
    """Un numar cu zecimale, fara zerouri inutile: "62,5", "62"."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:.0f}"
    return text.replace(".", ",")
