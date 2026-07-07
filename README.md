# FCH AutoLab — PartsBot 🚗🔧

Plataforma **e-commerce B2B de repuestos** con integración a la API de **CassChoice**.
Backend en **FastAPI + SQLAlchemy**, frontend estático (HTML/CSS/JS vanilla) y
sincronizador de catálogo y piezas desde CassChoice.

## ✨ Funcionalidades

- **Catálogo de vehículos** (marca / modelo / **año**) sincronizado desde CassChoice.
- **Autopartes** con códigos **OE / OEM / Aftermarket**, precio FOB y
  **precio de venta con margen del 6%** aplicado automáticamente.
- **Búsqueda por**: marca, modelo, año, nombre de pieza y número de parte.
- **Búsqueda semántica bilingüe (ES/EN)**: busca `pastillas de freno` o `brake pads`.
- **Agrupación inteligente de años**: `Toyota Corolla (2012-2015)` en vez de 4 filas.
- **Autenticación** completa: registro, login (JWT) y perfil (contraseñas con **bcrypt**).
- **E-commerce**: carrito (CRUD) y órdenes en estado **"Pendiente"**.
- **IA** para completar modelos/años de marcas chinas que sólo traen la marca.
- **Seguridad**: credenciales en variables de entorno, validación de tokens JWT.

## 🧱 Estructura del proyecto

```
partsbot/
├── main.py               # App FastAPI (registra routers, sirve el frontend)
├── config.py             # Configuración desde variables de entorno (.env)
├── database.py           # Motor SQLAlchemy (PostgreSQL o SQLite)
├── models.py             # Modelos normalizados (10 tablas)
├── schemas.py            # Esquemas Pydantic (validación de I/O)
├── security.py           # Hashing bcrypt + JWT + dependencia get_current_user
├── services.py           # Lógica: agrupación de años, traducción, búsqueda
├── cass_client.py        # Cliente HTTP de CassChoice
├── sincronizador.py      # Sincronización de vehículos y piezas (CLI)
├── init_db.py            # Crea tablas + seed de traducciones ES/EN
├── seed_parts.txt        # Números de parte semilla para sincronizar
├── routers/
│   ├── auth.py           # /auth/registro, /auth/login, /auth/perfil
│   ├── catalogo.py       # /consultar, /busqueda/semantica, /catalogo/*, /exportar_csv
│   ├── carrito.py        # /carrito/*
│   ├── ordenes.py        # /ordenes/*
│   ├── ia.py             # /ia/completar_datos
│   └── sincronizacion.py # /sincronizar/*
├── index.html            # Frontend e-commerce B2B (SPA de una sola página)
├── requirements.txt
├── .env.example
├── docker-compose.yml
└── API_DOCUMENTATION.md
```

## 🚀 Instalación

### 1. Requisitos
- Python 3.10+
- (Opcional) PostgreSQL 15 — si no se configura, se usa **SQLite** automáticamente.

### 2. Clonar e instalar dependencias
```bash
git clone https://github.com/fjcht/partsbot.git
cd partsbot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
```bash
cp .env.example .env
# Edita .env y completa:
#  - SECRET_KEY  (genera uno: python -c "import secrets; print(secrets.token_hex(32))")
#  - CASS_SID y CASS_TOKEN  (credenciales de sesión de CassChoice)
#  - DATABASE_URL (opcional; vacío = SQLite local)
```

### 4. Inicializar la base de datos
```bash
python init_db.py            # crea tablas + carga traducciones ES/EN
# python init_db.py --reset  # (¡cuidado!) borra y recrea todas las tablas
```

## 🔄 Ejecutar el sincronizador

El sincronizador tiene dos fases independientes:

```bash
# Ambas fases (vehículos + piezas del archivo seed_parts.txt)
python sincronizador.py

# Sólo el catálogo de vehículos (marca/modelo/año)
python sincronizador.py --solo-vehiculos

# Sólo piezas, con números de parte explícitos
python sincronizador.py --solo-piezas --piezas F4J16-3705110AB OTRO-CODIGO

# Sólo piezas, desde un archivo (uno por línea)
python sincronizador.py --solo-piezas --archivo-piezas seed_parts.txt
```

**Qué hace:**
- **Fase A (vehículos):** descarga `list_vehicle_relations`, aplana el árbol usando
  `vehicle_relation_id` real y guarda marca/modelo/año. Las marcas chinas sin
  modelo/año se marcan con `necesita_completar=True`.
- **Fase B (piezas):** llama a `query_commodity` con los números de parte, crea las
  autopartes con sus códigos OE/OEM/Aftermarket, aplica el **margen 6%** sobre el
  FOB, guarda cada oferta de precio y genera las **compatibilidades**.

## ▶️ Ejecutar la API

```bash
uvicorn main:app --reload --port 8000
```

- Frontend: <http://localhost:8000/>
- Documentación interactiva (Swagger): <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

## 🐳 Docker

```bash
docker-compose up --build
```

## 🔐 Uso de la API (resumen)

```bash
# Registro
curl -X POST localhost:8000/auth/registro -H "Content-Type: application/json" \
  -d '{"email":"cliente@empresa.com","password":"secret123","nombre":"Mi Empresa"}'

# Login -> devuelve access_token (JWT)
curl -X POST localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email":"cliente@empresa.com","password":"secret123"}'

# Búsqueda por marca (con JOIN + rangos de años)
curl "localhost:8000/consultar?marca=CHERY"

# Búsqueda semántica bilingüe
curl -X POST localhost:8000/busqueda/semantica -H "Content-Type: application/json" \
  -d '{"termino":"brake pads"}'

# Carrito (requiere Authorization: Bearer <token>)
curl -X POST localhost:8000/carrito/agregar -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"autoparte_id":1,"cantidad":2}'

# Crear orden (estado "Pendiente")
curl -X POST localhost:8000/ordenes/crear -H "Authorization: Bearer $TOKEN"
```

Ver **[API_DOCUMENTATION.md](./API_DOCUMENTATION.md)** para el detalle de todos los endpoints.

## 🗄️ Estructura de la base de datos

| Tabla | Descripción |
|-------|-------------|
| `usuarios` | Clientes B2B/B2C (email, password_hash bcrypt, tipo_cliente, fecha_registro) |
| `catalogo_vehiculos` | Marca / modelo / **año** + `vehicle_relation_id` + `necesita_completar` |
| `autopartes` | Códigos OE/OEM/Aftermarket, precio_fob, **precio_venta_calculado** (margen 6%) |
| `compatibilidades` | Relación autoparte ↔ vehículo (marca, modelo, rango de años) |
| `precios_casschoice` | Ofertas de precio por autoparte (calidad, marca, FOB, venta) |
| `carritos` / `items_carrito` | Carrito de compras del usuario |
| `ordenes` / `items_orden` | Órdenes (estado "Pendiente") e items con precio unitario |
| `traducciones_partes` | Diccionario ES↔EN para búsqueda bilingüe |

## 📝 Notas
- Si `CASS_SID`/`CASS_TOKEN` expiran, actualízalos en `.env` (sesión de CassChoice).
- Si `GEMINI_API_KEY` no está configurada, `/ia/completar_datos` devuelve la lista de
  pendientes sin fallar; con la clave, completa modelos/años automáticamente.
