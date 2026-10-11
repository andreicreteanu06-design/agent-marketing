# Ghid de tracking pentru clienți

Pentru echipa care se ocupă de site-ul tău (sau pentru tine, dacă îl administrezi singur).

Platforma optimizează reclamele pe clienți reali, nu pe click-uri. Meta învață doar din ce îi trimitem: dacă tracking-ul numără greșit, Meta caută oameni greșiți. Ghidul are patru pași. Durează de obicei o zi de lucru pentru un developer.

| Pas | Ce faci | De ce |
| --- | --- | --- |
| 1 | Pixelul Meta pe site, cu același ID ca serverul | Meta vede vizita și formularul, fără să le numere de două ori |
| 2 | Păstrezi ID-ul reclamei din link | Fiecare lead se leagă de reclama care l-a adus |
| 3 | Trimiți conversia de pe server, la webhook | Lead-urile calificate ajung la Meta prin Conversions API |
| 4 | Verifici în Meta Events Manager | Știi sigur că totul ajunge, înainte să cheltui |

## Ce primești de la agenție

- **URL-ul webhook-ului**, de forma
  `https://<domeniul-platformei>/api/v1/tracking/conversion/<ID-ul tău de client>?source_platform=<sursa>`.
  `source_platform` e `custom_web` (formular sau backend propriu), `gomag` (magazin Gomag) sau `call_tracker` (apeluri).
- **Cheia ta de webhook** (începe cu `whk_`). Merge doar pentru contul tău: nu poate trimite conversii în contul altui client. O trimiți în antetul `Authorization: Bearer whk_...` sau, dacă platforma acceptă doar un URL (Gomag, unele call trackere), la finalul URL-ului: `...&key=whk_...`.

**Cheia stă doar pe server.** Nu o pune în codul paginii, în JavaScript sau într-un formular: oricine o vede în browser ar putea trimite conversii false în contul tău. Dacă s-a scurs, anunță agenția.

> Pentru agenție: cheia clientului se ia din `GET /api/v1/clients/<ID client>/webhook-key`, cu cheia agenției. Cheia agenției (`pk_...`) nu se dă niciodată unui client: deschide toți clienții agenției.

## Pasul 1 - Pixelul Meta pe site

1. Instalează pixelul Meta cu ID-ul primit de la agenție (direct în pagină sau prin Google Tag Manager). Trebuie să trimită `PageView` pe fiecare pagină.
2. La conversie, trimite evenimentul **cu un `eventID`**, același pe care îl trimite și serverul la pasul 3. Meta unește cele două doar dacă numele și ID-ul sunt identice; altfel un lead devine doi.
   - formular de contact sau programare: `Lead`;
   - comandă: `Purchase`.
3. Pornește pixelul doar după acordul din bannerul de cookie-uri (consimțământ de marketing).

Exemplu pentru un formular (ID-ul se generează în browser și pleacă și la server, într-un câmp ascuns):

```html
<form id="programare" method="post" action="/programare">
  <input type="hidden" name="event_id">
  <!-- câmpurile formularului -->
</form>
<script>
  document.getElementById("programare").addEventListener("submit", function (e) {
    var id = "lead_" + crypto.randomUUID();
    e.target.querySelector("[name=event_id]").value = id;
    if (window.fbq) fbq("track", "Lead", {}, { eventID: id });
  });
</script>
```

> **Nu trimite niciodată `SubmitApplication` din pixel.** E evenimentul lead-urilor calificate și îl trimite doar serverul nostru. Pe el optimizează campaniile când au destul volum. Dacă îl trimite și site-ul, Meta învață din toate formularele, inclusiv din cele necalificate.

La magazinele Gomag, `eventID`-ul comenzii este `gomag_order_<id>`, cu `id`-ul comenzii din Gomag:
`fbq("track", "Purchase", {value: 150, currency: "RON"}, {eventID: "gomag_order_1001"})`.

## Pasul 2 - Păstrezi ID-ul reclamei

Reclamele lansate de platformă au în link ID-ul lor, de exemplu:
`https://site.ro/programare?utm_source=facebook&utm_medium=paid_social&utm_campaign=1202...&utm_content=1203...&ad_id=1203...`

Site-ul trebuie să păstreze `ad_id` de la intrare până la formular sau comandă (vizitatorul poate naviga prin mai multe pagini). Un cookie de 90 de zile, setat tot după consimțământ:

```html
<script>
  (function () {
    var params = new URLSearchParams(location.search);
    ["ad_id", "gclid", "ttclid"].forEach(function (key) {
      var value = params.get(key);
      if (value) {
        document.cookie = key + "=" + encodeURIComponent(value) +
          ";path=/;max-age=7776000;SameSite=Lax";
      }
    });
  })();
</script>
```

Pixelul Meta pune singur cookie-urile `_fbp` și `_fbc`. Serverul le citește din cerere la pasul 3, alături de `ad_id`.

**Fără `ad_id`**, conversia se numără, dar nu se leagă de nicio reclamă. Platforma nu poate atunci să-ți propună trecerea pe lead-ul calificat (vezi mai jos).

## Pasul 3 - Trimiți conversia de pe server

După ce formularul e salvat (sau comanda e plătită), serverul site-ului trimite un `POST` la webhook. Se trimite **de pe server, nu din browser**, cu cheia ta de webhook.

### Formular sau backend propriu (`custom_web`)

```bash
curl -X POST "https://<domeniul-platformei>/api/v1/tracking/conversion/<ID client>?source_platform=custom_web" \
  -H "Authorization: Bearer whk_<cheia ta>" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "lead_6f1c2a90-8d1e-4b7a-9c55-2f0e8a1b3c44",
    "event_type": "lead",
    "source_platform": "custom_web",
    "customer_email": "ion.popescu@exemplu.ro",
    "customer_phone": "0722000000",
    "ad_id": "120210000000000",
    "ad_platform": "meta",
    "event_time": 1760000000,
    "event_source_url": "https://site.ro/programare",
    "client_user_agent": "<User-Agent-ul vizitatorului>",
    "client_ip_address": "<IP-ul vizitatorului>",
    "fbp": "<cookie _fbp>",
    "fbc": "<cookie _fbc>",
    "marketing_consent": true
  }'
```

| Câmp | Obligatoriu | Ce conține |
| --- | --- | --- |
| `event_id` | da | ID-ul unic al conversiei: **același** ca `eventID`-ul din pixel |
| `source_platform` | da | `custom_web` |
| `event_type` | da, în practică | `lead`, `purchase`, `contact` sau `phone_call`. **Implicit e `purchase`**: la un formular, trimite `lead` |
| `value`, `currency` | nu | Valoarea comenzii. La lead-uri, fără valoare, se folosește valoarea stabilită cu agenția |
| `customer_email`, `customer_phone` | recomandat | În clar; serverul nostru le transformă ireversibil (hash SHA-256) înainte să le salveze sau să le trimită |
| `ad_id`, `ad_platform` | recomandat | Din cookie-ul de la pasul 2; `ad_platform` e `meta` |
| `lead_status` | nu | Marchează un lead necalificat: `unqualified`, `disqualified` sau `spam` |
| `event_time` | nu | Momentul conversiei (secunde Unix); lipsă = la primire |
| `event_source_url`, `client_user_agent`, `client_ip_address` | recomandat | Din cererea vizitatorului; cu ele, Meta potrivește mai bine conversia cu persoana |
| `fbp`, `fbc` | recomandat | Cookie-urile `_fbp` / `_fbc` puse de pixel |
| `gclid`, `ttclid` | nu | Pentru Google Ads și TikTok, când rulează și acolo |
| `marketing_consent` | recomandat | `false` = vizitatorul a refuzat cookie-urile de marketing: conversia rămâne doar la noi |

### Lead-uri calificate

Nu orice formular e un client. Dacă formularul are o întrebare de calificare (bugetul, zona, tipul lucrării), serverul tău decide și trimite `"lead_status": "unqualified"` pentru cei care nu se potrivesc. Fără `lead_status`, lead-ul e considerat calificat.

Ce se întâmplă apoi:

- **lead calificat:** pleacă la Meta ca `Lead` (unit cu pixelul) și ca `SubmitApplication` (doar de la server);
- **lead necalificat:** rămâne la noi, nu ajunge la Meta.

Campaniile mici pornesc pe `Lead`, ca Meta să iasă repede din faza de învățare. Când o campanie aduce două săptămâni la rând peste 50 de lead-uri calificate pe săptămână, platforma îți propune să o treci pe `SubmitApplication`. Atunci Meta caută doar oameni ca cei calificați.

> Statusul se trimite **o singură dată**, odată cu lead-ul. Dacă același `event_id` e trimis din nou mai târziu (de exemplu după ce vânzările au sunat clientul), a doua trimitere e ignorată.

### Magazin Gomag (`gomag`)

În Gomag, setează webhook-ul de comandă nouă către URL-ul primit, cu `source_platform=gomag`. Comanda se citește din formatul standard Gomag (numărul, totalul, emailul și telefonul din facturare). Gomag nu trimite antete personalizate, așa că pune cheia în URL: `...?source_platform=gomag&key=whk_...`. Dacă poți adăuga în comandă câmpurile `ad_id`, `ad_platform`, `fbp` și `fbc`, comenzile se leagă și de reclame.

### Apeluri (`call_tracker`)

Furnizorul de call tracking trimite, cu `source_platform=call_tracker` (cheia în antet sau ca `&key=whk_...` în URL):

| Câmp | Ce conține |
| --- | --- |
| `call_id` | ID-ul apelului (obligatoriu) |
| `caller_id` | Numărul apelantului |
| `duration_seconds` | Durata convorbirii |
| `call_status` | Starea apelului; `unqualified`, `disqualified` sau `spam` îl exclud |
| `ad_id`, `ad_platform` | Când furnizorul păstrează sursa apelului |

Apelurile sub 60 de secunde nu se numără ca lead: un apel scurt e de obicei o greșeală sau o întrebare fără intenție.

### Răspunsul serverului

```json
{
  "event_id": "lead_6f1c2a90-8d1e-4b7a-9c55-2f0e8a1b3c44",
  "qualified": true,
  "reason": null,
  "deduplicated": false,
  "meta_capi": "sent",
  "google_ads": null,
  "tiktok": null,
  "chatgpt": null
}
```

- `qualified: false` vine cu motivul în `reason` (de exemplu „marcat de client: unqualified” sau „durata apelului (20s) sub minimul de 60s”).
- `deduplicated: true` = conversia era deja primită. **Retrimiterea e sigură**: nu se numără de două ori, iar o trimitere către Meta eșuată se reîncearcă.
- `meta_capi: null` înseamnă că nu era cazul să plece la Meta: necalificată, deja trimisă, fără consimțământ sau cont fără pixel setat.
- Cod `401` = cheie greșită sau cheia altui client; `404` = ID de client greșit (doar cu cheia agenției); `422` = câmp lipsă sau invalid (motivul e în răspuns).

## Pasul 4 - Verificare

1. Cere agenției să pornească modul de test Meta (un cod de test pus pe server pentru câteva ore).
2. În **Meta Events Manager → Testează evenimentele**, completează un formular pe site, venind pe un link cu `?ad_id=test123`.
3. Trebuie să vezi:
   - `Lead` de la browser **și** de la server, marcat ca deduplicat (unul singur numărat);
   - `SubmitApplication` doar de la server, dacă lead-ul e calificat;
   - un lead trimis cu `"lead_status": "unqualified"` nu apare deloc.
4. Răspunsul webhook-ului are `"meta_capi": "sent"`.

Platforma verifică și ea, în fiecare noapte, într-un browser real: deschide site-ul, acceptă cookie-urile, apasă butonul principal și urmărește dacă pixelul trimite evenimentul stabilit. Dacă tracking-ul pică, agenția vede problema a doua zi, iar bugetele noi se opresc până la reparare.

## Greșeli frecvente

| Greșeala | Ce se întâmplă | Cum repari |
| --- | --- | --- |
| `eventID` din pixel diferit de `event_id` trimis la server | Fiecare lead se numără de două ori | Același ID în ambele locuri (pasul 1) |
| `Lead` trimis la încărcarea paginii de mulțumire | Un refresh devine un lead nou | Trimite-l la trimiterea formularului |
| `SubmitApplication` trimis din pixel | Meta învață și din lead-urile necalificate | Scoate-l din pixel și din Tag Manager |
| `event_type` lipsă la un formular | Lead-ul e numărat drept comandă | Trimite `"event_type": "lead"` |
| Cheia de webhook în JavaScript | Oricine poate trimite conversii false în contul tău | Webhook-ul pleacă doar de pe server |
| `ad_id` nepăstrat după prima pagină | Lead-ul nu se leagă de reclamă | Cookie la intrare (pasul 2) |
| Pixel pornit înainte de consimțământ | Risc GDPR | Pornește-l după acordul de marketing |

## Lista finală

- [ ] Pixelul trimite `PageView` pe toate paginile, după consimțământ.
- [ ] `Lead` / `Purchase` pleacă din pixel cu `eventID`.
- [ ] Pixelul nu trimite `SubmitApplication`.
- [ ] `ad_id` (și `gclid`, `ttclid`) se păstrează în cookie de la intrare.
- [ ] Serverul trimite fiecare conversie la webhook, cu același `event_id`.
- [ ] Formularele trimit `"event_type": "lead"` și, unde e cazul, `lead_status`.
- [ ] Cheia de webhook (`whk_...`) e doar pe server.
- [ ] Testul din Events Manager arată `Lead` deduplicat și `SubmitApplication` de la server.
