#!/usr/bin/env bash
# ============================================================
#  FCH AutoLab PartsBot - SETUP AUTOMATICO (Linux / macOS)
#  Hace todo: venv, dependencias, DB, catalogo, IA, piezas.
# ============================================================
set -e

echo "============================================================"
echo "   FCH AutoLab PartsBot - SETUP AUTOMATICO"
echo "============================================================"

# 1. Elegir Python (preferir 3.12)
PY=python3
if command -v python3.12 >/dev/null 2>&1; then
    PY=python3.12
    echo "[1/8] OK: Python 3.12 encontrado."
else
    echo "[1/8] AVISO: se usara $($PY --version). Se recomienda Python 3.12."
fi

# 2. Entorno virtual
echo "[2/8] Preparando entorno virtual (.venv)..."
if [ ! -d ".venv" ]; then
    $PY -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Dependencias
echo "[3/8] Instalando dependencias..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 4. Archivo .env
echo "[4/8] Verificando .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   Se creo .env desde .env.example."
    echo "   IMPORTANTE: completa CASS_USUARIO, CASS_PASSWORD y GEMINI_API_KEY"
    echo "   (Gemini gratis en https://aistudio.google.com/app/apikey)"
    read -r -p "   Presiona ENTER cuando hayas completado el .env..."
else
    echo "   OK: .env ya existe."
fi

# 5. Base de datos
echo "[5/8] Inicializando base de datos..."
python init_db.py --reset

# 6. Catalogo de vehiculos
echo "[6/8] Importando catalogo de vehiculos..."
if [ -f "merchant.txt" ]; then
    python importar_merchant.py
else
    python sincronizador.py --solo-vehiculos
fi

# 7. Marcas chinas con IA
echo "[7/8] Poblando marcas chinas con IA (puede tardar varios minutos)..."
python sincronizador.py --completar-marcas

# 8. Piezas
echo "[8/8] Sincronizando piezas de seed_parts.txt..."
python sincronizador.py --solo-piezas --archivo-piezas seed_parts.txt

echo ""
echo "============================================================"
echo "   LISTO! Para arrancar el servidor:"
echo "     source .venv/bin/activate"
echo "     python -m uvicorn main:app --reload"
echo "   Luego abre: http://localhost:8000"
echo "============================================================"
