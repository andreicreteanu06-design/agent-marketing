# site/ — AC Media Marketing (marketing site)

Next.js 16 (App Router) + Tailwind v4 + Motion + GSAP/ScrollTrigger + Lenis.
Vezi planul complet: Faza W1-W4 in `.claude/plans/` la radacina proiectului.

## Rulare locala

```bash
npm run dev
```

## De confirmat/completat inainte de lansare

- [ ] **Numele real** in `About.tsx` ("Sunt Andrei...") — confirmat, sau de corectat.
- [ ] **Logo real**: `Logo.tsx`/`LogoMark` e o recreare SVG aproximativa (nu am
      avut fisierul sursa, doar imaginea din conversatie). Inlocuieste cu
      fisierul real (SVG ideal, PNG cu fundal transparent acceptabil) cand il ai.
- [ ] **Favicon**: inca cel implicit Next.js (`src/app/favicon.ico`) — de
      inlocuit cu un favicon in culorile brandului.
- [ ] **Link Cal.com real**: `src/lib/config.ts` -> `CAL_LINK` e un placeholder
      (`cal.com/ac-media/apel-descoperire`). Inlocuieste cu link-ul tau real.
- [ ] **Email de contact real**: `src/lib/config.ts` -> `CONTACT_EMAIL`.
- [ ] **Domeniu**: `metadata` din `src/app/layout.tsx` (OG image/URL absolut)
      cand exista domeniul.

## Ce ramane dezactivat deliberat (Faza W1)

Sectiunea "Conectează-ți conturile de reclame" din `/creeaza-cont` e vizual
completa dar butonul de submit e dezactivat — activarea vine in Faza W2
(autentificare client + stocare criptata a cheilor API), per decizia
"backend securizat intai".
