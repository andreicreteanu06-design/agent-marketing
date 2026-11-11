---
target: Homepage AC Media — direcție premium
total_score: 19
max_score: 28
na_heuristics: 7,9,10
p0_count: 0
p1_count: 1
timestamp: 2026-10-03T08-52-18Z
slug: src-app-page-tsx
---
⚠️ DEGRADED: single-context (both isolated assessments failed at startup because of the usage limit).

# AC Media — evaluare pentru următorul nivel de design

Suprafață: src/app/page.tsx, mod Persuade. Analiză vizuală desktop 1440 × 900 și mobil 390 × 844; măsurători suplimentare la 1280 × 720. Evaluarea vizuală a fost înregistrată înainte de rularea detectorului. Scorul este o apreciere euristică, nu rezultatul unui studiu cu utilizatori.

## Verdict

Produsul are deja elemente specifice: consiliul cu cinci roluri, controlul uman asupra bugetului, demonstrația în trei pași și proiectele reale. Compoziția generală încă folosește frecvent aceeași formulă: titlu mare, panou albastru rotunjit, obiect plutitor. Această repetiție limitează identitatea și ritmul vizual.

Direcția recomandată: **titaniu editorial, cu produsul în prim-plan**. Grafit și albastru profund, text alb perlat, lumină rece bine localizată, compoziții asimetrice și alternanță între suprafețe mate și sticlă. Păstrăm Geist, materialele existente și animația de scroll.

## Scor euristic

| Criteriu Nielsen | Scor | Observație |
|---|---:|---|
| 1. Vizibilitatea stării | 3/4 | Etapele demo-ului și starea aprobării sunt explicite; etichetele sunt mici. |
| 2. Limbaj familiar | 3/4 | Beneficiile sunt clare; acronimele C-suite adaugă efort pentru un vizitator nou. |
| 3. Control și libertate | 3/4 | Există navigare directă, taburi și reluarea exemplului. |
| 4. Consecvență | 2/4 | Paletă coerentă în componente, dar diferență vizibilă între clipul PPC și randările din titan. |
| 5. Prevenirea erorilor | 3/4 | Datele exemplu și aprobarea simulată sunt declarate; nota trebuie să fie mai lizibilă. |
| 6. Recunoaștere | 3/4 | Etapele sunt vizibile; legătura dintre agenție și platformă poate fi exprimată mai direct. |
| 7. Eficiență pentru experți | n/a | Nu este o suprafață de lucru operațională. |
| 8. Ierarhie și economie vizuală | 2/4 | Materialele și animațiile repetate au greutate apropiată; lipsește un ritm distinct între capitole. |
| 9. Recuperare după erori | n/a | Formularul extern de programare și autentificarea nu au fost evaluate. |
| 10. Documentație | n/a | În afara scopului acestei evaluări a paginii de prezentare. |
| **Total** | **19/28** | **Acceptabil; priorități clare de îmbunătățire.** |

## Ce funcționează

- Exemplul interactiv explică o decizie și păstrează controlul la utilizator.
- Randările din ceramică, titan și sticlă oferă o bază vizuală coerentă.
- Capturile reale din portofoliu adaugă dovezi vizibile și variație cromatică.

## Priorități

### P1 — Lizibilitate și atingere

Măsurat în browser: etichete de 9–11 px pe desktop, nota demo-ului de 8 px pe mobil, taburi de 36 px înălțime pe mobil și 38 px pe desktop. Butonul demo are 40 px.

Propunere: conținut important la 14–16 px, etichete secundare de cel puțin 12 px și zone de atingere de 44 px. Pe mobil reducem informația simultană și folosim spațiul economisit pentru text. Aceste dimensiuni sunt obiective de design, nu o declarație că toate controalele actuale încalcă WCAG.

Fișier principal: src/app/globals.css, clasele product-demo și regulile responsive; src/components/HeroProductDemo.tsx.

### P2 — Compoziția hero-ului

În captura desktop, sculptura este în mare parte tăiată și acoperită de demo. Titlul, obiectul, cardul și mai multe acțiuni concurează pentru atenție.

Propunere: o singură compoziție dominantă, cu demonstrația lizibilă și sculptura poziționată intenționat în relație cu ea. Titlu de aproximativ 80–88 px pe desktop larg, 38–44 px pe telefoanele care permit această mărime; verificare la 320 px. CTA-ul de programare primește cea mai mare greutate vizuală; explicația produsului rămâne acțiunea secundară. Păstrăm destinațiile și identitatea.

Fișiere: src/components/ScrollWorld.tsx și src/app/globals.css. Motorul, duratele și clipurile scroll rămân intacte.

### P2 — Servicii cu identitate proprie

Cele trei carduri repetă grila și încadrarea obiectelor.

Propunere: PPC pune în scenă o decizie explicabilă; Web Design arată un proiect real și un detaliu de interfață; Automatizările arată un flux clar în câțiva pași. Layouturi distincte în aceeași familie vizuală. Sculpturile susțin fiecare mesaj. Păstrăm mecanismul existent de carduri suprapuse.

Fișier: src/components/Services.tsx, stilurile service-card.

### P2 — Continuitatea luminii și mișcării

Clipul PPC folosește fire și particule neon albastre; randările ulterioare au iluminare de studio și titan.

Propunere: ajustări CSS ale contrastului și temperaturii luminii, reflexii localizate și o singură mișcare dominantă în fiecare cadru. Restul mișcării rămâne discret. Păstrăm mesh-ul, gradientele și experiența cinematografică cerute. Interacțiunile folosesc răspuns imediat și tranziții scurte, întreruptibile.

Fișier: src/app/globals.css. Fără schimbarea motorului de scroll.

### P2 — Portofoliu cu detalii ale execuției

Capturile sunt mari și reale, însă explicațiile rămân generale.

Propunere: un proiect prezentat ca studiu de caz: obiectiv, decizii de design, livrabile, captură mare și două detalii relevante. Folosim numai capturi mobile reale și rezultate documentate. Fără procente inventate. Un portret autentic al fondatorului, dacă este disponibil, poate întări partea umană.

Fișiere: src/components/Portfolio.tsx și, ulterior, src/components/About.tsx.

## Încărcare cognitivă și parcurs

Încărcare moderată: focalizarea și ierarhia acțiunilor pot fi mai clare. Împărțirea demo-ului în trei pași ajută. Cele cinci roluri ale consiliului sunt parte din produs și nu trebuie eliminate pentru o regulă arbitrară de număr de opțiuni.

Parcursul pornește atmosferic, devine repetitiv în zona serviciilor și recâștigă credibilitate în portofoliu. Explicarea controlului uman oferă reasigurare înainte de programare.

## Perspective ale utilizatorilor

- Vizitator nou: trebuie să înțeleagă repede relația dintre agenție, platformă și consiliu.
- Utilizator mobil: etichetele mici și taburile înguste cer atenție suplimentară.
- Cumpărător B2B: proiectele reale ajută; livrabilele concrete și responsabilitatea umană trebuie să fie ușor de găsit.

## Dovezi tehnice și limite

Detectorul a returnat trei avertismente gradient-text în globals.css: liniile 255, 279, 421. Gradientele sunt cerute explicit de utilizator, deci nu sunt defecte automate. Scanarea nu a identificat problema principală de lizibilitate, confirmată separat în browser.

Fără erori în consola browserului în eșantionul verificat și fără overflow orizontal la dimensiunile măsurate. Scenele ascunse aveau aria-hidden și inert în hero. Overlay-ul detectorului nu a fost injectat deoarece evaluarea DOM disponibilă este read-only; aceasta nu este o verificare automată completă de accesibilitate.

Catalogul ui-ux-pro-max a susținut direcția cinematică, ierarhia tipografică și țintele de atingere. Paleta roz generată automat de catalog a fost respinsă fiind incompatibilă cu cerința explicită de dark titanium. Parametri orientativi: variație 7/10, mișcare 6/10, densitate 3/10.

## Criterii pentru următoarea versiune

Poate un vizitator recunoaște AC Media fără siglă? Înțelege în primul ecran ce decide sistemul și ce aprobă el? Fiecare secțiune aduce o demonstrație vizuală nouă?

Nu s-au modificat fișierele aplicației în această evaluare.
