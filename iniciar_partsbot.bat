@echo off
title FCH PartsBot - Iniciando Motor...
echo =========================================
echo    Arrancando FCH PartsBot en Docker...
echo =========================================

REM Detener instancias previas para evitar conflictos
docker-compose down

REM Construir y levantar contenedores
docker-compose up --build -d

echo.
echo Esperando a que el backend inicie...
timeout /t 10 /nobreak > NUL

REM Abre el panel visual
start chrome --app="%~dp0index.html"

exit