@echo off
REM Porneste toate cele 3 servere necesare pentru site (fiecare in fereastra proprie).
REM Inchide ferestrele cand termini de testat.

cd /d "%~dp0"

start "Site (port 3000)" cmd /k "cd site && npm run dev"
start "Backend cont/login (port 8000)" cmd /k ".venv\Scripts\python.exe -m uvicorn ppc_agent_server.app:app --port 8000"
start "Agent SEO+GEO (port 8001)" cmd /k ".venv\Scripts\python.exe -m uvicorn seo_geo_agent.app:app --port 8001"

echo.
echo Toate 3 serverele pornesc in ferestre separate.
echo Asteapta cateva secunde, apoi deschide: http://localhost:3000
echo.
pause
