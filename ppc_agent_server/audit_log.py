"""Log structurat (o linie JSON pe eveniment) pentru caile care ating bani.

Doar loggerii de executie, plafon si tracking - nu tot pachetul: restul
serverului (consiliul, SEO) ramane pe logging-ul obisnuit. Campurile
evenimentului vin din ``extra={...}`` al apelului de log; fara PII (emailuri,
telefoane) - acelea nu se scriu niciodata aici.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

AUDIT_LOGGERS = (
    "ppc_agent.services.execution_engine",
    "ppc_agent_server.spend_guard",
    "ppc_agent_server.routers.proposals",
    "ppc_agent_server.tracking.meta_capi",
    "ppc_agent_server.services.emergency_stop",
)

#: Atributele pe care orice ``LogRecord`` le are; restul vin din ``extra``.
_STANDARD = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_audit_logging() -> None:
    """Un handler JSON pe stderr pentru fiecare logger de audit. Idempotent."""
    for name in AUDIT_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
