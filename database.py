"""
Configuración de la base de datos (SQLAlchemy).

La conexión se define mediante la variable de entorno ``DATABASE_URL``.

- Producción / Docker: usar PostgreSQL, ej.
  ``postgresql+psycopg2://postgres:admin123@db:5432/repuestos_db``
- Desarrollo local sin PostgreSQL: si ``DATABASE_URL`` no está definida se
  utiliza automáticamente un archivo SQLite (``partsbot.db``) para que el
  proyecto arranque sin dependencias externas.

Toda la configuración sensible se lee desde variables de entorno (ver
``config.py`` y ``.env.example``).
"""
import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

logger = logging.getLogger("partsbot.database")

SQLALCHEMY_DATABASE_URL = settings.database_url

# SQLite necesita un argumento especial para permitir el uso en varios hilos
# (FastAPI atiende peticiones en un pool de hilos).
connect_args = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

logger.info("Conectando a la base de datos: %s", SQLALCHEMY_DATABASE_URL.split("@")[-1])

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    """Dependencia de FastAPI que entrega una sesión de base de datos."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
