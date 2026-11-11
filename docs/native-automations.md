# Automatizări native — operare și integrare

Cele nouă procese rulează în FastAPI și folosesc baza de date a aplicației.
Nu necesită n8n, Google Sheets sau executarea codului din exporturile JSON.
Exporturile originale reparate rămân arhivă; configurațiile și credențialele lor nu sunt importate.

## Interfață și procese

Din `/cont/automatizari`, un client autentificat poate configura fiecare flux,
previzualiza un exemplu, înregistra evenimente, verifica ciornele și consulta istoricul.
Fluxurile sunt inițial pe pauză, cu aprobarea mesajelor activată.

| Flux | Intrare și rezultat |
| --- | --- |
| Lead-uri | Nume, email, mesaj → răspuns pentru aprobare și notificarea echipei |
| Facturi | Factură, sumă, scadență, stare plată → mementouri după 1/7/14 zile; după 30 zile, verificare internă |
| Suport | Email normalizat și contextul firmei → răspuns pentru aprobare |
| Conținut | Idee, public, obiectiv → ciorne LinkedIn, Facebook, Instagram, newsletter; fără publicare automată |
| Onboarding | Contact, data începerii, formular completat → bun venit, memento, verificarea colaborării |
| Candidaturi | Contact, rol, text CV → înregistrare și verificare umană; fără scor, clasament sau respingere automată |
| Comenzi | Număr, produse, sumă și stare plată → confirmarea primirii către client și echipă |
| Stoc | SKU, produs, stoc și prag → alertă internă când stocul este la/sub prag |
| Review-uri | Comandă, data livrării, URL HTTPS → cerere după intervalul configurat |

Textele AI folosesc integrarea Ollama existentă (`OLLAMA_HOST`, `OLLAMA_MODEL`).
Fără model disponibil, rezultatul este un șablon marcat ca atare, nu o generare AI reușită.
Răspunsurile către lead-uri/suport, marketingul, recrutarea și escaladările facturilor
cer verificare chiar dacă administratorul contului a ales trimiterea automată a mesajelor standard.

## Pornire

Din rădăcina proiectului, cu mediul Python instalat și configurația existentă a conturilor:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn ppc_agent_server.app:app --host 127.0.0.1 --port 8000
```

Migrarea aditivă `d91005a7b001` urmează `c8a2d4f6e135` și creează patru tabele
`native_automation*`. În producție se aplică prin procedura de migrare și backup existentă.

Pentru scadențe, recuperarea rulărilor din coadă și livrarea mesajelor automate,
pornește **una** dintre variante:

```powershell
# Fără Redis; verifică baza de date la fiecare 30 de secunde.
.\.venv\Scripts\python.exe -m ppc_agent_server.automations.worker

# Alternativ: workerul ARQ existent; REDIS_URL trebuie configurat.
.\.venv\Scripts\arq.exe ppc_agent_server.jobs.worker.WorkerSettings
```

ARQ verifică scadențele la fiecare cinci minute. `--once` pe workerul nativ execută un singur ciclu.
Acesta este un ciclu real: poate trimite mesajele deja aprobate dacă SMTP este activ.
API-ul fără Redis pregătește evenimentele sincron; generarea AI poate prelungi cererea.
Pentru producție folosește coada ARQ și supravegherea procesului din infrastructura existentă.

## Email

Variabilele sunt documentate și în `.env.example` și trebuie puse în mediul **API-ului și workerului**:

```dotenv
AUTOMATION_EMAIL_ENABLED=false
AUTOMATION_SMTP_HOST=
AUTOMATION_SMTP_PORT=587
AUTOMATION_SMTP_USERNAME=
AUTOMATION_SMTP_PASSWORD=
AUTOMATION_SMTP_FROM=
AUTOMATION_SMTP_SSL=false
```

Cu `SSL=false` se cere STARTTLS. Pentru TLS implicit folosește `SSL=true` și portul furnizorului
(uzual 465). Certificatele sunt validate. Expeditorul trebuie autorizat de furnizorul SMTP.
Activează `AUTOMATION_EMAIL_ENABLED=true` numai după configurare; câmpul `email_ready` arată
prezența configurației, nu garantează conectivitatea sau livrarea în inbox.
Parola rămâne pe server; pagina clientului nu o cere și nu o returnează.

## Evenimente și webhook-uri

`GET /api/v1/me/automations`, cu JWT-ul contului, întoarce cele nouă definiții, câmpuri,
exemple, configurații și istoricul recent. Interfața generează formularele din acest catalog.

Rute pentru clientul autentificat:

- `PUT /api/v1/me/automations/{slug}/settings`: configurare și activare.
- `POST /api/v1/me/automations/{slug}/preview`: simulare fără scrieri, email sau generare AI.
- `POST /api/v1/me/automations/{slug}/events`: salvează evenimentul și pregătește procesul.
- `PUT /api/v1/me/automations/records/{id}`: actualizează plata, formularul sau alte date.
- `POST /api/v1/me/automations/check-due`: verifică scadențele contului.
- `POST /api/v1/me/automations/messages/{id}/approve` sau `/cancel`: gestionează un mesaj.
- `POST /api/v1/me/automations/runs/{id}/retry`: reîncearcă o pregătire eșuată fără mesaje.
- `POST` / `DELETE /api/v1/me/automations/{slug}/webhook-key`: emite/rotește sau revocă cheia.

Un formular, magazin sau adaptor de email trimite un eveniment normalizat la URL-ul afișat în cont:

```http
POST /api/v1/automation-hooks/ID_AFISAT_IN_CONT
Authorization: Bearer CHEIA_WEBHOOK
Content-Type: application/json

{
  "event_id": "magazin-comanda-123",
  "data": {
    "name": "Client demonstrativ",
    "email": "client@example.com",
    "order_id": "123",
    "total": "120.00",
    "currency": "RON",
    "items": "Produs demonstrativ x2",
    "payment_status": "în așteptare"
  }
}
```

Cheia este afișată o singură dată; se păstrează doar hash-ul SHA-256 (nu criptare reversibilă).
Cheia identifică un singur cont și flux și nu funcționează pentru autentificare sau MCP.
Rotirea o invalidează pe cea veche. Folosește HTTPS pentru endpoint-ul public.

**Nu există citire automată Gmail, extragere PDF sau abonare directă la evenimente Shopify/WooCommerce.**
Aplicația sursă/adaptorul trebuie să trimită schema de mai sus, adaptată fluxului din catalog.
Pentru CV-uri, textul extras este furnizat de sursă; absența lui cere verificarea documentului de către un coleg.

## Deduplicare, modificări și erori

- Pentru comenzi/facturi, cheia naturală este `order_id`/`invoice_id`; pentru celelalte evenimente este `event_id`.
- Pentru procesele periodice, fiecare etapă are o singură rulare per înregistrare.
- Retrimiterea aceluiași eveniment cu aceleași date întoarce rularea existentă.
  Date diferite pe același identificator cer actualizarea înregistrării, nu creează o copie.
- Actualizarea datelor anulează ciornele vechi neexpediate. Etapele viitoare folosesc datele noi;
  aceeași etapă deja consumată nu este regenerată automat.
- Etapele expirate înainte de procesare sunt omise. Un memento vechi nu se trimite după trecerea
  la o etapă nouă; schedulerul pregătește etapa curentă sub cheia ei proprie.
- Un mesaj este rezervat atomic înainte de SMTP. Fără configurație devine `blocked`.
  Dacă SMTP nu confirmă rezultatul, devine `uncertain` și nu se retrimite automat.
  Verifică jurnalul furnizorului folosind Message-ID-ul stabil înainte de orice intervenție manuală.
- Workerul marchează pregătirile/livrările întrerupte de peste 30 minute pentru verificare.
- Datele și istoricul sunt izolate per cont. Pagina arată ultimele 50 de rulări și 100 mesaje/înregistrări.

## Verificare dezvoltare

```powershell
.\.venv\Scripts\python.exe -m mypy ppc_agent_server/automations ppc_agent_server/routers/automations.py
.\.venv\Scripts\python.exe -m ruff check ppc_agent_server/automations ppc_agent_server/routers/automations.py
.\.venv\Scripts\python.exe -m pytest tests_server/test_native_automations.py tests_server/test_arq_queue.py tests_server/test_migrations.py
```

Testele folosesc baze de date izolate și transport SMTP simulat; nu expediază emailuri reale.
