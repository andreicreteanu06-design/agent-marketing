"""Un site local pentru testele de monitorizare sintetica (fara trafic in afara masinii).

Pagina are un banner de consimtamant, un CTA si tag-uri care trimit evenimente la
GA4 si Meta DOAR dupa consimtamant, ca un site real cu Consent Mode.
``fail_ga4_after_cta`` simuleaza un eveniment de conversie care nu mai pleaca.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GA4 = "https://region1.google-analytics.com/g/collect"
META = "https://www.facebook.com/tr/"

_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="banner"><button id="onetrust-accept-btn-handler">Accept</button></div>
<a id="contact-btn" href="#" style="display:{cta_display}">Programează-te</a>
<script>
function consent() {{
  fetch("{ga4}?v=2&tid=G-TEST123&en=page_view", {{method: "POST", keepalive: true}});
  new Image().src = "{meta}?id=987654&ev=PageView";
}}
document.getElementById("onetrust-accept-btn-handler").addEventListener("click", consent);
document.getElementById("contact-btn").addEventListener("click", function (e) {{
  e.preventDefault();
  {cta_ga4}
  new Image().src = "{meta}?id=987654&ev=Lead";
}});
</script></body></html>"""


def page(*, cta_visible: bool = True, ga4_after_cta: bool = True) -> bytes:
    cta_ga4 = (
        f'navigator.sendBeacon("{GA4}?v=2&tid=G-TEST123", "en=generate_lead&_et=1");'
        if ga4_after_cta
        else ""
    )
    return _PAGE.format(
        ga4=GA4,
        meta=META,
        cta_display="inline" if cta_visible else "none",
        cta_ga4=cta_ga4,
    ).encode()


@contextmanager
def serve(body: bytes, *, status: int = 200) -> Iterator[str]:
    """Serveste ``body`` pe 127.0.0.1; intoarce URL-ul paginii."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
