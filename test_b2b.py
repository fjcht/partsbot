"""
Pruebas de las capacidades B2B: login (forma), reintentos con backoff,
crawl paginado (total_pages/has_next), export limpio de IAService y el
reporte de piezas publicables. Usa una DB SQLite temporal y mocks (no toca
la red ni CassChoice real).

Ejecutar:  python test_b2b.py
"""
import os
import tempfile

# DB temporal ANTES de importar database.
_tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmpdb.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdb.name}"

import database  # noqa: E402
import models  # noqa: E402
import sincronizador as sync  # noqa: E402
from cass_client import CassChoiceClient, CassChoiceError  # noqa: E402

models.Base.metadata.create_all(bind=database.engine)

OK, FAIL = "\033[92mOK\033[0m", "\033[91mFAIL\033[0m"
_fallos = 0


def check(nombre, cond):
    global _fallos
    print(f"  [{OK if cond else FAIL}] {nombre}")
    if not cond:
        _fallos += 1


# ---------------------------------------------------------------------------
print("\n1) IAService se exporta e instancia limpiamente")
from ia_service import IAService, ia_service, inferir_fitment  # noqa: E402
ia = IAService()
check("import IAService", IAService is not None)
check("instancia .disponible() es bool", isinstance(ia.disponible(), bool))
check("tiene inferir_fitment", callable(ia.inferir_fitment))
check("tiene inferir_modelos_marca", callable(ia.inferir_modelos_marca))
check("instancia compartida ia_service", isinstance(ia_service, IAService))


# ---------------------------------------------------------------------------
print("\n2) Parser de paginación tolera distintos nombres de campo")
# a) formato snake_case explícito
p = CassChoiceClient._extraer_paginacion(
    {"total": 100, "total_pages": 5, "has_next": True, "results": [1, 2]}, 1, 20
)
check("snake_case total_pages=5", p["total_pages"] == 5 and p["has_next"] is True)
# b) camelCase
p = CassChoiceClient._extraer_paginacion(
    {"totalCount": 100, "totalPages": 5, "hasNext": False, "records": [1]}, 5, 20
)
check("camelCase records->results", p["results"] == [1] and p["has_next"] is False)
# c) sólo total -> calcula total_pages y has_next
p = CassChoiceClient._extraer_paginacion({"total": 45, "results": [1] * 20}, 1, 20)
check("calcula total_pages=3 desde total=45", p["total_pages"] == 3)
check("calcula has_next (pag1<3)", p["has_next"] is True)
p = CassChoiceClient._extraer_paginacion({"total": 45, "results": [1] * 5}, 3, 20)
check("has_next False en última página", p["has_next"] is False)


# ---------------------------------------------------------------------------
print("\n3) Reintentos con backoff exponencial (500 -> 500 -> 200)")


class _RespFake:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _SessionFake:
    """Simula fallos 500 transitorios y luego un 200 correcto."""
    def __init__(self, secuencia):
        self.secuencia = secuencia
        self.llamadas = 0
        self.headers = {}
        self.cookies = _CookieJarFake()

    def request(self, metodo, url, **kw):
        r = self.secuencia[min(self.llamadas, len(self.secuencia) - 1)]
        self.llamadas += 1
        return r


class _CookieJarFake:
    def __init__(self):
        self._d = {}

    def set(self, k, v):
        self._d[k] = v

    def get(self, k, default=None):
        return self._d.get(k, default)


cli = CassChoiceClient(sid="x", token="t", auto_login=False, max_retries=4)
cli.session = _SessionFake([
    _RespFake(500, text="boom"),
    _RespFake(500, text="boom"),
    _RespFake(200, {"message": {"data": {"results": [{"parts_number": "A"}], "total": 1}}}),
])
# backoff real dormiría; lo acortamos temporalmente.
import config  # noqa: E402
config.settings.cass_backoff_base = 1.0
config.settings.cass_backoff_max = 0.01
res = cli.query_commodity(["A"])
check("recupera tras 2 fallos 500", res == [{"parts_number": "A"}])
check("hizo 3 llamadas (2 fallos+1 ok)", cli.session.llamadas == 3)

# 4xx no se reintenta
cli2 = CassChoiceClient(sid="x", token="t", auto_login=False, max_retries=4)
cli2.session = _SessionFake([_RespFake(403, text="forbidden")])
try:
    cli2.query_commodity(["A"])
    check("4xx lanza error", False)
except CassChoiceError:
    check("4xx lanza error sin reintentar", cli2.session.llamadas == 1)


# ---------------------------------------------------------------------------
print("\n4) Crawl paginado de 5 páginas (mock) -> indexa piezas+precios+fitment")


def _producto(pn, marca, modelo_anio, precio_usd):
    return {
        "product_id": f"id_{pn}",
        "product_title": f"Repuesto {pn}",
        "category_name": "Ignition",
        "brand_name": marca,
        "brand_type": "ORIGINAL",
        "parts_number": pn,
        "replace_parts_numbers": [
            {"brand_code": marca, "parts_number": pn},
            {"brand_code": f"{marca}_OEM", "parts_number": pn + "-OEM"},
        ],
        "price": {"prices": [
            {"currency": "CNY", "default_price": precio_usd * 7},
            {"currency": "USD", "default_price": precio_usd},
        ]},
        "product_status": "ONSALE",
        "store_name": "Tienda",
        "vehicle_details": [modelo_anio],
    }


PAGINAS = 5
PIEZAS_POR_PAGINA = 4


def _solicitar_mock(metodo, url, *, json_body=None, contexto=""):
    page = json_body.get(config.settings.cass_param_page, 1)
    results = []
    for k in range(PIEZAS_POR_PAGINA):
        pn = f"P{page}-{k}"
        results.append({
            "parts_number": pn,
            "products": [_producto(pn, "CHANGAN", "CHANGAN Alsvin 2018~2024", 10.0 + k)],
        })
    total = PAGINAS * PIEZAS_POR_PAGINA
    return {"message": {"data": {
        "results": results,
        "total": total,
        "has_next": page < PAGINAS,
    }}}


client = CassChoiceClient(sid="x", token="t", auto_login=False)
client._solicitar = _solicitar_mock

db = database.SessionLocal()
procesadas = sync.sincronizar_total(db, client, limite_paginas=5, page_size=PIEZAS_POR_PAGINA, usar_ia=False)
check("procesó 5 páginas x 4 = 20 piezas", procesadas == 20)

n_autopartes = db.query(models.Autoparte).count()
check("20 autopartes indexadas", n_autopartes == 20)

# Verificar precios + margen (6%) sobre USD.
a0 = db.query(models.Autoparte).filter_by(numero_oem="P1-0").first()
check("autoparte P1-0 existe", a0 is not None)
check("precio_fob USD=10.0", a0 and abs((a0.precio_fob or 0) - 10.0) < 1e-6)
check("precio_venta = fob*1.06", a0 and abs((a0.precio_venta_calculado or 0) - 10.6) < 1e-6)
check("tiene precios guardados", a0 and len(a0.precios) >= 1)

# Verificar mapeo de vehículos (fitment) desde vehicle_details.
compat = a0.compatibilidades if a0 else []
check("fitment mapeado (>=1)", len(compat) >= 1)
if compat:
    c = compat[0]
    check("marca=CHANGAN modelo=Alsvin", c.marca_vehiculo == "CHANGAN" and c.modelo_vehiculo == "Alsvin")
    check("rango años 2018-2024", c.anio_inicio == 2018 and c.anio_fin == 2024)

# Códigos OE/OEM clasificados.
check("codigo_oe asignado", bool(a0 and a0.codigo_oe))
check("codigo_oem asignado", bool(a0 and a0.codigo_oem))


# ---------------------------------------------------------------------------
print("\n5) Reporte de piezas PUBLICABLES (CSV)")
csv_path = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
resumen = sync.generar_reporte_publicables(db, csv_path)
check("todas (20) publicables (desc+USD+fitment)", resumen["publicables"] == 20)

# Añadir una pieza NO publicable (sin fitment) y comprobar que se descarta.
mala = models.Autoparte(numero_oem="SIN-FIT", descripcion="algo", precio_venta_calculado=5.0)
db.add(mala)
db.commit()
resumen2 = sync.generar_reporte_publicables(db, csv_path)
check("la pieza sin fitment se descarta", resumen2["no_publicables"] == 1 and resumen2["publicables"] == 20)

with open(csv_path, encoding="utf-8-sig") as f:
    contenido = f.read()
check("CSV tiene encabezado vehiculos_compatibles", "vehiculos_compatibles" in contenido)
check("CSV incluye CHANGAN Alsvin", "CHANGAN Alsvin" in contenido)

db.close()

# ---------------------------------------------------------------------------
print("\n6) Parser con formato EXACTO de partes.md (message.data anidado)")

# Formato real del endpoint de listado masivo (ver partes.md en el repo).
resp_real = {
    "message": {
        "code": 200,
        "message": "Success",
        "data": {
            "results": [
                {"parts_number": "TEST-001", "total": 1, "products": []},
                {"parts_number": "TEST-002", "total": 1, "products": []},
            ],
            "total": 10000,
            "page": 1,
            "page_size": 20,
            "total_pages": 500,
            "has_next": True,
            "has_prev": False,
        }
    }
}

cli_parse = CassChoiceClient(sid="x", token="t", auto_login=False)
cli_parse.session = _SessionFake([_RespFake(200, resp_real)])
pag = cli_parse.query_commodity_pagina(page=1, page_size=20)
check("results extraídos", len(pag["results"]) == 2)
check("total=10000", pag["total"] == 10000)
check("total_pages=500", pag["total_pages"] == 500)
check("has_next=True", pag["has_next"] is True)
check("page=1", pag["page"] == 1)

print("\n" + ("="*50))
if _fallos == 0:
    print(f"  \033[92mTODAS LAS PRUEBAS PASARON\033[0m")
else:
    print(f"  \033[91m{_fallos} PRUEBA(S) FALLARON\033[0m")
print("="*50)
os.unlink(_tmpdb.name)
raise SystemExit(1 if _fallos else 0)
