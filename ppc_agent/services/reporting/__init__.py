"""Raportul saptamanal, pe modelul "data asset as code" (bruin, dbt) - fara ele.

Trei straturi, fiecare o functie pura peste iesirea celui dinainte, testabil
singur, cu o granita de forma fixa intre ele:

    extractors  ->  transformers  ->  serving (+ summary)
    RAW             agregat           JSON pentru grafice

- :mod:`.extractors` aduce ce s-a intamplat, exact cum raporteaza sursele: zilele
  de la Google Ads si Meta, deciziile executate. Nicio agregare.
- :mod:`.transformers` calculeaza cu Pandas: totaluri, CPA, ROAS, evolutia fata
  de saptamana anterioara. Banii in bani intregi, nu in float.
- :mod:`.serving` da forma finala, ``WeeklyReportPayload``, gata de legat in
  Recharts/Tremor; :mod:`.summary` scrie rezumatul executiv si verifica ca un
  model de limbaj n-a inventat cifre.

Pachetul nu stie nimic despre baza de date: salvarea raportului si citirea
deciziilor din ``ProposedChange`` le face serverul
(``ppc_agent_server/jobs/weekly_report.py``).
"""

from __future__ import annotations
