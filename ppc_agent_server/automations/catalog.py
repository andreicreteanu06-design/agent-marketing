"""Public native catalog and form descriptions; no credentials or executable exports."""

from datetime import UTC, datetime, timedelta
from typing import Any

from ppc_agent_server.automations.schemas import INPUTS

TITLES = {
    "leaduri": "Răspuns la lead-uri",
    "facturi": "Urmărirea facturilor",
    "suport": "Răspuns la emailuri",
    "continut": "O idee, patru canale",
    "onboarding": "Primirea clienților",
    "cv": "Candidaturi pentru revizuire",
    "comenzi": "Confirmarea comenzilor",
    "stoc": "Alertă de stoc",
    "reviewuri": "Cerere de review",
}
SCHEDULED = {"facturi", "onboarding", "reviewuri"}
LABELS = {
    "name": "Nume",
    "email": "Email client",
    "message": "Mesajul primit",
    "invoice_id": "Număr factură",
    "amount": "Sumă",
    "currency": "Monedă",
    "due_date": "Data scadenței",
    "paid": "Factura este plătită",
    "subject": "Subiect",
    "idea": "Ideea de conținut",
    "audience": "Publicul",
    "objective": "Obiectivul",
    "started_at": "Începutul colaborării",
    "form_completed": "Formular completat",
    "role": "Rolul",
    "cv_text": "Textul CV-ului (fără scor sau clasament automat)",
    "order_id": "Număr comandă",
    "total": "Total",
    "items": "Produse și cantități",
    "payment_status": "Starea plății",
    "sku": "Cod produs / SKU",
    "product_name": "Produs",
    "stock": "Stoc disponibil",
    "threshold": "Prag de alertă",
    "delivered_at": "Data livrării",
    "review_url": "Link HTTPS pentru review",
}
LONG = {"message", "idea", "cv_text", "items"}
NUMERIC = {"amount", "total", "stock", "threshold"}


def catalog() -> list[dict[str, Any]]:
    entries = []
    for slug, model in INPUTS.items():
        schema = model.model_json_schema()
        fields = []
        for key, spec in schema["properties"].items():
            kind = (
                "textarea"
                if key in LONG
                else "number"
                if key in NUMERIC
                else "checkbox"
                if spec.get("type") == "boolean"
                else "date"
                if spec.get("format") == "date"
                else "email"
                if key == "email"
                else "url"
                if key == "review_url"
                else "text"
            )
            fields.append(
                {
                    "name": key,
                    "label": LABELS[key],
                    "type": kind,
                    "required": key in schema.get("required", []),
                    "default": spec.get("default", ""),
                    "maxLength": spec.get("maxLength"),
                }
            )
        entries.append(
            {
                "id": slug,
                "title": TITLES[slug],
                "scheduled": slug in SCHEDULED,
                "fields": fields,
                "example": example(slug),
            }
        )
    return entries


def example(slug: str) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    contact = {"name": "Client demonstrativ", "email": "client@example.com"}
    samples: dict[str, dict[str, Any]] = {
        "leaduri": {**contact, "message": "Aș dori o ofertă pentru magazinul meu online."},
        "facturi": {
            **contact,
            "invoice_id": "DEMO-101",
            "amount": "450.00",
            "currency": "RON",
            "due_date": str(today - timedelta(days=8)),
            "paid": False,
        },
        "suport": {
            **contact,
            "subject": "Informații despre livrare",
            "message": "Când ajunge comanda?",
        },
        "continut": {
            "idea": "Un nou serviciu pentru magazine online",
            "audience": "Antreprenori",
            "objective": "Solicitări de demonstrație",
        },
        "onboarding": {**contact, "started_at": str(today), "form_completed": False},
        "cv": {
            **contact,
            "role": "Specialist marketing",
            "cv_text": "Experiență în campanii digitale.",
        },
        "comenzi": {
            **contact,
            "order_id": "DEMO-202",
            "total": "120.00",
            "currency": "RON",
            "items": "Produs demonstrativ x2",
            "payment_status": "în așteptare",
        },
        "stoc": {
            "sku": "DEMO-SKU",
            "product_name": "Produs demonstrativ",
            "stock": 3,
            "threshold": 5,
        },
        "reviewuri": {
            **contact,
            "order_id": "DEMO-203",
            "delivered_at": str(today - timedelta(days=8)),
            "review_url": "https://example.com/review",
        },
    }
    return samples[slug]
