import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Lógica inteligente: 
# Si existe la variable IS_DOCKER, usa 'db' (configuración de contenedor).
# Si no, asume que estás en tu laptop y usa 'localhost'.
if os.getenv("IS_DOCKER"):
    DB_HOST = "db"
else:
    DB_HOST = "localhost"

# URL de conexión centralizada
SQLALCHEMY_DATABASE_URL = f"postgresql://postgres:admin123@{DB_HOST}:5432/repuestos_db"

print(f"DEBUG: Conectando a la base de datos en host: {DB_HOST}")

# Crear el motor de conexión
# Se añade 'connect_args' para mayor compatibilidad en entornos locales si fuera necesario
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Configurar la sesión
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarar la base para los modelos
Base = declarative_base()

# Función necesaria para las dependencias en tus rutas de FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()