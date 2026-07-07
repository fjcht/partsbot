"""Endpoints de órdenes (checkout). Requieren autenticación."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import database
import security

router = APIRouter(prefix="/ordenes", tags=["Órdenes"])


def _serializar_orden(orden: models.Orden, detalle: bool = False) -> dict:
    data = {
        "id": orden.id,
        "estado": orden.estado,
        "total": round(orden.total or 0.0, 2),
        "fecha_creacion": orden.fecha_creacion.isoformat() if orden.fecha_creacion else None,
        "cantidad_items": len(orden.items),
    }
    if detalle:
        data["items"] = [
            {
                "autoparte_id": it.autoparte_id,
                "descripcion": it.autoparte.descripcion if it.autoparte else None,
                "codigo_oe": it.autoparte.codigo_oe if it.autoparte else None,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "subtotal": round((it.precio_unitario or 0.0) * it.cantidad, 2),
            }
            for it in orden.items
        ]
    return data


@router.post("/crear")
def crear_orden(
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    """Convierte el carrito activo en una orden con estado 'Pendiente'."""
    carrito = (
        db.query(models.Carrito)
        .filter(models.Carrito.usuario_id == usuario.id, models.Carrito.activo.is_(True))
        .first()
    )
    if not carrito or not carrito.items:
        raise HTTPException(status_code=400, detail="El carrito está vacío")

    orden = models.Orden(usuario_id=usuario.id, estado="Pendiente", total=0.0)
    db.add(orden)
    db.commit()
    db.refresh(orden)

    total = 0.0
    for it in carrito.items:
        precio = (it.autoparte.precio_venta_calculado or 0.0) if it.autoparte else 0.0
        total += precio * it.cantidad
        db.add(
            models.ItemOrden(
                orden_id=orden.id,
                autoparte_id=it.autoparte_id,
                cantidad=it.cantidad,
                precio_unitario=precio,
            )
        )
    orden.total = round(total, 2)

    # Cerrar el carrito actual (se creará uno nuevo en la próxima compra).
    carrito.activo = False
    db.commit()
    db.refresh(orden)
    return _serializar_orden(orden, detalle=True)


@router.get("/listar")
def listar_ordenes(
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    ordenes = (
        db.query(models.Orden)
        .filter(models.Orden.usuario_id == usuario.id)
        .order_by(models.Orden.fecha_creacion.desc())
        .all()
    )
    return {"total": len(ordenes), "ordenes": [_serializar_orden(o) for o in ordenes]}


@router.get("/detalle/{orden_id}")
def detalle_orden(
    orden_id: int,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    orden = (
        db.query(models.Orden)
        .filter(models.Orden.id == orden_id, models.Orden.usuario_id == usuario.id)
        .first()
    )
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return _serializar_orden(orden, detalle=True)
