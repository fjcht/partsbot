"""
Lógica de negocio reutilizable: agrupación de años, traducción bilingüe,
serialización de autopartes y búsqueda.
"""
from typing import List, Optional, Dict

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models


# ---------------------------------------------------------------------------
# Agrupación de años en rangos
# ---------------------------------------------------------------------------
def agrupar_anios(anios: List[Optional[int]]) -> List[Dict]:
    """
    Convierte una lista de años en rangos contiguos.
    Ej: [2012, 2013, 2014, 2018] -> [{desde:2012,hasta:2014}, {desde:2018,hasta:2018}]
    """
    limpios = sorted({a for a in anios if a})
    if not limpios:
        return []
    rangos = []
    inicio = prev = limpios[0]
    for a in limpios[1:]:
        if a == prev + 1:
            prev = a
        else:
            rangos.append({"desde": inicio, "hasta": prev})
            inicio = prev = a
    rangos.append({"desde": inicio, "hasta": prev})
    return rangos


def formatear_rango(marca: str, modelo: str, rango: Dict) -> str:
    """Devuelve 'Toyota Corolla (2012-2015)' o 'Toyota Corolla (2012)'."""
    base = f"{marca} {modelo}".strip()
    desde, hasta = rango.get("desde"), rango.get("hasta")
    if not desde and not hasta:
        return base
    if desde == hasta:
        return f"{base} ({desde})"
    return f"{base} ({desde}-{hasta})"


def compatibilidades_agrupadas(compatibilidades) -> List[Dict]:
    """
    Agrupa una lista de objetos Compatibilidad por (marca, modelo) y colapsa
    los años en rangos legibles.
    """
    por_vehiculo: Dict[tuple, List[Optional[int]]] = {}
    origen_por_vehiculo: Dict[tuple, str] = {}
    for c in compatibilidades:
        clave = (c.marca_vehiculo or "", c.modelo_vehiculo or "")
        por_vehiculo.setdefault(clave, [])
        # Registrar el origen del dato (si alguno es de IA, se marca como "ia").
        origen = getattr(c, "origen", None) or "casschoice"
        if origen_por_vehiculo.get(clave) != "ia":
            origen_por_vehiculo[clave] = origen
        # Expandir el rango almacenado (anio_inicio..anio_fin) a años.
        if c.anio_inicio and c.anio_fin:
            por_vehiculo[clave].extend(range(c.anio_inicio, c.anio_fin + 1))
        elif c.anio_inicio:
            por_vehiculo[clave].append(c.anio_inicio)

    resultado = []
    for (marca, modelo), anios in sorted(por_vehiculo.items()):
        origen = origen_por_vehiculo.get((marca, modelo), "casschoice")
        estimado = origen == "ia"
        rangos = agrupar_anios(anios)
        if not rangos:
            resultado.append(
                {
                    "marca": marca,
                    "modelo": modelo,
                    "anios": [],
                    "etiqueta": f"{marca} {modelo}".strip(),
                    "origen": origen,
                    "estimado_ia": estimado,
                }
            )
        else:
            for r in rangos:
                resultado.append(
                    {
                        "marca": marca,
                        "modelo": modelo,
                        "desde": r["desde"],
                        "hasta": r["hasta"],
                        "etiqueta": formatear_rango(marca, modelo, r),
                        "origen": origen,
                        "estimado_ia": estimado,
                    }
                )
    return resultado


# ---------------------------------------------------------------------------
# Serialización de autopartes
# ---------------------------------------------------------------------------
def serializar_autoparte(parte: models.Autoparte) -> Dict:
    return {
        "id": parte.id,
        "numero_oem": parte.numero_oem,
        "codigo_oe": parte.codigo_oe,
        "codigo_oem": parte.codigo_oem,
        "codigo_aftermarket": parte.codigo_aftermarket,
        "marca": parte.marca,
        "modelo": parte.modelo,
        "descripcion": parte.descripcion,
        "categoria": parte.categoria,
        "calidad": parte.calidad,
        "imagen_url": parte.imagen_url,
        "precio_fob": parte.precio_fob,
        "precio_venta": parte.precio_venta_calculado,
        "precio": parte.precio_venta_calculado,  # alias para el frontend
        "moneda": "USD",
        "necesita_completar": parte.necesita_completar,
        "compatibilidades": compatibilidades_agrupadas(parte.compatibilidades),
        "precios": [
            {
                "calidad": p.calidad,
                "marca_repuesto": p.marca_repuesto,
                "precio_fob": p.precio_fob,
                "precio_venta": p.precio_venta,
                "moneda": p.moneda,
                "disponibilidad": p.disponibilidad,
                "store_name": p.store_name,
            }
            for p in parte.precios
        ],
    }


# ---------------------------------------------------------------------------
# Traducción bilingüe
# ---------------------------------------------------------------------------
def expandir_terminos_bilingue(db: Session, termino: str) -> List[str]:
    """
    Dado un término (ES o EN) devuelve el conjunto de sinónimos en ambos
    idiomas usando la tabla traducciones_partes.
    """
    if not termino:
        return []
    t = termino.strip().lower()
    terminos = {t}
    filas = (
        db.query(models.TraduccionParte)
        .filter(
            or_(
                func.lower(models.TraduccionParte.termino_es).like(f"%{t}%"),
                func.lower(models.TraduccionParte.termino_en).like(f"%{t}%"),
            )
        )
        .all()
    )
    for f in filas:
        terminos.add(f.termino_es.lower())
        terminos.add(f.termino_en.lower())
    return list(terminos)


# ---------------------------------------------------------------------------
# Búsqueda de autopartes con JOIN correcto
# ---------------------------------------------------------------------------
def buscar_autopartes(
    db: Session,
    marca: Optional[str] = None,
    modelo: Optional[str] = None,
    anio: Optional[int] = None,
    pieza: Optional[str] = None,
    numero_parte: Optional[str] = None,
    terminos_pieza: Optional[List[str]] = None,
    limite: int = 100,
) -> List[models.Autoparte]:
    """
    Búsqueda unificada. Une Autoparte con Compatibilidad cuando se filtra por
    vehículo (marca/modelo/año) y con los códigos/descripcion cuando se filtra
    por pieza o número de parte.
    """
    query = db.query(models.Autoparte).distinct()

    necesita_join_compat = any([marca, modelo, anio])
    if necesita_join_compat:
        query = query.join(
            models.Compatibilidad,
            models.Compatibilidad.autoparte_id == models.Autoparte.id,
        )
        if marca:
            query = query.filter(models.Compatibilidad.marca_vehiculo.ilike(f"%{marca}%"))
        if modelo:
            query = query.filter(models.Compatibilidad.modelo_vehiculo.ilike(f"%{modelo}%"))
        if anio:
            query = query.filter(
                models.Compatibilidad.anio_inicio <= anio,
                models.Compatibilidad.anio_fin >= anio,
            )

    if numero_parte:
        np = f"%{numero_parte}%"
        query = query.filter(
            or_(
                models.Autoparte.numero_oem.ilike(np),
                models.Autoparte.codigo_oe.ilike(np),
                models.Autoparte.codigo_oem.ilike(np),
                models.Autoparte.codigo_aftermarket.ilike(np),
            )
        )

    # Búsqueda por texto de pieza (bilingüe si se pasan términos expandidos).
    textos = list(terminos_pieza or [])
    if pieza:
        textos.append(pieza)
    if textos:
        condiciones = []
        for t in textos:
            like = f"%{t}%"
            condiciones.append(models.Autoparte.descripcion.ilike(like))
            condiciones.append(models.Autoparte.categoria.ilike(like))
        query = query.filter(or_(*condiciones))

    return query.limit(limite).all()
