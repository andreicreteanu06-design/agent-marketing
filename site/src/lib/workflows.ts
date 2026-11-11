export type WorkflowNode = { id: string; title: string; label: string; detail: string; kind?: "trigger" | "decision" | "human" | "result" };
export type Workflow = { id: string; department: string; title: string; summary: string; outcome: string; control: string; tools: string[]; rows: WorkflowNode[][]; edges: [string, string][] };
// Public diagrams describe the native Python workflows.
export const WORKFLOWS: Workflow[] = [
  {
    "id": "leaduri",
    "department": "Vânzări",
    "title": "Primul răspuns, la momentul potrivit.",
    "summary": "O solicitare nouă este înregistrată, echipa primește contextul, iar răspunsul către client este pregătit pentru verificare.",
    "outcome": "Un răspuns personalizat și un istoric comun pentru echipa de vânzări.",
    "control": "Răspunsul către client se aprobă în platformă. Același eveniment nu produce mesaje duplicate.",
    "tools": [
      "Formular / webhook",
      "AI",
      "Email / SMTP",
      "Istoric AC Media"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Solicitare nouă",
          "label": "Formular / API",
          "detail": "Primește numele, emailul și mesajul printr-o conexiune autentificată.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "draft",
          "title": "Pregătește răspunsul",
          "label": "Contextul firmei",
          "detail": "AI poate redacta o ciornă; dacă nu este disponibil, se folosește un mesaj standard pentru verificare."
        }
      ],
      [
        {
          "id": "approve",
          "title": "Verifici mesajul",
          "label": "Aprobare",
          "detail": "Citești destinatarul și răspunsul înainte să aprobi trimiterea.",
          "kind": "human"
        },
        {
          "id": "team",
          "title": "Anunță echipa",
          "label": "Context comun",
          "detail": "Echipa primește mesajul original și datele de contact, conform modului de trimitere configurat."
        }
      ],
      [
        {
          "id": "log",
          "title": "Urmărești rezultatul",
          "label": "Istoric AC Media",
          "detail": "Rularea și starea fiecărui mesaj rămân în contul tău.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "draft"
      ],
      [
        "draft",
        "approve"
      ],
      [
        "draft",
        "team"
      ],
      [
        "approve",
        "log"
      ],
      [
        "team",
        "log"
      ]
    ]
  },
  {
    "id": "facturi",
    "department": "Finanțe",
    "title": "Urmărire consecventă pentru facturile restante.",
    "summary": "Verifică înregistrările din cont, scadența și starea plății. Pregătește mementouri pentru etapele de întârziere, iar după 30 de zile anunță responsabilul.",
    "outcome": "Mementouri documentate, cu evidența mesajelor deja trimise.",
    "control": "O factură marcată plătită oprește mementourile în așteptare. Aceeași etapă nu generează o nouă trimitere la fiecare verificare.",
    "tools": [
      "Verificare periodică",
      "Istoric AC Media",
      "AI",
      "Email / SMTP"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Verifică scadențele",
          "label": "Verificare periodică",
          "detail": "Citește facturile salvate în contul AC Media și datele lor de scadență.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "check",
          "title": "Alege următorul pas",
          "label": "Scadență și istoric",
          "detail": "Elimină facturile plătite, datele incomplete și notificările repetate; stabilește etapa de urmărire.",
          "kind": "decision"
        }
      ],
      [
        {
          "id": "remind",
          "title": "Trimite un memento",
          "label": "Etapă automată",
          "detail": "Pregătește un mesaj standard pentru etapele de 1, 7 sau 14 zile de întârziere."
        },
        {
          "id": "owner",
          "title": "Te anunță pe tine",
          "label": "Prag de escaladare",
          "detail": "Restanțele care trec pragul din flux sunt semnalate responsabilului pentru următorul pas.",
          "kind": "human"
        }
      ],
      [
        {
          "id": "log",
          "title": "Actualizează evidența",
          "label": "După memento",
          "detail": "Păstrează etapa și starea mesajului în istoricul platformei.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "check"
      ],
      [
        "check",
        "remind"
      ],
      [
        "check",
        "owner"
      ],
      [
        "remind",
        "log"
      ]
    ]
  },
  {
    "id": "suport",
    "department": "Suport",
    "title": "Emailul ajunge la răspunsul potrivit.",
    "summary": "Emailul primit devine o înregistrare în cont. Echipa primește contextul, iar răspunsul către client este pregătit folosind informațiile firmei.",
    "outcome": "O căsuță de email organizată și un traseu clar pentru fiecare solicitare.",
    "control": "Răspunsul către client cere verificare umană. Serviciul de email transmite mesajele către platformă printr-o conexiune configurată separat.",
    "tools": [
      "Email / SMTP",
      "Bază de răspunsuri",
      "AI",
      "Istoric AC Media"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Mesaj primit",
          "label": "Email / webhook",
          "detail": "Serviciul de email trimite un eveniment autentificat, cu subiect, mesaj și adresă de răspuns.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "draft",
          "title": "Pregătește o ciornă",
          "label": "Contextul firmei",
          "detail": "AI propune un răspuns din informațiile configurate. În lipsa lor, mesajul cere ajutorul echipei."
        }
      ],
      [
        {
          "id": "help",
          "title": "Verifică un coleg",
          "label": "Aprobare",
          "detail": "Un coleg citește solicitarea și aprobă răspunsul înainte de trimitere.",
          "kind": "human"
        }
      ],
      [
        {
          "id": "log",
          "title": "Păstrează conversația",
          "label": "Istoric AC Media",
          "detail": "Înregistrarea, ciorna și starea livrării rămân în platformă.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "draft"
      ],
      [
        "draft",
        "help"
      ],
      [
        "help",
        "log"
      ]
    ]
  },
  {
    "id": "continut",
    "department": "Marketing",
    "title": "O idee. Patru forme de a o spune.",
    "summary": "Pornești de la o idee, public și obiectiv. Primești variante adaptate pentru LinkedIn, Facebook, Instagram și newsletter, în vocea brandului tău.",
    "outcome": "Patru ciorne salvate în cont, pregătite pentru revizuire.",
    "control": "Conținutul rămâne în platformă și poate fi trimis echipei prin email, după aprobare. Publicarea pe canale este un pas separat.",
    "tools": [
      "Formular de idei",
      "AI",
      "Istoric AC Media",
      "Email / SMTP"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Adaugi ideea",
          "label": "Brief scurt",
          "detail": "Completezi ideea, scopul și publicul; profilul firmei definește tonul și cuvintele de evitat.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "write",
          "title": "Adaptează mesajul",
          "label": "Vocea brandului",
          "detail": "AI dezvoltă unghiul, variantele de titlu și textele specifice fiecărui canal."
        }
      ],
      [
        {
          "id": "li",
          "title": "LinkedIn",
          "label": "Profesional",
          "detail": "O postare structurată pentru conversații profesionale."
        },
        {
          "id": "fb",
          "title": "Facebook",
          "label": "Conversațional",
          "detail": "O variantă personală și accesibilă pentru comunitate."
        },
        {
          "id": "ig",
          "title": "Instagram",
          "label": "Scurt și vizual",
          "detail": "Text concis, hashtaguri și o direcție pentru imagine."
        },
        {
          "id": "news",
          "title": "Newsletter",
          "label": "Ideea dezvoltată",
          "detail": "Subiect de email și un corp de newsletter în HTML simplu."
        }
      ],
      [
        {
          "id": "approve",
          "title": "Tu revizuiești",
          "label": "Platformă + email",
          "detail": "Revizuiești cele patru variante în platformă, apoi aprobi mesajul către echipă.",
          "kind": "human"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "write"
      ],
      [
        "write",
        "li"
      ],
      [
        "write",
        "fb"
      ],
      [
        "write",
        "ig"
      ],
      [
        "write",
        "news"
      ],
      [
        "li",
        "approve"
      ],
      [
        "fb",
        "approve"
      ],
      [
        "ig",
        "approve"
      ],
      [
        "news",
        "approve"
      ]
    ]
  },
  {
    "id": "onboarding",
    "department": "Operațiuni",
    "title": "Un început bine organizat pentru fiecare client.",
    "summary": "Clientul primește mesajul de bun venit, echipa este anunțată, iar verificările din zilele următoare urmăresc pașii rămași.",
    "outcome": "O primire consecventă și o evidență a pașilor parcurși de fiecare client.",
    "control": "Workerul platformei verifică periodic datele salvate. Poți configura intervalele și marca formularul completat pentru a opri mementourile.",
    "tools": [
      "Webhook",
      "Verificare periodică",
      "Istoric AC Media",
      "Email / SMTP"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Client nou",
          "label": "Date validate",
          "detail": "Înregistrează clientul, datele de contact și începutul colaborării în AC Media.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "welcome",
          "title": "Bun venit + echipa",
          "label": "Pornirea colaborării",
          "detail": "Trimite mesajul de bun venit, apoi anunță echipa responsabilă."
        }
      ],
      [
        {
          "id": "daily",
          "title": "Verifică progresul",
          "label": "Verificare periodică",
          "detail": "Verifică înregistrările din cont pentru a pregăti mementoul sau mesajul de verificare a colaborării.",
          "kind": "decision"
        }
      ],
      [
        {
          "id": "reminder",
          "title": "Cere pasul lipsă",
          "label": "Formular necompletat",
          "detail": "Trimite un memento dacă formularul a rămas necompletat după intervalul configurat."
        },
        {
          "id": "feedback",
          "title": "Întreabă cum merge",
          "label": "Verificare ulterioară",
          "detail": "La intervalul stabilit, trimite un mesaj de verificare a colaborării."
        }
      ],
      [
        {
          "id": "log",
          "title": "Actualizează statusul",
          "label": "Evidență",
          "detail": "Notează ce mesaj a fost trimis, pentru următoarea verificare.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "welcome"
      ],
      [
        "welcome",
        "daily"
      ],
      [
        "daily",
        "reminder"
      ],
      [
        "daily",
        "feedback"
      ],
      [
        "reminder",
        "log"
      ],
      [
        "feedback",
        "log"
      ]
    ]
  },
  {
    "id": "cv",
    "department": "HR",
    "title": "Fiecare candidatură ajunge la un om.",
    "summary": "Datele candidatului și textul CV-ului sunt înregistrate în cont. Responsabilul de recrutare primește materialul pentru verificare.",
    "outcome": "O evidență a candidaturilor și a traseului urmat de fiecare aplicație.",
    "control": "Fără scoruri, clasamente, invitații sau respingeri automate. Decizia și răspunsul către candidat aparțin responsabilului de recrutare.",
    "tools": [
      "Formular / webhook",
      "Text CV",
      "Email / SMTP",
      "Istoric AC Media"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Candidatură nouă",
          "label": "Date + text CV",
          "detail": "Primește numele, emailul, rolul și textul extras al CV-ului.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "check",
          "title": "Verifică datele",
          "label": "Înregistrare",
          "detail": "Validează datele de contact. Dacă lipsește textul CV-ului, semnalează că documentul trebuie citit manual."
        }
      ],
      [
        {
          "id": "human",
          "title": "Responsabilul decide",
          "label": "Revizuire umană",
          "detail": "Un coleg examinează candidatura. Platforma nu atribuie un scor și nu trimite o decizie candidatului.",
          "kind": "human"
        }
      ],
      [
        {
          "id": "log",
          "title": "Păstrează evidența",
          "label": "Istoric AC Media",
          "detail": "Candidatura și starea notificării către echipă rămân în cont.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "check"
      ],
      [
        "check",
        "human"
      ],
      [
        "human",
        "log"
      ]
    ]
  },
  {
    "id": "comenzi",
    "department": "E-commerce",
    "title": "O comandă nouă, confirmată și înregistrată.",
    "summary": "Datele comenzii sunt validate, apoi clientul și echipa primesc informațiile relevante. Comanda este adăugată și în evidența internă.",
    "outcome": "Clientul știe că solicitarea a fost primită, iar echipa are detaliile la îndemână.",
    "control": "Confirmă primirea comenzii, separat de plată și expediere. Implicit, mesajele se verifică înainte de trimitere; poți activa modul automat pentru acest flux.",
    "tools": [
      "Magazin / webhook",
      "Email / SMTP",
      "Istoric AC Media"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Comandă nouă",
          "label": "Din magazin",
          "detail": "Magazinul trimite datele comenzii prin webhook.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "check",
          "title": "Validează datele",
          "label": "Sursă + email",
          "detail": "Verifică sursa, adresa clientului și pregătește detaliile produselor.",
          "kind": "decision"
        }
      ],
      [
        {
          "id": "team",
          "title": "Anunță echipa",
          "label": "Operațiuni",
          "detail": "Echipa primește produsele, valoarea și starea plății.",
          "kind": "human"
        },
        {
          "id": "customer",
          "title": "Confirmă clientului",
          "label": "Email de primire",
          "detail": "Clientul primește numărul comenzii și sumarul produselor."
        },
        {
          "id": "log",
          "title": "Înregistrează comanda",
          "label": "Evidență internă",
          "detail": "Datele sunt salvate în istoricul comenzilor.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "check"
      ],
      [
        "check",
        "team"
      ],
      [
        "check",
        "customer"
      ],
      [
        "check",
        "log"
      ]
    ]
  },
  {
    "id": "stoc",
    "department": "E-commerce",
    "title": "Stocul redus devine o alertă clară.",
    "summary": "La actualizarea stocului, cantitatea este comparată cu pragul configurat. Produsele care ajung la limită sunt semnalate echipei.",
    "outcome": "O notificare cu produsul, cantitatea disponibilă și pragul atins.",
    "control": "Echipa decide reaprovizionarea sau ajustarea campaniilor. Fluxul notifică și înregistrează; nu comandă automat produse.",
    "tools": [
      "Magazin / webhook",
      "Email / SMTP",
      "Istoric AC Media"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Stoc actualizat",
          "label": "Din magazin",
          "detail": "Primește produsul, SKU-ul și cantitatea disponibilă.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "check",
          "title": "Compară cu pragul",
          "label": "Regulă configurabilă",
          "detail": "Continuă doar dacă stocul este mai mic sau egal cu pragul. Actualizările peste prag sunt ignorate.",
          "kind": "decision"
        }
      ],
      [
        {
          "id": "alert",
          "title": "Anunță responsabilul",
          "label": "Stoc redus",
          "detail": "Trimite un email cu produsul, cantitatea și pragul pentru ca echipa să decidă.",
          "kind": "human"
        },
        {
          "id": "log",
          "title": "Păstrează alerta",
          "label": "Istoric",
          "detail": "Înregistrează alerta în platformă pentru urmărire.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "check"
      ],
      [
        "check",
        "alert"
      ],
      [
        "check",
        "log"
      ]
    ]
  },
  {
    "id": "reviewuri",
    "department": "E-commerce",
    "title": "Cere feedback după ce produsul a ajuns.",
    "summary": "Fluxul verifică livrările și trimite cererea de review după intervalul configurat. Comenzile deja contactate sunt excluse.",
    "outcome": "Cereri de feedback trimise la un moment potrivit după livrare.",
    "control": "Intervalul inițial este de 7 zile. Aceeași etapă nu creează mesaje duplicate, iar starea livrării se păstrează în platformă.",
    "tools": [
      "Verificare periodică",
      "Istoric AC Media",
      "Email / SMTP"
    ],
    "rows": [
      [
        {
          "id": "in",
          "title": "Verifică livrările",
          "label": "Verificare periodică",
          "detail": "Citește comenzile livrate salvate în cont și verifică dacă există deja o cerere de feedback.",
          "kind": "trigger"
        }
      ],
      [
        {
          "id": "check",
          "title": "Selectează comenzile",
          "label": "Interval + istoric",
          "detail": "Alege comenzile livrate de suficient timp, cu email valid și fără cerere trimisă anterior.",
          "kind": "decision"
        }
      ],
      [
        {
          "id": "email",
          "title": "Cere un review",
          "label": "Email către client",
          "detail": "Trimite un mesaj cu numărul comenzii și linkul pentru feedback."
        }
      ],
      [
        {
          "id": "log",
          "title": "Marchează trimiterea",
          "label": "Fără repetare",
          "detail": "Păstrează starea mesajului și data confirmării SMTP. Verificările ulterioare nu creează aceeași cerere din nou.",
          "kind": "result"
        }
      ]
    ],
    "edges": [
      [
        "in",
        "check"
      ],
      [
        "check",
        "email"
      ],
      [
        "email",
        "log"
      ]
    ]
  }
];
