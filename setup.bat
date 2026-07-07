@echo off
setlocal enabledelayedexpansion
title FCH PartsBot - Instalacion y sincronizacion automatica
color 0A

echo ============================================================
echo    FCH AutoLab PartsBot - SETUP AUTOMATICO
echo ============================================================
echo.
echo Este script hara TODO por ti:
echo   1. Verificar Python
echo   2. Crear/activar entorno virtual (.venv)
echo   3. Instalar dependencias
echo   4. Verificar el archivo .env
echo   5. Inicializar la base de datos
echo   6. Importar el catalogo de vehiculos (merchant.txt)
echo   7. Poblar TODAS las marcas chinas con IA (modelos + anios)
echo   8. Sincronizar piezas de seed_parts.txt (con IA)
echo.
echo ============================================================
echo.

REM ---------------------------------------------------------------
REM 1. Verificar Python 3.12 (recomendado)
REM ---------------------------------------------------------------
echo [1/8] Verificando Python...
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYLAUNCHER=py -3.12"
    py -3.12 --version >nul 2>nul
    if !errorlevel! neq 0 (
        echo    AVISO: No se encontro Python 3.12. Usare el Python por defecto.
        echo    RECOMENDACION: instala Python 3.12 desde python.org para evitar
        echo    errores de compilacion con Python 3.13/3.14.
        set "PYLAUNCHER=python"
    ) else (
        echo    OK: Python 3.12 encontrado.
    )
) else (
    set "PYLAUNCHER=python"
)

REM ---------------------------------------------------------------
REM 2. Crear entorno virtual si no existe
REM ---------------------------------------------------------------
echo.
echo [2/8] Preparando entorno virtual (.venv)...
if not exist ".venv\Scripts\activate.bat" (
    echo    Creando .venv con !PYLAUNCHER! ...
    !PYLAUNCHER! -m venv .venv
    if !errorlevel! neq 0 (
        echo    ERROR: No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo    OK: .venv ya existe.
)
call .venv\Scripts\activate.bat

REM ---------------------------------------------------------------
REM 3. Instalar dependencias
REM ---------------------------------------------------------------
echo.
echo [3/8] Instalando dependencias (puede tardar un par de minutos)...
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo    ERROR: Fallo la instalacion de dependencias.
    echo    Si ves errores de compilacion, usa Python 3.12 (ver README).
    pause
    exit /b 1
)
echo    OK: Dependencias instaladas.

REM ---------------------------------------------------------------
REM 4. Verificar archivo .env
REM ---------------------------------------------------------------
echo.
echo [4/8] Verificando archivo .env...
if not exist ".env" (
    echo    No existe .env. Copiando desde .env.example...
    copy .env.example .env >nul
    echo.
    echo    ==========================================================
    echo    IMPORTANTE: Abre el archivo .env y completa:
    echo      - CASS_USUARIO y CASS_PASSWORD (credenciales CassChoice)
    echo      - GEMINI_API_KEY (para la IA de marcas chinas)
    echo        Consiguela GRATIS en: https://aistudio.google.com/app/apikey
    echo    ==========================================================
    echo.
    echo    Presiona una tecla cuando hayas completado el .env...
    pause >nul
) else (
    echo    OK: .env ya existe.
)

REM Comprobar si GEMINI_API_KEY tiene valor
findstr /R /C:"GEMINI_API_KEY=." .env >nul 2>nul
if %errorlevel% neq 0 (
    echo    AVISO: GEMINI_API_KEY parece vacia en .env.
    echo    Sin ella, las marcas chinas NO se completaran con IA.
    echo    Puedes continuar y completarlas despues ejecutando:
    echo        python sincronizador.py --completar-marcas
    echo.
    timeout /t 4 /nobreak >nul
)

REM ---------------------------------------------------------------
REM 5. Inicializar base de datos
REM ---------------------------------------------------------------
echo.
echo [5/8] Inicializando base de datos...
python init_db.py --reset
if %errorlevel% neq 0 goto :error

REM ---------------------------------------------------------------
REM 6. Importar catalogo de vehiculos (merchant.txt)
REM ---------------------------------------------------------------
echo.
echo [6/8] Importando catalogo de vehiculos (merchant.txt)...
if exist "merchant.txt" (
    python importar_merchant.py
) else (
    echo    AVISO: no se encontro merchant.txt. Se intentara sincronizar en vivo.
    python sincronizador.py --solo-vehiculos
)
if %errorlevel% neq 0 goto :error

REM ---------------------------------------------------------------
REM 7. Poblar marcas chinas con IA (modelos + anios)
REM ---------------------------------------------------------------
echo.
echo [7/8] Poblando marcas chinas con IA (esto puede tardar varios minutos)...
python sincronizador.py --completar-marcas
if %errorlevel% neq 0 goto :error

REM ---------------------------------------------------------------
REM 8. Sincronizar piezas de seed_parts.txt (con IA)
REM ---------------------------------------------------------------
echo.
echo [8/8] Sincronizando piezas de seed_parts.txt...
python sincronizador.py --solo-piezas --archivo-piezas seed_parts.txt
if %errorlevel% neq 0 goto :error

echo.
echo ============================================================
echo    LISTO! Todo instalado y sincronizado.
echo ============================================================
echo.
echo Para arrancar el servidor web, ejecuta:
echo     iniciar_servidor.bat
echo o manualmente:
echo     python -m uvicorn main:app --reload
echo.
echo Luego abre en el navegador: http://localhost:8000
echo.
set /p ARRANCAR="Quieres arrancar el servidor ahora? (S/N): "
if /I "!ARRANCAR!"=="S" (
    echo Arrancando servidor... abre http://localhost:8000
    start http://localhost:8000
    python -m uvicorn main:app --reload
)
goto :fin

:error
echo.
echo ============================================================
echo    ERROR: Algo fallo. Revisa los mensajes de arriba.
echo ============================================================
pause
exit /b 1

:fin
pause
endlocal
