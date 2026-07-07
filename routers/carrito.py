"""Endpoints de carrito de compras (requieren autenticación)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import database
import schemas
import security

router = APIRouter(prefix="/carrito", tags=["Carrito"])


def _obtener_carrito_activo(db: Session, usuario: models.Usuario) -> models.Carrito:
    carrito = (
        db.query(models.Carrito)
        .filter(models.Carrito.usuario_id == usuario.id, models.Carrito.activo.is_(True))
        .first()
    )
    if not carrito:
        carrito = models.Carrito(usuario_id=usuario.id, activo=True)
        db.add(carrito)
        db.commit()
        db.refresh(carrito)
    return carrito


def _serializar_carrito(carrito: models.Carrito) -> dict:
    items = []
    total = 0.0
    for it in carrito.items:
        parte = it.autoparte
        precio = (parte.precio_venta_calculado or 0.0) if parte else 0.0
        subtotal = precio * it.cantidad
        total += subtotal
        items.append(
            {
                "item_id": it.id,
                "autoparte_id": it.autoparte_id,
                "descripcion": parte.descripcion if parte else None,
                "codigo_oe": parte.codigo_oe if parte else None,
                "imagen_url": parte.imagen_url if parte else None,
                "precio_unitario": precio,
                "cantidad": it.cantidad,
                "subtotal": round(subtotal, 2),
            }
        )
    return {
        "carrito_id": carrito.id,
        "items": items,
        "total": round(total, 2),
        "cantidad_items": sum(i["cantidad"] for i in items),
    }


@router.post("/agregar")
def agregar_item(
    payload: schemas.AgregarItemRequest,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    parte = db.query(models.Autoparte).filter(models.Autoparte.id == payload.autoparte_id).first()
    if not parte:
        raise HTTPException(status_code=404, detail="Autoparte no encontrada")

    carrito = _obtener_carrito_activo(db, usuario)
    item = (
        db.query(models.ItemCarrito)
        .filter(
            models.ItemCarrito.carrito_id == carrito.id,
            models.ItemCarrito.autoparte_id == payload.autoparte_id,
        )
        .first()
    )
    if item:
        item.cantidad += payload.cantidad
    else:
        item = models.ItemCarrito(
            carrito_id=carrito.id,
            autoparte_id=payload.autoparte_id,
            cantidad=payload.cantidad,
        )
        db.add(item)
    db.commit()
    db.refresh(carrito)
    return _serializar_carrito(carrito)


@router.get("/ver")
def ver_carrito(
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    carrito = _obtener_carrito_activo(db, usuario)
    return _serializar_carrito(carrito)


@router.put("/actualizar")
def actualizar_item(
    payload: schemas.ActualizarItemRequest,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    carrito = _obtener_carrito_activo(db, usuario)
    item = (
        db.query(models.ItemCarrito)
        .filter(
            models.ItemCarrito.carrito_id == carrito.id,
            models.ItemCarrito.autoparte_id == payload.autoparte_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado en el carrito")

    if payload.cantidad == 0:
        db.delete(item)
    else:
        item.cantidad = payload.cantidad
    db.commit()
    db.refresh(carrito)
    return _serializar_carrito(carrito)


@router.delete("/eliminar/{autoparte_id}")
def eliminar_item(
    autoparte_id: int,
    db: Session = Depends(database.get_db),
    usuario: models.Usuario = Depends(security.get_current_user),
):
    carrito = _obtener_carrito_activo(db, usuario)
    item = (
        db.query(models.ItemCarrito)
        .filter(
            models.ItemCarrito.carrito_id == carrito.id,
            models.ItemCarrito.autoparte_id == autoparte_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado en el carrito")
    db.delete(item)
    db.commit()
    db.refresh(carrito)
    return _serializar_carrito(carrito)
