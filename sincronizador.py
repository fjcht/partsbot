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


def obtener_filtro_completo(db=None) -> dict:
    """
    Construye el filtro completo (brand + vehicle_relation_id_arr) requerido
    por el endpoint query_commodity_by_category para el crawl masivo.

    Si se pasa `db`, consulta las marcas únicas desde CatalogoVehiculos.
    Si la BD está vacía o no se pasa `db`, retorna un fallback hardcoded con
    ~400 marcas conocidas (OEM, AM, Aftermarket, etc.).

    Este filtro se debe pasar como `filtro` a `crawl_commodities()` para que
    se combine con {page, pageSize} en cada petición.
    """
    marcas = set()

    if db is not None:
        try:
            # Extraer vehicle_relation_id únicos (marca base) de la BD.
            for (vr,) in db.query(models.CatalogoVehiculos.vehicle_relation_id).distinct():
                if vr:
                    marcas.add(vr)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error consultando BD para filtro, usando fallback: %s", exc)

    # Si no obtuvimos marcas de la BD, usar fallback hardcoded (del curl real).
    if not marcas:
        marcas = set(MARCAS_REPUESTO)

    marcas_lista = sorted(marcas)
    logger.info("Filtro completo construido: %d marcas", len(marcas_lista))
    return {
        "brand": marcas_lista,
        "vehicle_relation_id_arr": marcas_lista,  # mismo set para ambos params
    }


# ---------------------------------------------------------------------------
# Marcas de repuesto (part brands) — universo REAL del filtro `brand[]`.
# Tomado del curl real de la tienda CassChoice. Cada pieza tiene UNA sola
# `brand`, así que particionar por marca de repuesto NO duplica piezas.
# Incluye OEM (originales), _OEM, _AM (aftermarket de marca) y proveedores
# aftermarket independientes (BOSCH, BREMBO, TRW, SKF, GATES, etc.).
# ---------------------------------------------------------------------------
MARCAS_REPUESTO = sorted({
            "ACURA", "ALFAROMEO", "AUDI", "AVATR", "BAIC", "BAOJUN", "BEIJING",
            "BEIJINGC", "BENTENG", "BENTLEY", "BENZ", "BMW", "BUICK", "BYD",
            "CADILLAC", "CHANGAN", "CHANGHE", "CHERY", "CHEVROLET", "CHRYSLER",
            "CITROEN", "DACIA", "DAEWOO", "DAIHATSU", "DF", "DFFS", "DFFX",
            "DODGE", "EXEED", "FAW", "FAWAUDI", "FEIDIE", "FERRARI", "FIAT",
            "FORD", "FOTON", "GACG", "GEELY", "GM", "GMC", "GWM", "HAFEI",
            "HAIMA", "HANTENG", "HAVAL", "HONDA", "HONGQI", "HUMMER", "HYUNDAI",
            "INFINITI", "ISUZU", "IVECO", "JAC", "JAGUAR", "JEEP", "JETOUR",
            "JETTA", "JINBEI", "JMC", "KAIYI", "KARRY", "KIA", "LADA",
            "LANDROVER", "LANDWIND", "LEADINGIDEAL", "LEOPAARD", "LEXUS",
            "LIFAN", "LOTUS", "LYNKCO", "Li Auto", "MASERATI", "MAYBACH",
            "MAZDA", "MAZDA_ CHANGAN", "MG", "MINI", "MITSUBISHI", "NISSAN",
            "OMODA", "OPEL", "PERODUA", "PEUGEOT", "PONTIAC", "PORSCHE",
            "PROTON", "QOROS", "RENAULT", "ROEWE", "ROVER", "SAAB", "SAIC",
            "SAICMAXUS", "SATURN", "SCANIA", "SHACMAN", "SK", "SMA", "SMART",
            "SOUEAST", "SSANGYONG", "SUBARU", "SUZUKI", "SWM", "TANK", "TESLA",
            "TOYOTA", "TRUMPCHI", "VENUCIA", "VOLVO", "VOYAH", "VW", "WAZI",
            "WULING", "XIAOPENG", "YEMA", "ZEEKR", "ZHONGHUA", "ZOTYE",
            # OEM variants
            "BAIC_OEM", "BENZ_OEM", "BYD_OEM", "CHANA_OEM", "CHANGAN_OEM",
            "CHERY_OEM", "CHEVROLET_OEM", "FORD_OEM", "FOTON_OEM", "GACG_OEM",
            "GEELY_OEM", "GM_OEM", "GWM_OEM", "HAVAL_OEM", "HYUNDAI_OEM",
            "JETOUR_OEM", "KIA_OEM", "LANDROVER_OEM", "LEADINGIDEAL_OEM",
            "MAZDA_OEM", "MG_OEM", "NISSAN_OEM", "PORSCHE_OEM", "ROEWE_OEM",
            "SAICMAXUS_OEM", "SAIC_OEM", "SHACMAN_OEM", "TOYOTA_OEM",
            "TRUMPCHI_OEM", "VOLVO_OEM", "VOYAH_OEM", "VW_OEM", "ZEEKR_OEM",
            # Aftermarket
            "ACURA_AM", "AISAN", "ALFAROMEO_AM", "ALMABAT", "AUDI_AM",
            "AUTO PARTS", "Aftermarket", "BAIC_AM", "BAOJUN_AM", "BENZ_AM",
            "BJ212", "BMW_AM", "BOIGEVIS", "BUICK_AM", "BYD_AM", "CADILLAC_AM",
            "CASL_AM", "CHANA_AM", "CHANGAN_AM", "CHERY_AM", "CHEVROLET_AM",
            "CHRYSLER_AM", "CITROEN_AM", "COWIN_AM", "CTR", "DACIA_AM",
            "DAEWOO_AM", "DAIHATSU_AM", "DFFS_AM", "DFFX_AM", "DFSK_AM",
            "DF_AM", "DODGE_AM", "EVERUS_AM", "EXEED_AM", "FEIDIE_AM",
            "FENGGUANG_AM", "FIAT_AM", "FORD_AM", "FOTON_AM", "GAC",
            "GACAION_AM", "GACG_AM", "GEELY_AM", "GM_AM", "GWM_AM", "HAFEI_AM",
            "HAVAL_AM", "HONDA_AM", "HONGQI_AM", "HUANSU_AM", "HYUNDAI_AM",
            "INFINITI_AM", "ISUZU_AM", "IVECO_AM", "JAC_AM", "JAGUAR_AM",
            "JAPD", "JEEP_AM", "JETOUR_AM", "KIA_AM", "KIRSTEN", "KOYORAD",
            "LADA_AM", "LANDROVER_AM", "LEADINGIDEAL_AM", "LEOPAARD_AM",
            "LEXUS_AM", "LIFAN_AM", "Li Auto_AM", "MAZDA_AM", "MG_AM",
            "MINI_AM", "MITSUBISHI_AM", "MuNiK", "NIBD", "NISSAN_AM",
            "OMODA_AM", "OPEL_AM", "OUSHANG_AM", "PERODUA_AM", "PEUGEOT_AM",
            "PORSCHE_AM", "PROTON_AM", "RENAULT_AM", "ROEWE_AM",
            "SAICMAXUS_AM", "SAIC_AM", "SCANIA_AM", "SE_AM", "SK_AM",
            "SSANGYONG_AM", "SUBARU_AM", "SUZUKI_AM", "TANK_AM", "TESLA_AM",
            "TOYOTA_AM", "TRUMPCHI_AM", "UROparts", "VENUCIA_AM", "VIKA",
            "VOLVO_AM", "VOYAH_AM", "VW_AM", "WEY_AM", "WULING_AM", "XENIA_AM",
            "XG", "XHJ", "YULONG", "ZEEKR_AM", "ZOTYE_AM", "kibi",
            # Proveedores aftermarket
            "3M", "ADVICS", "AFS", "AIRPLEX", "AISIN", "AOLAIQI", "ATE",
            "AUTOPACC", "Andfore", "Asanetwork", "BANDO", "BENDIX", "BILSTEIN",
            "BO YU", "BORGWARNER", "BOSCH", "BREMBO", "Biuceodein", "CARTUSTAR",
            "CHAMPION", "CHUGUANG", "CONTINENTAL", "CONTITECH", "CORTECO",
            "CanpartPro", "Continenta_1", "DANA", "DAYCO", "DEBAIJIA", "DELPHI",
            "DENSO", "DFT", "DINGHU", "ELITES", "ELRING", "Elwis Royal",
            "Evertech", "FAG", "FEBI", "FERODO", "Filtron", "GALFER", "GATES",
            "GE", "GEBA", "GGT", "GKN", "Goodman", "HELLA", "HENGST", "HITACH",
            "Hitachi Astemo", "Hutchinson", "INA", "INA1", "JHAEM", "KOYO",
            "KS", "KUWADA", "KYB", "LAILI", "LEMFORDER", "LPR", "LUK", "Litens",
            "Lucas", "Lynx", "MAHLE", "MAHLE BEHR", "MANN", "MARELLI", "MARWELL",
            "MENGNUO", "MICRON AIR", "MICRONAIR", "MINTEX", "MOOG", "MOTUL",
            "NGK", "NISSENS", "NSK", "NTK", "NTN", "OETEHUI", "OSRAM", "Oudesi",
            "PHILIPS", "PIERBURG", "REACH", "SACHS", "SANDEN", "SDS", "SEG",
            "SENSATA", "SHILE", "SKF", "SOFIMA", "SOGEFIPRO", "SSB", "STABILUS",
            "SVES", "Sidem", "TEMB", "TEXTAR", "TROOFTEC", "TRW", "TUOPU",
            "UFI", "USHONE", "VAG", "VALEO", "VDO", "VW_FAW", "VW_IMP",
            "VW_SAIC", "Victor Reinz", "Vitesco", "WAHLER", "WEISHIDUN",
            "WOKELI", "YIQIFAWAY", "ZF", "ZF/LEMFORDER", "Zimmermann", "kaierbi",
            "wabco",
})


# ---------------------------------------------------------------------------
# Particionado del catálogo (para superar el tope de 10.000 del API)
# ---------------------------------------------------------------------------
# CassChoice (backend Elasticsearch) impone un tope DURO de 10.000 resultados
# por consulta (max_result_window). Un crawl con TODAS las marcas en un solo
# filtro nunca ve más de 10.000 piezas. La solución es PARTICIONAR:
#   1) Consultar marca por marca (cada pieza tiene UNA sola `brand`, así que
#      sumar por marca NO duplica).
#   2) Para las marcas que igual topan en 10.000, sub-particionar por
#      `vehicle_relation_id` a nivel modelo (BRAND#Modelo).
# Al crawlear se deduplica por `parts_number` (una pieza encaja en varios
# vehículos, por eso las sub-particiones se solapan).
TOPE_API = 10000


def _marcas_repuesto(db=None) -> List[str]:
    """
    Devuelve la lista de MARCAS DE REPUESTO (part brands, el param ``brand[]``)
    para particionar el crawl.

    IMPORTANTE: son marcas de REPUESTO (OEM/AM/proveedores), NO marcas de
    vehículo. Siempre se usa la lista fija ``MARCAS_REPUESTO`` (tomada del curl
    real de la tienda); NO se leen de la BD, porque en la BD sólo viven las
    relaciones de vehículo (``vehicle_relation_id``), que son otra dimensión.
    """
    return list(MARCAS_REPUESTO)


def _relaciones_por_marca(db) -> dict:
    """
    Agrupa los ``vehicle_relation_id`` a nivel MODELO (BRAND#Modelo) por su
    marca de vehículo, leyéndolos de CatalogoVehiculos. Devuelve
    ``{marca_vehiculo: [relation_id, ...]}``.
    """
    grupos: dict = {}
    if db is None:
        return grupos
    try:
        q = db.query(models.CatalogoVehiculos.vehicle_relation_id).distinct()
        for (vr,) in q:
            if not vr or "#" not in vr:
                continue
            # Nivel modelo = exactamente un '#': BRAND#Modelo (ignorar año).
            marca = vr.split("#", 1)[0]
            base_modelo = "#".join(vr.split("#")[:2])  # BRAND#Modelo
            grupos.setdefault(marca, set()).add(base_modelo)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudieron leer relaciones por marca: %s", exc)
    return {k: sorted(v) for k, v in grupos.items()}


def obtener_particiones(client, db, page_size_sonda: int = 1):
    """
    Generador de particiones de filtro, cada una GARANTIZADA bajo el tope de
    10.000 (en la medida de lo posible). Emite tuplas ``(etiqueta, filtro, total)``.

    Estrategia:
      - Para cada marca de repuesto se consulta su ``total``.
      - Si total < 10.000  -> se emite ``{"brand": [marca]}`` (partición directa).
      - Si total >= 10.000 (marca TOPADA) -> se emite SIEMPRE la partición base
        ``{"brand": [marca]}`` (que recupera las primeras 10.000 piezas) Y ADEMÁS
        se intenta sub-particionar por ``vehicle_relation_id`` a nivel modelo
        para alcanzar las piezas por encima de la ventana de 10.000. El crawler
        deduplica por ``parts_number``, así que el solape entre la base y las
        sub-particiones no genera duplicados.

    NOTA sobre el sub-particionado por vehículo: sólo aporta piezas EXTRA para
    marcas cuyas piezas están efectivamente etiquetadas contra relaciones de
    vehículo del mismo nombre (p.ej. BMW). Para marcas cuyo mapeo marca->vehículo
    no coincide (p.ej. la marca de repuesto ``BENZ`` frente al prefijo de
    vehículo ``MERCEDESBENZ``) o proveedores aftermarket sin vehículo asociado
    (BOSCH, TRW, SKF...), el sub-particionado no aporta piezas nuevas y se
    cubre lo alcanzable (10.000). Emitir SIEMPRE la base evita perder esas
    piezas.
    """
    marcas = _marcas_repuesto(db)
    relaciones = _relaciones_por_marca(db)
    todos_modelos = sorted({m for lst in relaciones.values() for m in lst})

    def sonda(filtro):
        try:
            info = client.query_commodity_pagina(page=1, page_size=page_size_sonda, filtro=filtro)
            return info.get("total", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sonda falló para %s: %s", filtro, exc)
            return -1

    for marca in marcas:
        total = sonda({"brand": [marca]})
        if total <= 0:
            continue
        if total < TOPE_API:
            yield (marca, {"brand": [marca]}, total)
            continue

        # Marca TOPADA: emitir SIEMPRE la base (primeras 10.000)...
        yield (marca, {"brand": [marca]}, total)

        # ...y ADEMÁS sub-particionar por modelo de vehículo para las EXTRA.
        modelos = relaciones.get(marca) or todos_modelos
        if not modelos:
            logger.info(
                "Marca '%s' topa en %d y no hay modelos para sub-particionar; "
                "se cubre hasta 10.000.", marca, TOPE_API,
            )
            continue

        logger.info(
            "Marca '%s' topa en 10.000 -> probando %d modelo(s) para piezas extra.",
            marca, len(modelos),
        )
        emitidas = 0
        for modelo in modelos:
            filtro = {"brand": [marca], "vehicle_relation_id_arr": [modelo]}
            sub = sonda(filtro)
            if sub <= 0:
                continue
            emitidas += 1
            yield (f"{marca}|{modelo}", filtro, sub)
        if emitidas == 0:
            logger.info(
                "Marca '%s': el sub-particionado por vehículo no aportó piezas "
                "extra (mapeo marca->vehículo no coincide); cubierta hasta 10.000.",
                marca,
            )


def contar_catalogo(db, client: CassChoiceClient, exacto_topadas: bool = False) -> dict:
    """
    Cuenta el catálogo de CassChoice SIN crawlear todas las piezas.

    Suma el ``total`` de cada marca de repuesto (cada pieza tiene una sola
    ``brand``, así que la suma no duplica). Identifica las marcas que topan en
    10.000 (tienen más piezas de las que el API revela en una consulta).

    - ``exacto_topadas=False`` (rápido): las marcas topadas cuentan como 10.000
      (piso). Devuelve el conteo mínimo garantizado + lista de topadas.
    - ``exacto_topadas=True`` (lento): sub-particiona y DEDUPLICA por
      ``parts_number`` las marcas topadas para su conteo exacto (requiere
      descargar sus números de parte).
    """
    marcas = _marcas_repuesto(db)
    detalle = {}
    topadas = []
    suma = 0
    for i, marca in enumerate(marcas):
        try:
            info = client.query_commodity_pagina(page=1, page_size=1, filtro={"brand": [marca]})
            total = info.get("total", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Conteo falló para %s: %s", marca, exc)
            continue
        detalle[marca] = total
        suma += total
        if total >= TOPE_API:
            topadas.append(marca)
        if (i + 1) % 50 == 0:
            logger.info("Conteo: %d/%d marcas, suma parcial %d", i + 1, len(marcas), suma)

    resultado = {
        "marcas_consultadas": len(detalle),
        "suma_piso": suma,          # con topadas contadas como 10.000
        "marcas_topadas": topadas,
        "detalle": detalle,
    }

    if exacto_topadas and topadas:
        logger.info("Conteo EXACTO de %d marca(s) topada(s) (con dedup)...", len(topadas))
        relaciones = _relaciones_por_marca(db)
        todos_modelos = sorted({m for lst in relaciones.values() for m in lst})
        extra = 0
        exacto_por_marca = {}
        for marca in topadas:
            modelos = relaciones.get(marca) or todos_modelos
            vistos = set()
            for modelo in modelos:
                filtro = {"brand": [marca], "vehicle_relation_id_arr": [modelo]}
                for pagina in client.crawl_commodities(page_size=50, filtro=filtro):
                    for entry in pagina["results"]:
                        pn = entry.get("parts_number") or entry.get("partsNumber")
                        if pn:
                            vistos.add(pn)
            # El sub-particionado por vehículo sólo aporta el conteo exacto para
            # marcas alineables con vehículos (BMW). Para las que no (BENZ,
            # proveedores AM), devuelve < 10.000: en ese caso NO sabemos el
            # exacto, así que conservamos el piso de 10.000 (extra 0).
            piezas = max(len(vistos), TOPE_API)
            exacto_por_marca[marca] = {
                "piezas_estimadas": piezas,
                "unicas_por_vehiculo": len(vistos),
                "exacto_confiable": len(vistos) > TOPE_API,
            }
            extra += piezas - TOPE_API  # ya contamos 10.000 en suma_piso
            logger.info(
                "  %s: %d piezas únicas vía vehículo (estimado %d).",
                marca, len(vistos), piezas,
            )
        resultado["exacto_por_marca_topada"] = exacto_por_marca
        resultado["total_exacto"] = suma + extra

    return resultado


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


def _procesar_pagina(db, info, vistos, usar_ia) -> int:
    """Procesa los resultados de una página, deduplicando por parts_number."""
    nuevas = 0
    for entry in info["results"]:
        pn = entry.get("parts_number") or entry.get("partsNumber")
        if pn and pn in vistos:
            continue  # ya procesada en otra partición/página (dedup global)
        if pn:
            vistos.add(pn)
        # Cada entry debe tener parts_number + products. Si el endpoint
        # de búsqueda entrega productos sueltos, los envolvemos.
        if "products" not in entry and pn:
            entry = {"parts_number": pn, "products": [entry]}
        try:
            if _procesar_resultado_parte(db, entry, usar_ia=usar_ia):
                nuevas += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("Error procesando %s: %s", pn, exc)
    return nuevas


def sincronizar_total(
    db,
    client: CassChoiceClient,
    limite_paginas: Optional[int] = None,
    page_size: Optional[int] = None,
    usar_ia: bool = True,
    particionar: bool = True,
) -> int:
    """
    Crawl MASIVO del catálogo de piezas de CassChoice.

    El API impone un tope DURO de 10.000 resultados por consulta, así que un
    crawl con un único filtro global nunca supera 10.000 piezas. Por defecto
    (``particionar=True``) se recorre el catálogo PARTICIONADO por marca de
    repuesto (y sub-particionado por modelo de vehículo para las marcas que
    topan), deduplicando por ``parts_number`` para obtener el catálogo COMPLETO.

    - ``particionar=False``: modo antiguo (un solo filtro, máx. 10.000). Útil
      para pruebas rápidas.
    - ``limite_paginas``: máximo de páginas POR PARTICIÓN (ideal para pruebas).
    - Resiliente: los reintentos con backoff viven en el cliente HTTP.
    """
    logger.info(
        "=== SYNC TOTAL: crawl %s (limite_paginas=%s, page_size=%s) ===",
        "PARTICIONADO" if particionar else "simple",
        limite_paginas or "todas", page_size or settings.cass_page_size,
    )
    vistos: set = set()
    procesadas = 0

    if not particionar:
        # Modo simple: un solo filtro global (limitado a 10.000 por el API).
        filtro = obtener_filtro_completo(db)
        try:
            for info in client.crawl_commodities(
                limite_paginas=limite_paginas, page_size=page_size, filtro=filtro
            ):
                procesadas += _procesar_pagina(db, info, vistos, usar_ia)
                db.commit()
        except CassChoiceError as exc:
            logger.error("Crawl interrumpido: %s", exc)
        logger.info("SYNC TOTAL (simple) finalizado: %d pieza(s).", procesadas)
        return procesadas

    # Modo particionado: recorre marca por marca (y modelo por modelo si topa).
    n_part = 0
    for etiqueta, filtro, total in obtener_particiones(client, db):
        n_part += 1
        logger.info("[Partición %d] %s (total reportado: %d)", n_part, etiqueta, total)
        try:
            for info in client.crawl_commodities(
                limite_paginas=limite_paginas, page_size=page_size, filtro=filtro
            ):
                procesadas += _procesar_pagina(db, info, vistos, usar_ia)
            db.commit()
        except CassChoiceError as exc:
            logger.error("Partición '%s' interrumpida: %s", etiqueta, exc)
            db.rollback()

    logger.info(
        "SYNC TOTAL (particionado) finalizado: %d pieza(s) ÚNICA(S) en %d partición(es).",
        procesadas, n_part,
    )
    return procesadas


def generar_reporte_publicables(db, ruta_csv: str = "publicables.csv") -> dict:
    """
    Identifica las piezas PUBLICABLES (listas para vender) y genera un CSV.

    Una pieza es publicable si cumple las 3 condiciones de negocio:
      1. Tiene descripción no vacía.
      2. Tiene precio de venta en USD (> 0).
      3. Tiene fitment COMPLETO: al menos una compatibilidad con modelo concreto
         (marca + modelo; si además hay año, mejor).

    El CSV queda listo para el equipo comercial: qué vender y a quién.
    """
    import csv

    columnas = [
        "numero_oem", "descripcion", "categoria", "marca", "calidad",
        "codigo_oe", "codigo_oem", "codigo_aftermarket",
        "precio_fob_usd", "precio_venta_usd", "moneda",
        "vehiculos_compatibles", "n_compatibilidades", "origen_fitment",
    ]

    publicables = 0
    no_publicables = 0
    filas = []
    for a in db.query(models.Autoparte).all():
        tiene_desc = bool((a.descripcion or "").strip())
        precio = a.precio_venta_calculado
        tiene_precio = precio is not None and precio > 0
        compat_utiles = [
            c for c in a.compatibilidades if (c.modelo_vehiculo or "").strip()
        ]
        tiene_fitment = len(compat_utiles) > 0

        if not (tiene_desc and tiene_precio and tiene_fitment):
            no_publicables += 1
            continue

        publicables += 1
        # Texto legible de vehículos compatibles.
        vehiculos = []
        for c in compat_utiles:
            rango = ""
            if c.anio_inicio and c.anio_fin and c.anio_inicio != c.anio_fin:
                rango = f" {c.anio_inicio}-{c.anio_fin}"
            elif c.anio_inicio:
                rango = f" {c.anio_inicio}"
            vehiculos.append(f"{c.marca_vehiculo} {c.modelo_vehiculo}{rango}".strip())
        origen = "ia" if any(getattr(c, "origen", "") == "ia" for c in compat_utiles) else "casschoice"

        filas.append({
            "numero_oem": a.numero_oem or "",
            "descripcion": a.descripcion or "",
            "categoria": a.categoria or "",
            "marca": a.marca or "",
            "calidad": a.calidad or "",
            "codigo_oe": a.codigo_oe or "",
            "codigo_oem": a.codigo_oem or "",
            "codigo_aftermarket": a.codigo_aftermarket or "",
            "precio_fob_usd": a.precio_fob if a.precio_fob is not None else "",
            "precio_venta_usd": precio,
            "moneda": settings.moneda_precio,
            "vehiculos_compatibles": " | ".join(vehiculos),
            "n_compatibilidades": len(compat_utiles),
            "origen_fitment": origen,
        })

    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columnas)
        writer.writeheader()
        writer.writerows(filas)

    logger.info(
        "Reporte de publicables generado: %s (%d publicables, %d descartadas).",
        ruta_csv, publicables, no_publicables,
    )
    return {
        "status": "ok",
        "archivo": ruta_csv,
        "publicables": publicables,
        "no_publicables": no_publicables,
    }


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


def completar_marcas_faltantes(db, limite: Optional[int] = None) -> dict:
    """
    Puebla con IA el catálogo de vehículos para las marcas (típicamente chinas)
    que CassChoice entregó SIN modelos ni años (``necesita_completar=True``).

    Para cada marca infiere su lista de modelos + rango de años y crea las filas
    correspondientes en ``catalogo_vehiculos`` (año por año), igual que las
    marcas occidentales. Así aparecen en los desplegables de búsqueda aunque no
    haya piezas cargadas todavía. No consulta CassChoice; sólo requiere IA.
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
                "para poblar automáticamente los modelos/años de las marcas chinas."
            ),
        }

    # Marcas pendientes (distintas) marcadas como necesita_completar.
    marcas = [
        m[0]
        for m in db.query(models.CatalogoVehiculos.marca)
        .filter(models.CatalogoVehiculos.necesita_completar.is_(True))
        .distinct()
        .all()
    ]
    if limite:
        marcas = marcas[:limite]

    logger.info("=== Completar marcas con IA: %d marca(s) pendiente(s) ===", len(marcas))
    total_filas = 0
    detalle = []
    for marca in marcas:
        modelos = ia_service.inferir_modelos_marca(marca)
        creadas = 0
        for m in modelos:
            modelo = m["modelo"]
            ai, af = m["anio_inicio"], m["anio_fin"]
            anios = range(ai, af + 1) if (ai and af) else [ai]
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
                    creadas += 1
        # Eliminar las filas "placeholder" (marca sin modelo/año) de esta marca,
        # ya que ahora tenemos modelos concretos.
        if modelos:
            db.query(models.CatalogoVehiculos).filter(
                models.CatalogoVehiculos.marca == marca,
                models.CatalogoVehiculos.necesita_completar.is_(True),
                (models.CatalogoVehiculos.modelo == "")
                | (models.CatalogoVehiculos.modelo.is_(None)),
            ).delete(synchronize_session=False)
        db.commit()
        total_filas += creadas
        detalle.append({"marca": marca, "filas_creadas": creadas, "modelos": len(modelos)})
        logger.info("  %s -> %d modelo(s), %d fila(s) creada(s)", marca, len(modelos), creadas)

    logger.info("Completado: %d fila(s) en %d marca(s).", total_filas, len(marcas))
    return {"status": "ok", "marcas": len(marcas), "filas_creadas": total_filas, "detalle": detalle}


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
    parser.add_argument(
        "--completar-marcas",
        action="store_true",
        help=(
            "Puebla con IA el catálogo de vehículos de TODAS las marcas chinas "
            "sin modelos/años (necesita_completar=True), igual que las marcas "
            "occidentales. No consulta CassChoice; sólo requiere GEMINI_API_KEY."
        ),
    )
    parser.add_argument(
        "--sync-total",
        action="store_true",
        help=(
            "CRAWL MASIVO: recorre TODAS las páginas del catálogo de piezas de "
            "CassChoice (query_commodity paginado) y las indexa en la DB. Combínalo "
            "con --limit-pages para pruebas."
        ),
    )
    parser.add_argument(
        "--sin-particion",
        action="store_true",
        help=(
            "Desactiva el particionado en --sync-total (un solo filtro global, "
            "limitado a 10.000 piezas por el tope del API). Sólo para pruebas."
        ),
    )
    parser.add_argument(
        "--contar-catalogo",
        action="store_true",
        help=(
            "Cuenta el catálogo de CassChoice SIN crawlear todas las piezas: "
            "suma el total por marca de repuesto e identifica las marcas que "
            "topan en 10.000. Rápido (~2 min)."
        ),
    )
    parser.add_argument(
        "--contar-exacto",
        action="store_true",
        help=(
            "Con --contar-catalogo: sub-particiona y DEDUPLICA las marcas topadas "
            "para el conteo EXACTO (lento; descarga sus números de parte)."
        ),
    )
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        help="Máximo de páginas por partición en --sync-total (p.ej. 5 para probar).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=None,
        help="Tamaño de página del crawl (por defecto CASS_PAGE_SIZE del .env).",
    )
    parser.add_argument(
        "--reporte-publicables",
        nargs="?",
        const="publicables.csv",
        default=None,
        help=(
            "Genera un CSV de piezas PUBLICABLES (con descripción, precio USD y "
            "fitment completo), listo para vender. Ruta opcional (default: "
            "publicables.csv)."
        ),
    )
    args = parser.parse_args()

    # Asegurar que las tablas existen.
    models.Base.metadata.create_all(bind=database.engine)

    # Modo offline: reporte CSV de piezas publicables (no toca CassChoice).
    if args.reporte_publicables:
        db = database.SessionLocal()
        try:
            resumen = generar_reporte_publicables(db, args.reporte_publicables)
            logger.info(
                "Reporte: %s publicables=%d",
                resumen.get("archivo"), resumen.get("publicables", 0),
            )
        finally:
            db.close()
        logger.info("Sincronización finalizada.")
        return

    # Conteo del catálogo (sin crawl completo).
    if args.contar_catalogo:
        client = CassChoiceClient()
        db = database.SessionLocal()
        try:
            r = contar_catalogo(db, client, exacto_topadas=args.contar_exacto)
            print("\n" + "=" * 70)
            print("CONTEO DEL CATÁLOGO CASSCHOICE")
            print("=" * 70)
            print(f"Marcas de repuesto consultadas: {r['marcas_consultadas']}")
            print(f"Piezas (piso, topadas=10.000):  {r['suma_piso']:,}")
            print(f"Marcas topadas (tienen más):    {len(r['marcas_topadas'])}")
            print(f"  {', '.join(r['marcas_topadas'])}")
            if "total_exacto" in r:
                print(f"\nTOTAL EXACTO (con dedup de topadas): {r['total_exacto']:,}")
                for m, d in sorted(r["exacto_por_marca_topada"].items(),
                                   key=lambda x: -x[1]["piezas_estimadas"]):
                    marca_ok = "exacto" if d["exacto_confiable"] else "piso 10.000"
                    print(f"  {m:20} {d['piezas_estimadas']:>8,}  ({marca_ok})")
            else:
                print("\n(usa --contar-exacto para el conteo exacto de las topadas)")
            print("=" * 70)
        finally:
            db.close()
        logger.info("Conteo finalizado.")
        return

    # Crawl masivo paginado del catálogo de piezas.
    if args.sync_total:
        client = CassChoiceClient()
        db = database.SessionLocal()
        try:
            sincronizar_total(
                db, client,
                limite_paginas=args.limit_pages,
                page_size=args.page_size,
                usar_ia=not args.sin_ia,
                particionar=not args.sin_particion,
            )
        finally:
            db.close()
        logger.info("Sincronización finalizada.")
        return

    # Modo offline: completar marcas (catálogo de vehículos) con IA.
    if args.completar_marcas:
        db = database.SessionLocal()
        try:
            resumen = completar_marcas_faltantes(db)
            logger.info("Resultado: %s", resumen.get("status"))
        finally:
            db.close()
        logger.info("Sincronización finalizada.")
        return

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
