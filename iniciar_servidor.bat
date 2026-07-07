@echo off
title FCH PartsBot - Servidor Web
color 0A
echo ============================================================
echo    FCH AutoLab PartsBot - Servidor Web
echo ============================================================
echo.

REM Activar entorno virtual si existe
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo Arrancando servidor en http://localhost:8000 ...
echo (Presiona CTRL+C para detenerlo)
echo.
start http://localhost:8000
python -m uvicorn main:app --reload
pause
