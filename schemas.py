"""Esquemas Pydantic para validación de entrada/salida de la API."""
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


# --- Auth ---
class RegistroRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    nombre: Optional[str] = None
    tipo_cliente: str = "B2B"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: "UsuarioOut"


class UsuarioOut(BaseModel):
    id: int
    email: EmailStr
    nombre: Optional[str] = None
    tipo_cliente: str

    class Config:
        from_attributes = True


# --- Carrito ---
class AgregarItemRequest(BaseModel):
    autoparte_id: int
    cantidad: int = Field(default=1, ge=1)


class ActualizarItemRequest(BaseModel):
    autoparte_id: int
    cantidad: int = Field(ge=0)


# --- Búsqueda semántica ---
class BusquedaSemanticaRequest(BaseModel):
    termino: str
    marca: Optional[str] = None
    modelo: Optional[str] = None
    anio: Optional[int] = None


# --- IA ---
class CompletarDatosRequest(BaseModel):
    # Si se pasa vehiculo_id se completa ese vehículo; si no, se procesan
    # los primeros ``limite`` vehículos marcados como necesita_completar.
    vehiculo_id: Optional[int] = None
    limite: int = 10


class CompletarFitmentRequest(BaseModel):
    # Si se pasa autoparte_id se completa esa pieza; si no, se procesan las
    # primeras ``limite`` piezas SIN compatibilidades (típicas de marcas chinas).
    autoparte_id: Optional[int] = None
    limite: int = 10


# --- Sincronización manual ---
class CatalogoRequest(BaseModel):
    items: list


TokenResponse.model_rebuild()
