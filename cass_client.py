"""
Cliente HTTP para la API de CassChoice (Frappe / merchant_app).

Encapsula la autenticación (sid + CSRF token) y los dos endpoints usados:
- list_vehicle_relations: árbol de vehículos (marca > modelo > año).
- query_commodity: detalle de piezas + precios a partir de números de parte.

Las credenciales se leen desde variables de entorno (config.settings).
"""
import logging
from typing import List, Optional

import requests

from config import settings

logger = logging.getLogger("partsbot.cass_client")


class CassChoiceError(Exception):
    pass


class CassChoiceClient:
    def __init__(
        self,
        sid: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.sid = sid or settings.cass_sid
        self.token = token or settings.cass_token
        self.timeout = timeout
        if not self.sid:
            logger.warning(
                "CASS_SID no está configurado. Configura las credenciales en .env "
                "para poder sincronizar con CassChoice."
            )

    @property
    def _headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
            ),
            "X-Frappe-CSRF-Token": self.token,
            "Referer": settings.cass_base_url.rstrip("/") + "/store/",
            "Content-Type": "application/json",
        }

    @property
    def _cookies(self) -> dict:
        return {"sid": self.sid, "x-frappe-csrf-token": self.token}

    def listar_vehiculos(self) -> list:
        """Devuelve el árbol de relaciones de vehículos (lista de nodos)."""
        logger.info("Descargando catálogo de vehículos de CassChoice...")
        try:
            resp = requests.get(
                settings.cass_vehicles_url,
                headers=self._headers,
                cookies=self._cookies,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CassChoiceError(f"Error de red al listar vehículos: {exc}") from exc

        if resp.status_code != 200:
            raise CassChoiceError(
                f"CassChoice devolvió {resp.status_code} al listar vehículos"
            )
        data = resp.json().get("message", {})
        # La API puede devolver {'data': [...]} o directamente una lista.
        if isinstance(data, dict):
            return data.get("data", [])
        if isinstance(data, list):
            return data
        return []

    def query_commodity(self, parts_numbers: List[str]) -> list:
        """
        Consulta el detalle de piezas para una lista de números de parte.
        Devuelve la lista ``results`` (una entrada por número consultado).
        """
        if not parts_numbers:
            return []
        logger.info("query_commodity para %d número(s) de parte", len(parts_numbers))
        try:
            resp = requests.post(
                settings.cass_query_commodity_url,
                json={"partsNumbers": parts_numbers},
                headers=self._headers,
                cookies=self._cookies,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CassChoiceError(f"Error de red en query_commodity: {exc}") from exc

        if resp.status_code != 200:
            raise CassChoiceError(
                f"CassChoice devolvió {resp.status_code} en query_commodity: {resp.text[:200]}"
            )
        msg = resp.json().get("message", {})
        if not isinstance(msg, dict) or msg.get("code") not in (200, None):
            logger.warning("query_commodity respuesta inesperada: %s", str(msg)[:200])
        data = msg.get("data") or {}
        return data.get("results", []) if isinstance(data, dict) else []
