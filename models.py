from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Autoparte(Base):
    __tablename__ = "autopartes"
    
    id = Column(Integer, primary_key=True, index=True)
    numero_oem = Column(String, index=True)
    marca = Column(String, index=True)  # Marca del repuesto
    modelo = Column(String, index=True) # Modelo al que aplica
    descripcion = Column(String)
    
    compatibilidades = relationship("Compatibilidad", back_populates="autoparte", cascade="all, delete-orphan")
    precios = relationship("PrecioCassChoice", back_populates="autoparte", cascade="all, delete-orphan")

class Compatibilidad(Base):
    __tablename__ = "compatibilidades"
    
    id = Column(Integer, primary_key=True, index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"))
    
    marca_vehiculo = Column(String, index=True)
    modelo_vehiculo = Column(String, index=True)
    anio_inicio = Column(Integer)
    anio_fin = Column(Integer)
    
    autoparte = relationship("Autoparte", back_populates="compatibilidades")

class PrecioCassChoice(Base):
    __tablename__ = "precios_casschoice"
    
    id = Column(Integer, primary_key=True, index=True)
    autoparte_id = Column(Integer, ForeignKey("autopartes.id"))
    calidad = Column(String)         # Nueva columna para ver si es ORIGINAL/OEM
    marca_repuesto = Column(String)  # Nombre de la marca (ej: CHERY)
    precio_fob = Column(Float)
    disponibilidad = Column(String)
    ultima_actualizacion = Column(DateTime, default=datetime.datetime.utcnow)
    
    autoparte = relationship("Autoparte", back_populates="precios")

class CatalogoVehiculos(Base):
    """
    Esta tabla almacenará el catálogo oficial de marcas y modelos 
    de CassChoice para validar consultas instantáneamente.
    """
    __tablename__ = "catalogo_vehiculos"
    
    id = Column(Integer, primary_key=True, index=True)
    marca = Column(String, index=True)
    modelo = Column(String, index=True)