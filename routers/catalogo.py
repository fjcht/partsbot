"""Endpoints de consulta de catálogo y búsqueda semántica bilingüe."""
import io
import csv
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional

import models
import database
import schemas
import services

logger = logging.getLogger("partsbot.catalogo")

router = APIRouter(tags=["Catálogo y Búsqueda"])


@router.get("/consultar")
def consultar_repuestos(
    marca: Optional[str] = None,
    modelo: Optional[str] = None,
    anio: Optional[int] = None,
    pieza: Optional[str] = None,
    numero_parte: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    """
    Búsqueda principal. Une Autoparte <-> Compatibilidad <-> CatalogoVehiculos
    y devuelve las piezas con sus compatibilidades agrupadas por rango de años.
    Soporta filtros por marca, modelo, año, nombre de pieza y número de parte.
    """
    try:
        partes = services.buscar_autopartes(
            db,
            marca=marca,
            modelo=modelo,
            anio=anio,
            pieza=pieza,
            numero_parte=numero_parte,
        )

        resultados = [services.serializar_autoparte(p) for p in partes]

        # Vehículos del catálogo que coinciden con la marca/modelo (para mostrar
        # rangos de compatibilidad aunque no haya pieza cargada aún).
        vehiculos_catalogo = []
        if marca or modelo:
            q = db.query(
                models.CatalogoVehiculos.marca,
                models.CatalogoVehiculos.modelo,
                func.min(models.CatalogoVehiculos.anio),
                func.max(models.CatalogoVehiculos.anio),
            )
            if marca:
                q = q.filter(models.CatalogoVehiculos.marca.ilike(f"%{marca}%"))
            if modelo:
                q = q.filter(models.CatalogoVehiculos.modelo.ilike(f"%{modelo}%"))
            q = q.group_by(models.CatalogoVehiculos.marca, models.CatalogoVehiculos.modelo)
            for mk, md, amin, amax in q.limit(200).all():
                rango = {"desde": amin, "hasta": amax}
                vehiculos_catalogo.append(
                    {
                        "marca": mk,
                        "modelo": md,
                        "desde": amin,
                        "hasta": amax,
                        "etiqueta": services.formatear_rango(mk, md or "", rango),
                    }
                )

        return {
            "total": len(resultados),
            "resultados": resultados,
            "vehiculos_catalogo": vehiculos_catalogo,
            "criterios": {
                "marca": marca,
                "modelo": modelo,
                "anio": anio,
                "pieza": pieza,
                "numero_parte": numero_parte,
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en /consultar: %s", exc)
        raise HTTPException(status_code=500, detail="Error interno al procesar la consulta")


@router.post("/busqueda/semantica")
def busqueda_semantica(payload: schemas.BusquedaSemanticaRequest, db: Session = Depends(database.get_db)):
    """
    Búsqueda bilingüe (ES/EN): expande el término con la tabla de traducciones
    y busca autopartes por descripción/categoría además de filtros de vehículo.
    """
    terminos = services.expandir_terminos_bilingue(db, payload.termino)
    partes = services.buscar_autopartes(
        db,
        marca=payload.marca,
        modelo=payload.modelo,
        anio=payload.anio,
        terminos_pieza=terminos,
    )
    return {
        "termino": payload.termino,
        "terminos_expandidos": terminos,
        "total": len(partes),
        "resultados": [services.serializar_autoparte(p) for p in partes],
    }


@router.get("/catalogo/marcas")
def listar_marcas(db: Session = Depends(database.get_db)):
    filas = (
        db.query(models.CatalogoVehiculos.marca)
        .distinct()
        .order_by(models.CatalogoVehiculos.marca)
        .all()
    )
    return {"marcas": [f[0] for f in filas if f[0]]}


@router.get("/catalogo/modelos")
def listar_modelos(marca: str = Query(...), db: Session = Depends(database.get_db)):
    filas = (
        db.query(
            models.CatalogoVehiculos.modelo,
            func.min(models.CatalogoVehiculos.anio),
            func.max(models.CatalogoVehiculos.anio),
        )
        .filter(models.CatalogoVehiculos.marca.ilike(marca))
        .filter(models.CatalogoVehiculos.modelo != "")
        .group_by(models.CatalogoVehiculos.modelo)
        .order_by(models.CatalogoVehiculos.modelo)
        .all()
    )
    return {
        "marca": marca,
        "modelos": [
            {"modelo": m, "anio_min": amin, "anio_max": amax} for m, amin, amax in filas
        ],
    }


@router.get("/exportar_csv")
def exportar_csv(db: Session = Depends(database.get_db)):
    resultados = db.query(models.Autoparte).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Numero OEM", "Codigo OE", "Codigo OEM", "Codigo Aftermarket",
         "Descripcion", "Marca", "Precio FOB", "Precio Venta (con margen)"]
    )
    for p in resultados:
        writer.writerow(
            [p.id, p.numero_oem, p.codigo_oe, p.codigo_oem, p.codigo_aftermarket,
             p.descripcion, p.marca, p.precio_fob, p.precio_venta_calculado]
        )
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventario.csv"},
    )
