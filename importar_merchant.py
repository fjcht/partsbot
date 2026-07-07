"""
Importador OFFLINE de datos reales de CassChoice a partir de un archivo JSON
capturado del navegador (p. ej. merchant.txt).

Sirve para dos cosas:
  1. Poblar la base de datos con datos REALES sin necesitar credenciales en vivo
     (útil para demostraciones, pruebas y desarrollo).
  2. Validar que la lógica de parseo del sincronizador funciona contra las
     respuestas reales de la API.

Soporta dos formatos dentro del archivo:
  - Respuesta de list_vehicle_relations  -> puebla catalogo_vehiculos.
  - Respuesta de query_commodity          -> puebla autopartes/precios/compatibilidades.

El archivo puede contener uno o varios objetos JSON concatenados (como el
merchant.txt exportado), se detectan y procesan todos.

Uso:
    python importar_merchant.py merchant.txt
    python importar_merchant.py /home/ubuntu/Uploads/merchant.txt
"""
import argparse
import json
import logging
import sys
from typing import List

import database
import models
import sincronizador as sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("partsbot.importador")


def _extraer_objetos_json(texto: str) -> List[dict]:
    """
    Extrae uno o varios objetos JSON de un texto (permite objetos concatenados).
    """
    objetos = []
    decoder = json.JSONDecoder()
    idx = 0
    n = len(texto)
    while idx < n:
        # Saltar espacios en blanco / separadores.
        while idx < n and texto[idx] not in "{[":
            idx += 1
        if idx >= n:
            break
        try:
            obj, fin = decoder.raw_decode(texto, idx)
            objetos.append(obj)
            idx = fin
        except json.JSONDecodeError:
            idx += 1
    return objetos


def _es_respuesta_vehiculos(msg: dict) -> bool:
    data = msg.get("data")
    if isinstance(data, list) and data:
        primero = data[0]
        return isinstance(primero, dict) and "vehicle_relation_id" in primero
    return False


def _es_respuesta_piezas(msg: dict) -> bool:
    data = msg.get("data")
    return isinstance(data, dict) and "results" in data


def importar_vehiculos(db, nodos: list) -> int:
    aplanados = []
    sync._aplanar_vehiculos(nodos, aplanados)
    db.query(models.CatalogoVehiculos).delete()
    db.commit()
    insertados, vistos = 0, set()
    for v in aplanados:
        if not v["marca"]:
            continue
        clave = (v["marca"], v["modelo"], v["anio"])
        if clave in vistos:
            continue
        vistos.add(clave)
        db.add(models.CatalogoVehiculos(
            vehicle_relation_id=v["vehicle_relation_id"],
            marca=v["marca"], modelo=v["modelo"], anio=v["anio"],
            necesita_completar=v["necesita_completar"],
        ))
        insertados += 1
    db.commit()
    logger.info("Vehículos importados: %d", insertados)
    return insertados


def importar_piezas(db, results: list) -> int:
    procesadas = 0
    for entry in results:
        try:
            if sync._procesar_resultado_parte(db, entry):
                procesadas += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("Error importando %s: %s", entry.get("parts_number"), exc)
    logger.info("Piezas importadas: %d", procesadas)
    return procesadas


def main():
    parser = argparse.ArgumentParser(description="Importador offline de merchant.txt")
    parser.add_argument(
        "archivo",
        nargs="?",
        default="merchant.txt",
        help="Ruta al archivo JSON exportado (default: merchant.txt en el directorio actual)",
    )
    args = parser.parse_args()

    try:
        with open(args.archivo, "r", encoding="utf-8") as f:
            texto = f.read()
    except OSError as exc:
        logger.error("No se pudo leer %s: %s", args.archivo, exc)
        sys.exit(1)

    models.Base.metadata.create_all(bind=database.engine)
    objetos = _extraer_objetos_json(texto)
    logger.info("Objetos JSON detectados: %d", len(objetos))

    db = database.SessionLocal()
    total_v = total_p = 0
    try:
        for obj in objetos:
            msg = obj.get("message", obj)
            if not isinstance(msg, dict):
                continue
            if _es_respuesta_vehiculos(msg):
                total_v += importar_vehiculos(db, msg["data"])
            elif _es_respuesta_piezas(msg):
                total_p += importar_piezas(db, msg["data"]["results"])
    finally:
        db.close()

    logger.info("=== Importación finalizada: %d vehículos, %d piezas ===",
                total_v, total_p)


if __name__ == "__main__":
    main()
