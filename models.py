"""
Modelos SQLAlchemy normalizados para la plataforma e-commerce B2B de repuestos.

Grupos de tablas:
- Catálogo de vehículos y compatibilidades
- Autopartes, códigos y precios (CassChoice)
- Usuarios / autenticación
- E-commerce: carritos, items de carrito, órdenes, items de orden
- Traducciones para búsqueda bilingüe
"""
import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    ForeignKey,
    Float,
    DateTime,
    Boolean,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from database import Base


def _utcnow():
    return datetime.datetime.utcnow()


# ---------------------------------------------------------------------------
# CATÁLOGO DE VEHÍCULOS
# ---------------------------------------------------------------------------
class CatalogoVehiculos(Base):
    """
    Catálogo oficial de vehículos de CassChoice (marca / modelo / año).

    Cada nodo hoja del árbol de CassChoice (make#model#year) se guarda como
    una fila. El ``vehicle_relation_id`` es el identificador único de CassChoice
    (ej. ``BMW#116i#2004``).
    """

    __tablename__ = "catalogo_vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_relation_id = Column(String, unique=True, index=True)
    marca = Column(String, index=True, nullable=False)
    modelo = Column(String, index=True, default="")
    anio = Column(Integer, index=True, nullable=True)
    # True cuando la marca (típicamente china) no trae modelo/año y debe
    # completarse con ayuda de IA.
    necesita_completar = Column(Boolean, default=False, index=True)

    __table_args__ = (
        UniqueConstraint("marca", "modelo", "anio", name="uq_vehiculo_marca_modelo_anio"),
    )


# ---------------------------------------------------------------------------
# AUTOPARTES
# ---------------------------------------------------------------------------
class Autoparte(Base):
    __tablename__ = "autopartes"

    id = Column(Integer, primary_key=True, index=True)

    # Códigos de la pieza
    numero_oem = Column(String, index=True)          # compatibilidad histórica
    codigo_oe = Column(String, index=True)           # código OE
    codigo_oem = Column(String, index=True)          # código OEM
    codigo_aftermarket = Column(String, index=True)  # código aftermarket

    marca = Column(String, index=True)      # marca del repuesto (ej. CHERY)
    modelo = Column(String, index=True)     # modelo al que aplica (opcional)
    descripcion = Column(String)
    categoria = Column(String, index=True)
    imagen_url = Column(String)
    calidad = Column(String)                # ORIGINAL / OEM / AFTERMARKET

    # Precios
    precio_fob = Column(Float)                    # precio base FOB (USD)
    precio_venta_calculado = Column(Float)        # precio_fob * (1 + margen)

    necesita_completar = Column(Boolean, default=False, index=True)
    fecha_actualizacion = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    compatibilidades = relationship(
        "Compatibilidad", back_populates="autoparte", cascade="all, delete-orphan"
    )
    precios = relationship(
        "PrecioCassChoice", back_populates="autoparte", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_autoparte_codigos", "codigo_oe", "codigo_oem", "codigo_aftermarket"),
    )


class Compatibilidad(Base):
    """Relación N:N entre una autoparte y un vehículo (marca/modelo/rango de años)."""

    __tablename__ = "compatibilidades"

    id = Column(Integer, primary_key=True, index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"), index=True)

    marca_vehiculo = Column(String, index=True)
    modelo_vehiculo = Column(String, index=True)
    anio_inicio = Column(Integer)
    anio_fin = Column(Integer)

    autoparte = relationship("Autoparte", back_populates="compatibilidades")

    __table_args__ = (
        Index("ix_compat_marca_modelo", "marca_vehiculo", "modelo_vehiculo"),
    )


class PrecioCassChoice(Base):
    """Cada oferta/proveedor de precio para una autoparte."""

    __tablename__ = "precios_casschoice"

    id = Column(Integer, primary_key=True, index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"), index=True)
    calidad = Column(String)           # ORIGINAL / OEM / AFTERMARKET
    marca_repuesto = Column(String)    # nombre de la marca (ej. CHERY)
    precio_fob = Column(Float)
    precio_venta = Column(Float)       # con margen aplicado
    moneda = Column(String, default="USD")
    disponibilidad = Column(String)
    store_name = Column(String)
    ultima_actualizacion = Column(DateTime, default=_utcnow)

    autoparte = relationship("Autoparte", back_populates="precios")


# ---------------------------------------------------------------------------
# USUARIOS / AUTENTICACIÓN
# ---------------------------------------------------------------------------
class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    nombre = Column(String)
    tipo_cliente = Column(String, default="B2B")  # B2B / B2C / ADMIN
    activo = Column(Boolean, default=True)
    fecha_registro = Column(DateTime, default=_utcnow)

    carritos = relationship("Carrito", back_populates="usuario", cascade="all, delete-orphan")
    ordenes = relationship("Orden", back_populates="usuario", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# E-COMMERCE
# ---------------------------------------------------------------------------
class Carrito(Base):
    __tablename__ = "carritos"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True)
    activo = Column(Boolean, default=True)
    fecha_creacion = Column(DateTime, default=_utcnow)

    usuario = relationship("Usuario", back_populates="carritos")
    items = relationship(
        "ItemCarrito", back_populates="carrito", cascade="all, delete-orphan"
    )


class ItemCarrito(Base):
    __tablename__ = "items_carrito"

    id = Column(Integer, primary_key=True, index=True)
    carrito_id = Column(Integer, ForeignKey("carritos.id"), index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"), index=True)
    cantidad = Column(Integer, default=1)

    carrito = relationship("Carrito", back_populates="items")
    autoparte = relationship("Autoparte")

    __table_args__ = (
        UniqueConstraint("carrito_id", "autoparte_id", name="uq_item_carrito"),
    )


class Orden(Base):
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), index=True)
    estado = Column(String, default="Pendiente", index=True)
    total = Column(Float, default=0.0)
    fecha_creacion = Column(DateTime, default=_utcnow)

    usuario = relationship("Usuario", back_populates="ordenes")
    items = relationship(
        "ItemOrden", back_populates="orden", cascade="all, delete-orphan"
    )


class ItemOrden(Base):
    __tablename__ = "items_orden"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"), index=True)
    cantidad = Column(Integer, default=1)
    precio_unitario = Column(Float)

    orden = relationship("Orden", back_populates="items")
    autoparte = relationship("Autoparte")


# ---------------------------------------------------------------------------
# TRADUCCIONES (búsqueda bilingüe ES/EN)
# ---------------------------------------------------------------------------
class TraduccionParte(Base):
    __tablename__ = "traducciones_partes"

    id = Column(Integer, primary_key=True, index=True)
    termino_es = Column(String, index=True, nullable=False)
    termino_en = Column(String, index=True, nullable=False)
    categoria = Column(String, index=True)

    __table_args__ = (
        UniqueConstraint("termino_es", "termino_en", name="uq_traduccion"),
    )
