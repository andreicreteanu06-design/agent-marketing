"""Dispecerizarea job-urilor de fundal (plan / copy / creative).

``queue``: abstractia ``JobQueue`` + ``InlineJobQueue`` (sincron, in proces,
implicit — ce foloseste Faza E si toate testele). ``ArqJobQueue`` (Redis real)
se adauga in Faza F, cu acelasi contract exact.

``tasks``: functiile efective, agnostice de coada — deschid propria sesiune DB
(nu primesc una de la apelant), ca sa functioneze identic fie apelate inline,
fie intr-un proces worker ARQ separat.
"""

from __future__ import annotations
