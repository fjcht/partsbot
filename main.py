"""
Aplicación FastAPI — Plataforma e-commerce B2B de repuestos (FCH AutoLab).

Punto de entrada que registra todos los routers, configura CORS y sirve el
frontend estático (index.html).
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import models
import database
from config import settings
from routers import auth, catalogo, carrito, ordenes, ia, sincronizacion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("partsbot")

app = FastAPI(
    title="PartsBot — Plataforma e-commerce B2B de Repuestos",
    description="Middleware de inteligencia de repuestos e integración con CassChoice.",
    version="2.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear tablas al iniciar (idempotente).
models.Base.metadata.create_all(bind=database.engine)

# Registrar routers.
app.include_router(auth.router)
app.include_router(catalogo.router)
app.include_router(carrito.router)
app.include_router(ordenes.router)
app.include_router(ia.router)
app.include_router(sincronizacion.router)


@app.get("/api/health", tags=["Salud"])
def health():
    return {"status": "ok", "version": "2.0.0", "margen": settings.margen_ganancia}


@app.get("/", include_in_schema=False)
def index():
    ruta = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(ruta):
        return FileResponse(ruta)
    return JSONResponse({"mensaje": "PartsBot API activa. Visita /docs para la documentación."})
