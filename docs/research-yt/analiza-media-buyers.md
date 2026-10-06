# Media buyeri pe YouTube vs. platforma noastră (buget mic, Meta Ads)

Data analizei: 2026-10-06. Videoclipuri din ultimele ~4 săptămâni, găsite prin `playwright-cli` pe YouTube.

## Ce am putut analiza (și ce nu)

| Videoclip | Autor | Vechime | Transcriere |
| --- | --- | --- | --- |
| How to Scale with Meta Ads On A Low Budget (Post-Andromeda) | Mason Littlejohn | 19 h | da (panou YouTube) |
| How To Succeed With A NEW Meta Ad Account in 2026 | LYFE Marketing | 21 h | da (panou YouTube) |
| I paid Alex Hormozi $235,000 for his Facebook Ads Strategy | Ben Heath | 12 zile | da (yt-dlp, a doua opțiune) |
| The Only Meta Ads Campaign Structure You'll Ever Need | Sam Piliero | 1 zi | NU: YouTube a blocat (400 / 429) |
| The ONLY 2 Ad Creative Formats You Need to Scale | Sam Piliero | 4 săpt. | NU: blocat |
| The New Era of Meta Ads Has Just Begun | Sabri Suby | 2 săpt. | NU: blocat |

Limite: concluziile se bazează pe 3 videoclipuri, nu 6. Cifrele (ROAS 4-5, CPA -50%) sunt declarațiile
autorilor, nu date verificate. Mason și LYFE își vând mentoratul/agenția, deci au interes comercial.
Clipul lui Mason are puține vizualizări (197), dar descrie conturi reale pe ecran.

Transcrierile brute sunt în acest folder (`*.txt`).

## Ce fac experții corect (acord între cel puțin 2 surse)

1. **O singură campanie sub ~100 $/zi.** Mason: un client cu 50 $/zi pe 6 campanii a trecut pe una singură
   și CPA-ul a scăzut cu 50%. LYFE: „o campanie, un ad set, câteva reclame”. Cauza: date fragmentate.
2. **Minim pe test:** 10-25 $/zi per ad set de test (Mason).
3. **Targetare largă.** Fără interese înguste și fără lookalike la început; creativul „cheamă” publicul (Mason).
4. **Obiectiv = rezultatul real** (lead/vânzare), fără „încălzirea” contului cu trafic (LYFE, Heath).
5. **Tracking corect înainte de bani.** Evenimentul `Lead` doar la un lead real, nu la o vizită (LYFE, Heath).
6. **Nu umbla la reclame în faza de învățare** (~50 evenimente / 7 zile; LYFE).
7. **Optimizare pe lead calificat**, nu pe orice lead: întrebări de calificare în formular ca Meta să învețe
   pe oamenii buni (Heath).
8. **Creativ:** concepte dovedite (poveste de fondator, noi-vs-ei, înainte/după), nu idei noi (Mason);
   diversitate de formate și stiluri (video, static, carusel, UGC, mărturii, demo) și volum mare (Heath, Hormozi:
   50+ reclame/săptămână); hook-ul numește clientul ideal (Mason).

## Comparație cu platforma (verificat în cod)

| Practică expert | Platforma | Verdict |
| --- | --- | --- |
| 1 campanie, 1 ad set | `launch_campaign`: 1 campanie + 1 ad set + 1 reclamă, totul `PAUSED` (`providers/meta_campaign.py`) | La fel |
| Targetare largă | Țară sau rază + `advantage_audience: 1`, fără interese/lookalike | La fel |
| Buget pe ad set, nu 6 campanii | Buget pe ad set, `LOWEST_COST_WITHOUT_CAP` | La fel |
| Prag minim per test / nu împărți bugetul | `recommend_arm_capacity` derivă pragul din Gate B și CPA-ul țintă; la 10-25 lei/zi → nivel `micro` (1 variantă) (`decision/budget_strategy.py`) | Mai riguros decât experții (formulă, nu intuiție) |
| Faza de învățare 50 evenimente / 7 zile | Constante `LEARNING_EVENTS=50`, `LEARNING_WINDOW_DAYS=7` + consolidarea ad set-urilor suprapuse (`alignment/meta_liquidity.py`) | La fel |
| Tracking corect | Contract de tracking, CAPI Meta, calificare conversii (apel ≥60 s, valoare proxy lead) (`tracking/`) | Există; corectitudinea nu am auditat-o |
| Lead calificat către Meta | CAPI trimite DOAR conversiile calificate, cu `event_id` pentru deduplicare (`tracking/meta_capi.py`). Neverificat: dacă ad set-ul optimizează pe acel eveniment (`custom_event_type`) | În mare parte la fel |
| Concepte creative dovedite | Nu am găsit arhetipuri (poveste fondator / noi-vs-ei / înainte-după) în `creative/factory.py` sau `creative_evaluator.py`; există swipe file RAG + trenduri | Lipsă |
| Diversitate de formate la lansare | `MetaLaunchSpec` acceptă o singură imagine statică + text. Evaluatorul înțelege video, dar lansarea nu | Lipsă principală |
| Mai multe reclame de testat | O reclamă per lansare; „one-shot per ad set” (Mason) nu e posibil | Lipsă |

## Om vs. agent

- **Omul câștigă la:** judecată de context (Mason a ales CBO pentru că clientul avea stoc limitat), producerea de
  conținut real (fondator, UGC, mărturii), formulare de calificare pe site, decizii de business.
- **Agentul câștigă la:** disciplină (nu schimbă reclama la 12 ore, greșeala numărul 1 la începători), monitorizare
  continuă, praguri matematice (Gate B, Kelly, capacitate per buget), protecție de cheltuială și aprobare umană.
- **Punct comun:** ambii pornesc simplu. Structura platformei e deja cea recomandată de experți.

## Recomandări, în ordinea impactului

1. **Lansare multi-creativ:** extinde `MetaLaunchSpec` la 2-4 reclame (formate diferite) în același ad set, limitate
   de `recommend_arm_capacity` (la buget `micro` rămâne 1; la `standard` 2-4).
2. **Arhetipuri creative dovedite** ca șabloane în generatorul de creativ: poveste de fondator, noi-vs-ei, înainte/după,
   mărturie, demo. Hook-ul trebuie să numească clientul ideal (există deja Clientul Ideal JTBD în consiliu).
3. **Confirmă că ad set-ul optimizează pe evenimentul calificat** trimis prin CAPI (CAPI trimite deja doar lead-uri calificate).
4. **Suport video la lansare** (evaluatorul de retenție există deja).
5. Recitește Sam Piliero și Sabri Suby când YouTube deblochează transcrierile (sunt cei mai relevanți pentru structură
   și formate creative).


## Runda 2: reguli post-Andromeda (8 clipuri) si ce s-a schimbat in cod

Surse noi: Ross McNamee, Octopus, Max Rosewater, Ben Heath (AI), Ashton Shanks (vezi `.claude/skills/meta-ads-post-andromeda/references/surse.md`).
Sinteza regulilor este in skill-ul `meta-ads-post-andromeda`.

Concluzii noi fata de runda 1:
- **Creativul este targetarea** (Octopus): Meta transcrie audio-ul si citeste textul din cadru. Hook-ul trebuie sa numeasca problema.
- **Similaritate:** aceeasi persoana + unghi + oferta = o singura reclama in ochii Meta (Octopus). Unghiul bate formatul.
- **Structura:** o campanie per client ideal, un ad set, 20+ reclame la scara (Ross); la buget mic, mai putine (Mason).
- **Dezacorduri reale:** CBO vs ABO; un ad set total vs per concept; "mai multe reclame" vs "concepte, nu volum".

Modificari in cod (toate cu teste; suita completa trece):
- `ppc_agent/providers/meta_campaign.py`: `MetaAdCreative`, `MetaLaunchSpec.extra_ads` (max 6 reclame), payload versiunea 2 doar cand exista reclame in plus; propunerile vechi se citesc neschimbat.
- `ppc_agent/providers/live/meta.py`: imaginile se descarca toate inainte de orice apel Meta; cate un creative si un anunt per reclama, in acelasi ad set; esec = rollback pe toata campania.
- `ppc_agent/decision/andromeda_rules.py` (nou): similaritate, acelasi unghi, hook generic, numar de reclame fata de capacitatea bugetului.
- `ppc_agent/services/launch_brief.py`: regulile apar ca avertismente/sugestii in brief (nu blocheaza).
- `ppc_agent_server/schemas.py` + `routers/campaigns.py`: `extra_ads` in `propose_launch`; fiecare imagine trece prin poarta CCO, iar una slaba opreste lansarea.

Ramane: video/carusel la lansare, sabloane de concepte, optimizare confirmata pe evenimentul calificat.
