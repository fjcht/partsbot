"""
Endpoint de IA para completar datos de marcas (típicamente chinas) que en
CassChoice sólo traen la marca sin modelos ni años.

Usa Google Gemini si ``GEMINI_API_KEY`` está configurada; de lo contrario
devuelve una respuesta informativa sin fallar.
"""
import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import models
import database
import schemas
import security
from config import settings

logger = logging.getLogger("partsbot.ia")

router = APIRouter(prefix="/ia", tags=["IA"])


def _inferir_con_gemini(marca: str) -> list:
    """Devuelve una lista de dicts {modelo, anio_inicio, anio_fin} para la marca."""
    if not settings.gemini_api_key:
        return []
    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            f"Lista los modelos de vehículos más comunes de la marca '{marca}' "
            f"con su rango de años de producción. Responde SOLO con JSON válido "
            f'con esta forma: [{{"modelo": "X", "anio_inicio": 2015, "anio_fin": 2023}}]. '
            f"Máximo 15 modelos."
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        texto = resp.text.strip()
        # Extraer el bloque JSON.
        inicio = texto.find("[")
        fin = texto.rfind("]")
        if inicio >= 0 and fin > inicio:
            return json.loads(texto[inicio : fin + 1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini no disponible o falló para %s: %s", marca, exc)
    return []


@router.post("/completar_datos")
def completar_datos(
    payload: schemas.CompletarDatosRequest,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    """
    Completa modelos/años para vehículos marcados con ``necesita_completar``.
    Requiere autenticación (idealmente un usuario ADMIN).
    """
    query = db.query(models.CatalogoVehiculos).filter(
        models.CatalogoVehiculos.necesita_completar.is_(True)
    )
    if payload.vehiculo_id:
        query = query.filter(models.CatalogoVehiculos.id == payload.vehiculo_id)

    pendientes = query.limit(payload.limite).all()

    if not settings.gemini_api_key:
        return {
            "status": "sin_ia",
            "detalle": (
                "GEMINI_API_KEY no configurada. Configúrala en .env para completar "
                "automáticamente modelos/años de marcas chinas."
            ),
            "pendientes": [{"id": v.id, "marca": v.marca} for v in pendientes],
        }

    completados = []
    for veh in pendientes:
        modelos = _inferir_con_gemini(veh.marca)
        creados = 0
        for m in modelos:
            modelo = (m.get("modelo") or "").strip()
            if not modelo:
                continue
            ai = m.get("anio_inicio")
            af = m.get("anio_fin") or ai
            anios = range(int(ai), int(af) + 1) if ai else [None]
            for anio in anios:
                existe = (
                    db.query(models.CatalogoVehiculos)
                    .filter_by(marca=veh.marca, modelo=modelo, anio=anio)
                    .first()
                )
                if not existe:
                    db.add(
                        models.CatalogoVehiculos(
                            marca=veh.marca,
                            modelo=modelo,
                            anio=anio,
                            necesita_completar=False,
                        )
                    )
                    creados += 1
        veh.necesita_completar = False  # ya procesado
        completados.append({"marca": veh.marca, "modelos_creados": creados})
        db.commit()

    return {"status": "ok", "procesados": len(completados), "detalle": completados}


@router.post("/completar_fitment")
def completar_fitment(
    payload: schemas.CompletarFitmentRequest,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    """
    Completa con IA las compatibilidades (modelo/año) de las piezas que quedaron
    SIN compatibilidades porque CassChoice devolvió ``vehicle_details: []``
    (caso típico de marcas chinas: CHERY, JETOUR, CHANGAN, GEELY, etc.).

    Para cada pieza infiere el fitment a partir del número de parte, la marca y
    la descripción, crea las ``Compatibilidad`` con ``origen='ia'`` y enriquece
    el catálogo de vehículos. Requiere autenticación.
    """
    import ia_service

    # Piezas sin ninguna compatibilidad registrada.
    query = db.query(models.Autoparte)
    if payload.autoparte_id:
        query = query.filter(models.Autoparte.id == payload.autoparte_id)
    else:
        query = query.filter(~models.Autoparte.compatibilidades.any())

    piezas = query.limit(payload.limite).all()

    if not ia_service.hay_ia_disponible():
        return {
            "status": "sin_ia",
            "detalle": (
                "No hay proveedor de IA configurado. Configura GEMINI_API_KEY en "
                "tu archivo .env para inferir automáticamente las compatibilidades "
                "de las marcas chinas."
            ),
            "pendientes": [
                {"id": p.id, "numero_oem": p.numero_oem, "marca": p.marca}
                for p in piezas
            ],
        }

    resultados = []
    for pieza in piezas:
        marcas = [m for m in [pieza.marca] if m]
        fitment = ia_service.inferir_fitment(
            numero_parte=pieza.numero_oem or pieza.codigo_oem or "",
            marcas=marcas,
            descripcion=pieza.descripcion or "",
        )
        creadas = 0
        existentes = {
            (c.marca_vehiculo, c.modelo_vehiculo, c.anio_inicio, c.anio_fin)
            for c in pieza.compatibilidades
        }
        for f in fitment:
            clave = (f["marca"], f["modelo"], f["anio_inicio"], f["anio_fin"])
            if clave in existentes:
                continue
            db.add(
                models.Compatibilidad(
                    autoparte_id=pieza.id,
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
        resultados.append(
            {
                "autoparte_id": pieza.id,
                "numero_oem": pieza.numero_oem,
                "compatibilidades_creadas": creadas,
            }
        )

    return {"status": "ok", "procesados": len(resultados), "detalle": resultados}


def _enriquecer_catalogo(db, marca: str, modelo: str, anio_ini, anio_fin):
    """Inserta en catalogo_vehiculos los modelos/años inferidos (idempotente)."""
    anios = range(anio_ini, anio_fin + 1) if (anio_ini and anio_fin) else [anio_ini]
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
