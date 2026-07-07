"""
Servicio de IA para inferir compatibilidades (fitment) de autopartes.

Contexto del problema
----------------------
CassChoice NO entrega modelos ni años para muchas piezas de marcas chinas:
la respuesta de ``query_commodity`` trae ``vehicle_details: []`` vacío.
Sin embargo, sí conocemos:
  - el número de parte (a menudo con un prefijo de familia de motor, p.ej.
    "F4J16-..." = motor CHERY 1.6T),
  - la(s) marca(s) compatibles (CHERY, JETOUR, ...),
  - la descripción / categoría (p.ej. "Ignition coil").

Con esos datos, un modelo de lenguaje puede inferir con buena precisión los
modelos y rangos de años concretos a los que aplica la pieza. Este módulo
encapsula esa inferencia de forma agnóstica al proveedor.

Proveedores soportados (en orden de preferencia):
  1. Google Gemini  (si ``GEMINI_API_KEY`` está configurada) -> uso local del cliente.
  2. Abacus.AI      (si ``ABACUS_API_KEY`` está en el entorno) -> útil en la nube.

Si no hay ningún proveedor disponible, las funciones devuelven [] sin fallar,
de modo que la sincronización nunca se rompe por falta de IA.
"""
import json
import logging
import os
import re
from typing import List, Optional

from config import settings

logger = logging.getLogger("partsbot.ia_service")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _extraer_json_lista(texto: str) -> list:
    """Extrae el primer bloque JSON tipo lista de un texto arbitrario."""
    if not texto:
        return []
    inicio = texto.find("[")
    fin = texto.rfind("]")
    if inicio >= 0 and fin > inicio:
        try:
            return json.loads(texto[inicio : fin + 1])
        except json.JSONDecodeError:
            # Intento de limpieza de comas colgantes.
            fragmento = re.sub(r",\s*]", "]", texto[inicio : fin + 1])
            try:
                return json.loads(fragmento)
            except json.JSONDecodeError:
                logger.warning("No se pudo parsear JSON de la IA.")
    return []


def _normalizar_fitment(items: list) -> List[dict]:
    """Valida y normaliza la lista de fitment devuelta por la IA."""
    salida = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        marca = (str(it.get("marca") or "")).strip().upper()
        modelo = (str(it.get("modelo") or "")).strip()
        if not marca or not modelo:
            continue
        ai = it.get("anio_inicio")
        af = it.get("anio_fin") or ai
        try:
            ai = int(ai) if ai is not None else None
            af = int(af) if af is not None else ai
        except (ValueError, TypeError):
            ai = af = None
        if ai and af and af < ai:
            ai, af = af, ai
        salida.append(
            {"marca": marca, "modelo": modelo, "anio_inicio": ai, "anio_fin": af}
        )
    return salida


def _construir_prompt(numero_parte: str, marcas: List[str], descripcion: str) -> str:
    marcas_txt = ", ".join(sorted(set(m for m in marcas if m))) or "desconocida"
    prefijo = numero_parte.split("-")[0] if "-" in numero_parte else numero_parte[:5]
    return (
        "Eres un experto en catálogos de autopartes, especialmente de marcas "
        "chinas (CHERY, JETOUR, CHANGAN, GEELY, GREATWALL, HAVAL, MG, BYD, etc.).\n\n"
        f"Pieza a analizar:\n"
        f"- Número de parte: {numero_parte}\n"
        f"- Prefijo/familia: {prefijo}\n"
        f"- Descripción: {descripcion or 'no especificada'}\n"
        f"- Marcas compatibles según proveedor: {marcas_txt}\n\n"
        "Tarea: determina los modelos y rangos de años concretos de vehículos "
        "que utilizan esta pieza. Considera plataformas y motores compartidos "
        "entre marcas del mismo grupo. Sé conservador: incluye solo modelos "
        "reales que existan.\n\n"
        "Responde ÚNICAMENTE con JSON válido, sin texto adicional, con la forma:\n"
        '[{"marca":"CHERY","modelo":"Tiggo 8","anio_inicio":2020,"anio_fin":2024}]\n'
        "Máximo 12 entradas."
    )


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------
def _inferir_gemini(prompt: str) -> Optional[str]:
    if not settings.gemini_api_key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("Proveedor Gemini falló: %s", exc)
        return None


def _inferir_abacus(prompt: str) -> Optional[str]:
    if not os.getenv("ABACUS_API_KEY"):
        return None
    try:
        import abacusai

        client = abacusai.ApiClient()
        resp = client.evaluate_prompt(
            prompt=prompt,
            system_message="Responde solo con JSON válido, sin explicaciones.",
            llm_name="OPENAI_GPT4O",
        )
        return resp.content
    except Exception as exc:  # noqa: BLE001
        logger.warning("Proveedor Abacus.AI falló: %s", exc)
        return None


def hay_ia_disponible() -> bool:
    return bool(settings.gemini_api_key or os.getenv("ABACUS_API_KEY"))


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def inferir_fitment(
    numero_parte: str,
    marcas: List[str],
    descripcion: str = "",
) -> List[dict]:
    """
    Infiere la lista de vehículos compatibles (marca/modelo/rango de años)
    para una pieza cuyo ``vehicle_details`` viene vacío desde CassChoice.

    Devuelve una lista de dicts:
        [{"marca","modelo","anio_inicio","anio_fin"}, ...]
    Lista vacía si no hay proveedor de IA o si la inferencia falla.
    """
    if not hay_ia_disponible():
        logger.info(
            "Sin proveedor de IA (configura GEMINI_API_KEY). Se omite inferencia "
            "de fitment para %s.",
            numero_parte,
        )
        return []

    prompt = _construir_prompt(numero_parte, marcas, descripcion)
    texto = _inferir_gemini(prompt) or _inferir_abacus(prompt)
    if not texto:
        return []
    fitment = _normalizar_fitment(_extraer_json_lista(texto))
    logger.info(
        "IA infirió %d compatibilidad(es) para %s.", len(fitment), numero_parte
    )
    return fitment
