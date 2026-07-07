"""
Sincronizador de datos desde CassChoice hacia la base de datos local.

Dos fases independientes (se pueden ejecutar por separado):

  Fase A — Catálogo de vehículos:
    Descarga el árbol list_vehicle_relations y lo aplana en filas
    (marca / modelo / año) usando el ``vehicle_relation_id`` real.
    Las marcas (típicamente chinas) que sólo traen marca sin modelo/año se
    marcan con ``necesita_completar=True`` para completarse luego con IA.

  Fase B — Piezas (query_commodity):
    Para cada número de parte (archivo semilla o CLI) consulta query_commodity,
    crea/actualiza la Autoparte con sus códigos OE/OEM/aftermarket, aplica el
    margen del 6% sobre el precio FOB, guarda cada oferta de precio y genera
    las compatibilidades con los vehículos del catálogo.

Uso:
    python sincronizador.py                  # ambas fases
    python sincronizador.py --solo-vehiculos
    python sincronizador.py --solo-piezas
    python sincronizador.py --piezas F4J16-3705110AB OTRA-PARTE
    python sincronizador.py --archivo-piezas seed_parts.txt
"""
import argparse
import logging
import os
from typing import List, Optional

import database
import models
from config import settings
from cass_client import CassChoiceClient, CassChoiceError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("partsbot.sincronizador")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def aplicar_margen(precio_fob: Optional[float]) -> Optional[float]:
    """Aplica el margen configurado (6% por defecto) al precio FOB."""
    if precio_fob is None:
        return None
    return round(precio_fob * (1 + settings.margen_ganancia), 4)


def _to_int_year(valor) -> Optional[int]:
    try:
        anio = int(str(valor).strip())
        if 1950 <= anio <= 2100:
            return anio
    except (ValueError, TypeError):
        pass
    return None


def _parse_vehicle_detail_str(texto: str):
    """
    Parsea un string de compatibilidad de CassChoice.

    Ejemplos:
        "CHANGAN Alsvin 2018~2024"  -> ("CHANGAN", "Alsvin", 2018, 2024)
        "CHERY Tiggo 4 2019-2023"   -> ("CHERY", "Tiggo 4", 2019, 2023)
        "GEELY Coolray 2020"        -> ("GEELY", "Coolray", 2020, 2020)
    Devuelve (marca, modelo, anio_inicio, anio_fin).
    """
    import re

    texto = (texto or "").strip()
    if not texto:
        return "", "", None, None

    # Detectar rango o año al final (2018~2024 / 2018-2024 / 2018).
    m = re.search(r"(\d{4})\s*[~\-–/]\s*(\d{4})\s*$", texto)
    anio_ini = anio_fin = None
    resto = texto
    if m:
        anio_ini = _to_int_year(m.group(1))
        anio_fin = _to_int_year(m.group(2))
        resto = texto[: m.start()].strip()
    else:
        m2 = re.search(r"(\d{4})\s*$", texto)
        if m2:
            anio_ini = anio_fin = _to_int_year(m2.group(1))
            resto = texto[: m2.start()].strip()

    partes = resto.split()
    marca = partes[0] if partes else ""
    modelo = " ".join(partes[1:]) if len(partes) > 1 else ""
    return marca, modelo, anio_ini, anio_fin


# ---------------------------------------------------------------------------
# FASE A — Catálogo de vehículos
# ---------------------------------------------------------------------------
def _aplanar_vehiculos(nodos: list, acumulador: list):
    """
    Recorre recursivamente el árbol de CassChoice y produce una lista de dicts
    con las hojas relevantes (marca, modelo, año, vehicle_relation_id).
    """
    for nodo in nodos:
        make = (nodo.get("make") or "").strip()
        model = (nodo.get("model") or "").strip()
        year = _to_int_year(nodo.get("year"))
        vr_id = nodo.get("vehicle_relation_id") or nodo.get("name")
        hijos = nodo.get("children", []) or []

        # Registrar el nodo actual (permite buscar por marca aunque no haya hoja).
        acumulador.append(
            {
                "vehicle_relation_id": vr_id,
                "marca": make,
                "modelo": model,
                "anio": year,
                # Necesita completarse si es sólo marca (sin modelo ni año).
                "necesita_completar": bool(make and not model and not hijos),
            }
        )
        if hijos:
            _aplanar_vehiculos(hijos, acumulador)


def sincronizar_vehiculos(db, client: CassChoiceClient) -> int:
    logger.info("=== FASE A: Sincronización de catálogo de vehículos ===")
    try:
        nodos = client.listar_vehiculos()
    except CassChoiceError as exc:
        logger.error("No se pudo obtener el catálogo de vehículos: %s", exc)
        return 0

    aplanados = []
    _aplanar_vehiculos(nodos, aplanados)
    logger.info("Nodos aplanados: %d", len(aplanados))

    # Reemplazo completo del catálogo (idempotente).
    db.query(models.CatalogoVehiculos).delete()
    db.commit()

    insertados = 0
    vistos = set()
    for v in aplanados:
        if not v["marca"]:
            continue
        clave = (v["marca"], v["modelo"], v["anio"])
        if clave in vistos:
            continue
        vistos.add(clave)
        db.add(
            models.CatalogoVehiculos(
                vehicle_relation_id=v["vehicle_relation_id"],
                marca=v["marca"],
                modelo=v["modelo"],
                anio=v["anio"],
                necesita_completar=v["necesita_completar"],
            )
        )
        insertados += 1
        if insertados % 500 == 0:
            db.commit()
            logger.info("  ... %d vehículos insertados", insertados)
    db.commit()

    marcas_incompletas = (
        db.query(models.CatalogoVehiculos)
        .filter(models.CatalogoVehiculos.necesita_completar.is_(True))
        .count()
    )
    logger.info(
        "Catálogo de vehículos sincronizado: %d filas (%d marcas sin modelo/año -> IA).",
        insertados,
        marcas_incompletas,
    )
    return insertados


# ---------------------------------------------------------------------------
# FASE B — Piezas (query_commodity)
# ---------------------------------------------------------------------------
def _extraer_precio_usd(prod: dict) -> Optional[float]:
    price = prod.get("price") or {}
    precios = price.get("prices") or []
    if not precios:
        return None
    # Preferir la moneda configurada (USD).
    for p in precios:
        if p.get("currency") == settings.moneda_precio:
            return p.get("default_price")
    # Fallback: primer precio disponible.
    return precios[0].get("default_price")


def _extraer_imagen(prod: dict) -> Optional[str]:
    for r in prod.get("resources", []) or []:
        if r.get("resource_type") == "PARTS_IMAGE" and r.get("resource_value"):
            return r["resource_value"]
    return None


def _clasificar_codigo(autoparte: models.Autoparte, brand_type: str, parts_number: str):
    """Asigna el número de parte al campo de código correspondiente según el tipo."""
    bt = (brand_type or "").upper()
    if bt == "ORIGINAL" or bt == "OE":
        if not autoparte.codigo_oe:
            autoparte.codigo_oe = parts_number
    elif bt == "OEM":
        if not autoparte.codigo_oem:
            autoparte.codigo_oem = parts_number
    elif bt in ("AFTERMARKET", "AFTER MARKET", "AM"):
        if not autoparte.codigo_aftermarket:
            autoparte.codigo_aftermarket = parts_number


def _crear_compatibilidades_desde_producto(db, autoparte: models.Autoparte, prod: dict):
    """
    Crea compatibilidades. Usa ``vehicle_details`` del producto si viene
    poblado; de lo contrario, vincula por marca contra el catálogo de vehículos
    (agrupando años por modelo).
    """
    creadas = 0
    vehicle_details = prod.get("vehicle_details") or []

    existentes = {
        (c.marca_vehiculo, c.modelo_vehiculo, c.anio_inicio, c.anio_fin)
        for c in autoparte.compatibilidades
    }

    if vehicle_details:
        for vd in vehicle_details:
            # La API devuelve strings tipo "CHANGAN Alsvin 2018~2024"
            # o, en algunas variantes, dicts {make, model, year}.
            if isinstance(vd, dict):
                marca = (vd.get("make") or vd.get("brand") or "").strip()
                modelo = (vd.get("model") or "").strip()
                anio_ini = anio_fin = _to_int_year(vd.get("year"))
            else:
                marca, modelo, anio_ini, anio_fin = _parse_vehicle_detail_str(str(vd))
            clave = (marca, modelo, anio_ini, anio_fin)
            if marca and clave not in existentes:
                db.add(
                    models.Compatibilidad(
                        autoparte_id=autoparte.id,
                        marca_vehiculo=marca,
                        modelo_vehiculo=modelo,
                        anio_inicio=anio_ini,
                        anio_fin=anio_fin,
                    )
                )
                existentes.add(clave)
                creadas += 1
        return creadas

    # Fallback: vincular por marca del repuesto contra el catálogo.
    marca_repuesto = (prod.get("brand_name") or "").strip()
    if not marca_repuesto:
        return 0

    # Agrupar por modelo con rango de años (MIN/MAX).
    from sqlalchemy import func

    filas = (
        db.query(
            models.CatalogoVehiculos.modelo,
            func.min(models.CatalogoVehiculos.anio),
            func.max(models.CatalogoVehiculos.anio),
        )
        .filter(models.CatalogoVehiculos.marca.ilike(marca_repuesto))
        .group_by(models.CatalogoVehiculos.modelo)
        .all()
    )
    for modelo, anio_min, anio_max in filas:
        clave = (marca_repuesto, modelo or "", anio_min, anio_max)
        if clave not in existentes:
            db.add(
                models.Compatibilidad(
                    autoparte_id=autoparte.id,
                    marca_vehiculo=marca_repuesto,
                    modelo_vehiculo=modelo or "",
                    anio_inicio=anio_min,
                    anio_fin=anio_max,
                )
            )
            existentes.add(clave)
            creadas += 1
    return creadas


def _procesar_resultado_parte(db, entry: dict, usar_ia: bool = True) -> Optional[models.Autoparte]:
    """Procesa una entrada de ``results`` (un número de parte con sus productos)."""
    parts_number = entry.get("parts_number")
    productos = entry.get("products", []) or []
    if not productos:
        logger.warning("Sin productos para %s", parts_number)
        return None

    # Elegir como base el primer producto con título/categoría no vacío
    # (algunos productos vienen con product_title = "").
    base = productos[0]
    for prod in productos:
        if (prod.get("product_title") or prod.get("category_name") or "").strip():
            base = prod
            break
    descripcion = base.get("product_title") or base.get("category_name") or parts_number
    categoria = base.get("category_name")
    imagen = _extraer_imagen(base)
    marca_repuesto = base.get("brand_name")

    # Buscar/crear la autoparte por numero_oem (parts_number consultado).
    autoparte = (
        db.query(models.Autoparte)
        .filter(models.Autoparte.numero_oem == parts_number)
        .first()
    )
    if not autoparte:
        autoparte = models.Autoparte(numero_oem=parts_number)
        db.add(autoparte)

    autoparte.descripcion = descripcion
    autoparte.categoria = categoria
    autoparte.imagen_url = imagen
    autoparte.marca = marca_repuesto
    autoparte.calidad = base.get("brand_type")

    # Limpiar precios previos para reflejar la sincronización actual.
    for p in list(autoparte.precios):
        db.delete(p)

    mejor_fob = None
    for prod in productos:
        _clasificar_codigo(autoparte, prod.get("brand_type"), prod.get("parts_number") or parts_number)
        # Clasificar también los números de reemplazo (OE/OEM/aftermarket).
        # CassChoice codifica el tipo en brand_code: p.ej. "CHANGAN_OEM",
        # "CHANGAN_AM" (aftermarket) o "CHANGAN" (original/OE).
        for rep in prod.get("replace_parts_numbers", []) or []:
            bc = (rep.get("brand_code") or "").upper()
            num = rep.get("parts_number")
            if not num:
                continue
            if bc.endswith("_OEM"):
                tipo = "OEM"
            elif bc.endswith("_AM") or bc.endswith("_AFTERMARKET"):
                tipo = "AM"
            else:
                tipo = "OE"
            _clasificar_codigo(autoparte, tipo, num)
        precio_fob = _extraer_precio_usd(prod)
        precio_venta = aplicar_margen(precio_fob)
        if precio_fob is not None and (mejor_fob is None or precio_fob < mejor_fob):
            mejor_fob = precio_fob
        autoparte.precios.append(
            models.PrecioCassChoice(
                calidad=prod.get("brand_type"),
                marca_repuesto=prod.get("brand_name"),
                precio_fob=precio_fob,
                precio_venta=precio_venta,
                moneda=settings.moneda_precio,
                disponibilidad=prod.get("product_status"),
                store_name=prod.get("store_name"),
            )
        )

    # Fallback de códigos: si no se detectó ninguno, usar el número consultado como OE.
    if not any([autoparte.codigo_oe, autoparte.codigo_oem, autoparte.codigo_aftermarket]):
        autoparte.codigo_oe = parts_number

    autoparte.precio_fob = mejor_fob
    autoparte.precio_venta_calculado = aplicar_margen(mejor_fob)

    db.commit()
    db.refresh(autoparte)

    # Compatibilidades (usa el primer producto con vehicle_details o fallback por marca).
    total_compat = 0
    for prod in productos:
        total_compat += _crear_compatibilidades_desde_producto(db, autoparte, prod)
        if prod.get("vehicle_details"):
            break  # con un producto que tenga detalles es suficiente
    db.commit()

    # --- IA: si CassChoice no entregó fitment ÚTIL (con modelo), inferirlo ---
    # Para marcas chinas, CassChoice suele devolver 0 detalles o, a lo sumo,
    # compatibilidades "genéricas" sólo con la marca (sin modelo ni año). En
    # ambos casos activamos la IA para obtener modelo + rango de años reales.
    origen_compat = "casschoice"
    utiles = [c for c in autoparte.compatibilidades if (c.modelo_vehiculo or "").strip()]
    if not utiles and usar_ia:
        # Descartar las compatibilidades genéricas (marca sin modelo) para no
        # ensuciar el catálogo; la IA las reemplaza por fitment concreto.
        for c in list(autoparte.compatibilidades):
            if not (c.modelo_vehiculo or "").strip():
                db.delete(c)
        db.commit()
        inferidas = _inferir_compatibilidades_con_ia(db, autoparte, productos)
        if inferidas:
            total_compat = inferidas
            origen_compat = "ia"

    logger.info(
        "Pieza '%s' (%s) -> %d precio(s), %d compatibilidad(es) [%s]. Precio venta: %s",
        parts_number,
        marca_repuesto,
        len(autoparte.precios),
        total_compat,
        origen_compat,
        autoparte.precio_venta_calculado,
    )
    return autoparte


def _inferir_compatibilidades_con_ia(db, autoparte: models.Autoparte, productos: list) -> int:
    """
    Usa IA para inferir el fitment de una pieza sin ``vehicle_details``.
    Crea las compatibilidades y ENRIQUECE el catálogo de vehículos con los
    modelos/años descubiertos (marcando la marca como ya completada).
    """
    try:
        import ia_service
    except Exception:  # noqa: BLE001
        return 0
    if not ia_service.hay_ia_disponible():
        return 0

    # Reunir todas las marcas reales del proveedor (sin sufijos _OEM/_AM).
    marcas = set()
    for prod in productos:
        bn = (prod.get("brand_name") or "").upper()
        bn = bn.replace("_OEM", "").replace("_AM", "").replace("_AFTERMARKET", "").strip()
        if bn:
            marcas.add(bn)

    fitment = ia_service.inferir_fitment(
        numero_parte=autoparte.numero_oem,
        marcas=sorted(marcas),
        descripcion=autoparte.descripcion or "",
    )
    if not fitment:
        return 0

    existentes = {
        (c.marca_vehiculo, c.modelo_vehiculo, c.anio_inicio, c.anio_fin)
        for c in autoparte.compatibilidades
    }
    creadas = 0
    for f in fitment:
        marca, modelo = f["marca"], f["modelo"]
        ai, af = f["anio_inicio"], f["anio_fin"]
        clave = (marca, modelo, ai, af)
        if clave in existentes:
            continue
        db.add(
            models.Compatibilidad(
                autoparte_id=autoparte.id,
                marca_vehiculo=marca,
                modelo_vehiculo=modelo,
                anio_inicio=ai,
                anio_fin=af,
                origen="ia",
            )
        )
        existentes.add(clave)
        creadas += 1
        # Enriquecer el catálogo de vehículos (año por año) para esta marca.
        _enriquecer_catalogo(db, marca, modelo, ai, af)
    db.commit()
    return creadas


def _enriquecer_catalogo(db, marca: str, modelo: str, anio_ini, anio_fin):
    """Inserta en catalogo_vehiculos los modelos/años inferidos (idempotente)."""
    anios = (
        range(anio_ini, anio_fin + 1)
        if (anio_ini and anio_fin)
        else [anio_ini]
    )
    for anio in anios:
        existe = (
            db.query(models.CatalogoVehiculos)
            .filter_by(marca=marca, modelo=modelo, anio=anio)
            .first()
        )
        if not existe:
            db.add(
                models.CatalogoVehiculos(
                    marca=marca,
                    modelo=modelo,
                    anio=anio,
                    necesita_completar=False,
                    origen="ia",
                )
            )


def _leer_parts_de_archivo(ruta: str) -> List[str]:
    if not os.path.exists(ruta):
        logger.warning("Archivo de piezas no encontrado: %s", ruta)
        return []
    numeros = []
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#"):
                numeros.append(linea)
    return numeros


def sincronizar_piezas(
    db,
    client: CassChoiceClient,
    parts_numbers: List[str],
    lote: int = 20,
    usar_ia: bool = True,
) -> int:
    logger.info("=== FASE B: Sincronización de piezas (query_commodity) ===")
    if not parts_numbers:
        logger.warning("No hay números de parte para sincronizar.")
        return 0

    procesadas = 0
    for i in range(0, len(parts_numbers), lote):
        batch = parts_numbers[i : i + lote]
        try:
            resultados = client.query_commodity(batch)
        except CassChoiceError as exc:
            logger.error("Fallo en lote %s: %s", batch, exc)
            continue
        for entry in resultados:
            try:
                if _procesar_resultado_parte(db, entry, usar_ia=usar_ia):
                    procesadas += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception("Error procesando %s: %s", entry.get("parts_number"), exc)
    logger.info("Piezas sincronizadas: %d", procesadas)
    return procesadas


def completar_fitment_faltante(db, limite: Optional[int] = None) -> dict:
    """
    Procesa DE UNA SOLA VEZ todas las piezas ya guardadas que quedaron sin
    fitment útil (sin ningún modelo concreto), típicas de marcas chinas cuyo
    proveedor no entrega modelos ni años. Usa la IA para inferir el fitment.

    No consulta CassChoice: trabaja sobre lo que ya está en la base de datos,
    así que sólo necesita ``GEMINI_API_KEY`` configurada. Devuelve un resumen.
    """
    try:
        import ia_service
    except Exception:  # noqa: BLE001
        return {"status": "error", "detalle": "No se pudo cargar ia_service."}

    if not ia_service.hay_ia_disponible():
        return {
            "status": "sin_ia",
            "detalle": (
                "No hay proveedor de IA. Configura GEMINI_API_KEY en tu .env "
                "para completar automáticamente las marcas chinas."
            ),
        }

    # Piezas cuyo conjunto de compatibilidades no tiene NINGÚN modelo concreto.
    pendientes = []
    for a in db.query(models.Autoparte).all():
        if not any((c.modelo_vehiculo or "").strip() for c in a.compatibilidades):
            pendientes.append(a)
    if limite:
        pendientes = pendientes[:limite]

    logger.info("=== Completar fitment con IA: %d pieza(s) pendiente(s) ===", len(pendientes))
    total_creadas = 0
    detalle = []
    for a in pendientes:
        # Limpiar compatibilidades genéricas (marca sin modelo) previas.
        for c in list(a.compatibilidades):
            if not (c.modelo_vehiculo or "").strip():
                db.delete(c)
        db.commit()
        marcas = [m for m in [a.marca] if m]
        fitment = ia_service.inferir_fitment(
            numero_parte=a.numero_oem or a.codigo_oem or a.codigo_oe or "",
            marcas=marcas,
            descripcion=a.descripcion or "",
        )
        existentes = {
            (c.marca_vehiculo, c.modelo_vehiculo, c.anio_inicio, c.anio_fin)
            for c in a.compatibilidades
        }
        creadas = 0
        for f in fitment:
            clave = (f["marca"], f["modelo"], f["anio_inicio"], f["anio_fin"])
            if clave in existentes:
                continue
            db.add(
                models.Compatibilidad(
                    autoparte_id=a.id,
                    marca_vehiculo=f["marca"],
                    modelo_vehiculo=f["modelo"],
                    anio_inicio=f["anio_inicio"],
                    anio_fin=f["anio_fin"],
                    origen="ia",
                )
            )
            existentes.add(clave)
            creadas += 1
            _enriquecer_catalogo(db, f["marca"], f["modelo"], f["anio_inicio"], f["anio_fin"])
        db.commit()
        total_creadas += creadas
        detalle.append({"numero": a.numero_oem, "marca": a.marca, "creadas": creadas})
        logger.info("  %s (%s) -> %d compatibilidad(es) [ia]", a.numero_oem, a.marca, creadas)

    logger.info("Completado: %d compatibilidad(es) creadas en %d pieza(s).", total_creadas, len(pendientes))
    return {"status": "ok", "piezas": len(pendientes), "compatibilidades_creadas": total_creadas, "detalle": detalle}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sincronizador CassChoice -> DB")
    parser.add_argument("--solo-vehiculos", action="store_true", help="Sólo fase A")
    parser.add_argument("--solo-piezas", action="store_true", help="Sólo fase B")
    parser.add_argument("--piezas", nargs="*", help="Números de parte explícitos")
    parser.add_argument(
        "--archivo-piezas",
        default="seed_parts.txt",
        help="Archivo con números de parte (uno por línea)",
    )
    parser.add_argument(
        "--sin-ia",
        action="store_true",
        help="Desactiva la inferencia de fitment con IA para piezas sin vehicle_details",
    )
    parser.add_argument(
        "--completar-fitment",
        action="store_true",
        help=(
            "Recorre TODAS las piezas ya guardadas sin fitment (marcas chinas) y "
            "completa sus compatibilidades con IA de una sola vez. No consulta "
            "CassChoice; sólo requiere GEMINI_API_KEY."
        ),
    )
    args = parser.parse_args()

    # Asegurar que las tablas existen.
    models.Base.metadata.create_all(bind=database.engine)

    # Modo offline: completar fitment con IA sobre lo ya cargado (no toca CassChoice).
    if args.completar_fitment:
        db = database.SessionLocal()
        try:
            resumen = completar_fitment_faltante(db)
            logger.info("Resultado: %s", resumen.get("status"))
        finally:
            db.close()
        logger.info("Sincronización finalizada.")
        return

    client = CassChoiceClient()
    db = database.SessionLocal()
    try:
        hacer_vehiculos = not args.solo_piezas
        hacer_piezas = not args.solo_vehiculos

        if hacer_vehiculos:
            sincronizar_vehiculos(db, client)

        if hacer_piezas:
            numeros = args.piezas or _leer_parts_de_archivo(args.archivo_piezas)
            sincronizar_piezas(db, client, numeros, usar_ia=not args.sin_ia)
    finally:
        db.close()
    logger.info("Sincronización finalizada.")


if __name__ == "__main__":
    main()
