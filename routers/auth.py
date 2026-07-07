"""Endpoints de autenticación: registro, login y perfil."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import models
import database
import schemas
import security

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/registro", response_model=schemas.TokenResponse, status_code=201)
def registro(payload: schemas.RegistroRequest, db: Session = Depends(database.get_db)):
    email = payload.email.lower().strip()
    existente = db.query(models.Usuario).filter(models.Usuario.email == email).first()
    if existente:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    usuario = models.Usuario(
        email=email,
        password_hash=security.hash_password(payload.password),
        nombre=(payload.nombre or "").strip() or None,
        tipo_cliente=payload.tipo_cliente or "B2B",
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    token = security.crear_access_token({"sub": str(usuario.id), "email": usuario.email})
    return {"access_token": token, "token_type": "bearer", "usuario": usuario}


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(database.get_db)):
    email = payload.email.lower().strip()
    usuario = db.query(models.Usuario).filter(models.Usuario.email == email).first()
    if not usuario or not security.verify_password(payload.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    if not usuario.activo:
        raise HTTPException(status_code=403, detail="Usuario inactivo")

    token = security.crear_access_token({"sub": str(usuario.id), "email": usuario.email})
    return {"access_token": token, "token_type": "bearer", "usuario": usuario}


@router.get("/perfil", response_model=schemas.UsuarioOut)
def perfil(usuario: models.Usuario = Depends(security.get_current_user)):
    return usuario
