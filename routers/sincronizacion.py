"""
Endpoints para disparar la sincronización con CassChoice desde la API.
Reutiliza la lógica del módulo ``sincronizador``.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import database
import schemas
import sincronizador
from cass_client import CassChoiceClient, CassChoiceError

logger = logging.getLogger("partsbot.sync_router")

router = APIRouter(prefix="/sincronizar", tags=["Sincronización"])


@router.post("/vehiculos")
def sincronizar_vehiculos(db: Session = Depends(database.get_db)):
    try:
        total = sincronizador.sincronizar_vehiculos(db, CassChoiceClient())
        return {"status": "ok", "vehiculos": total}
    except CassChoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/piezas")
def sincronizar_piezas(payload: schemas.CatalogoRequest, db: Session = Depends(database.get_db)):
    numeros = [str(x) for x in payload.items] if payload.items else []
    if not numeros:
        raise HTTPException(status_code=400, detail="Debes enviar 'items' con números de parte")
    total = sincronizador.sincronizar_piezas(db, CassChoiceClient(), numeros)
    return {"status": "ok", "piezas": total}
