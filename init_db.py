"""
Inicialización / migración de la base de datos.

- Crea todas las tablas definidas en ``models.py``.
- Carga (idempotente) el diccionario de traducciones ES/EN para la
  búsqueda bilingüe de piezas.

Uso:
    python init_db.py            # crea tablas + seed de traducciones
    python init_db.py --reset    # BORRA y recrea todas las tablas
"""
import argparse
import logging

import database
import models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("partsbot.init_db")


# Diccionario base ES <-> EN de términos comunes de autopartes.
TRADUCCIONES_SEED = [
    ("pastillas de freno", "brake pads", "Frenos"),
    ("disco de freno", "brake disc", "Frenos"),
    ("freno", "brake", "Frenos"),
    ("balata", "brake pad", "Frenos"),
    ("amortiguador", "shock absorber", "Suspensión"),
    ("suspensión", "suspension", "Suspensión"),
    ("resorte", "spring", "Suspensión"),
    ("rótula", "ball joint", "Suspensión"),
    ("bobina de encendido", "ignition coil", "Encendido"),
    ("bujía", "spark plug", "Encendido"),
    ("filtro de aceite", "oil filter", "Filtros"),
    ("filtro de aire", "air filter", "Filtros"),
    ("filtro de combustible", "fuel filter", "Filtros"),
    ("filtro de habitáculo", "cabin filter", "Filtros"),
    ("correa de distribución", "timing belt", "Motor"),
    ("correa", "belt", "Motor"),
    ("bomba de agua", "water pump", "Motor"),
    ("bomba de aceite", "oil pump", "Motor"),
    ("radiador", "radiator", "Refrigeración"),
    ("termostato", "thermostat", "Refrigeración"),
    ("ventilador", "fan", "Refrigeración"),
    ("alternador", "alternator", "Eléctrico"),
    ("batería", "battery", "Eléctrico"),
    ("motor de arranque", "starter motor", "Eléctrico"),
    ("faro", "headlight", "Iluminación"),
    ("faro delantero", "headlamp", "Iluminación"),
    ("luz trasera", "tail light", "Iluminación"),
    ("intermitente", "turn signal", "Iluminación"),
    ("parachoques", "bumper", "Carrocería"),
    ("paragolpes", "bumper", "Carrocería"),
    ("capó", "hood", "Carrocería"),
    ("guardabarros", "fender", "Carrocería"),
    ("puerta", "door", "Carrocería"),
    ("espejo retrovisor", "side mirror", "Carrocería"),
    ("parabrisas", "windshield", "Carrocería"),
    ("embrague", "clutch", "Transmisión"),
    ("caja de cambios", "gearbox", "Transmisión"),
    ("transmisión", "transmission", "Transmisión"),
    ("junta", "gasket", "Motor"),
    ("empaque", "gasket", "Motor"),
    ("sensor de oxígeno", "oxygen sensor", "Sensores"),
    ("sensor", "sensor", "Sensores"),
    ("inyector", "injector", "Combustible"),
    ("bomba de combustible", "fuel pump", "Combustible"),
    ("silenciador", "muffler", "Escape"),
    ("catalizador", "catalytic converter", "Escape"),
    ("escape", "exhaust", "Escape"),
    ("neumático", "tire", "Ruedas"),
    ("llanta", "wheel", "Ruedas"),
    ("rodamiento", "bearing", "Ruedas"),
    ("balero", "bearing", "Ruedas"),
    ("cremallera de dirección", "steering rack", "Dirección"),
    ("bomba de dirección", "power steering pump", "Dirección"),
    ("aceite", "oil", "Lubricantes"),
    ("bujía de precalentamiento", "glow plug", "Encendido"),
]


def seed_traducciones(db):
    creadas = 0
    for es, en, cat in TRADUCCIONES_SEED:
        existe = (
            db.query(models.TraduccionParte)
            .filter(
                models.TraduccionParte.termino_es == es,
                models.TraduccionParte.termino_en == en,
            )
            .first()
        )
        if not existe:
            db.add(models.TraduccionParte(termino_es=es, termino_en=en, categoria=cat))
            creadas += 1
    db.commit()
    logger.info("Traducciones cargadas (nuevas: %d, total seed: %d)", creadas, len(TRADUCCIONES_SEED))


def crear_tablas(reset: bool = False):
    if reset:
        logger.warning("Eliminando todas las tablas (--reset)...")
        models.Base.metadata.drop_all(bind=database.engine)
    logger.info("Creando tablas...")
    models.Base.metadata.create_all(bind=database.engine)
    logger.info("Tablas creadas correctamente.")


def main():
    parser = argparse.ArgumentParser(description="Inicializa la base de datos de PartsBot")
    parser.add_argument("--reset", action="store_true", help="Borra y recrea las tablas")
    args = parser.parse_args()

    crear_tablas(reset=args.reset)

    db = database.SessionLocal()
    try:
        seed_traducciones(db)
    finally:
        db.close()

    logger.info("Inicialización finalizada.")


if __name__ == "__main__":
    main()
