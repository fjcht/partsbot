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
        auto_login: bool = True,
    ):
        self.sid = sid or settings.cass_sid
        self.token = token or settings.cass_token
        self.timeout = timeout

        # Si no hay sid/token pero SÍ hay usuario/contraseña, intentar
        # obtenerlos automáticamente vía login (Frappe).
        if auto_login and (not self.sid or not self.token):
            if settings.cass_usuario and settings.cass_password:
                try:
                    self.login(settings.cass_usuario, settings.cass_password)
                except CassChoiceError as exc:
                    logger.error("Login automático a CassChoice falló: %s", exc)

        if not self.sid:
            logger.warning(
                "CASS_SID no está configurado y no se pudo iniciar sesión "
                "automáticamente. Define CASS_SID/CASS_TOKEN o "
                "CASS_USUARIO/CASS_PASSWORD en .env."
            )

    # ------------------------------------------------------------------
    # Autenticación automática (Frappe login)
    # ------------------------------------------------------------------
    def login(self, usuario: str, password: str) -> None:
        """
        Inicia sesión en CassChoice (backend Frappe) y obtiene automáticamente
        el ``sid`` (cookie de sesión) y el ``X-Frappe-CSRF-Token``.

        Esto evita tener que copiar/pegar manualmente el SID y el token desde
        el navegador: basta con configurar CASS_USUARIO y CASS_PASSWORD en .env.
        """
        base = settings.cass_base_url.rstrip("/")
        login_url = base + "/api/method/login"
        logger.info("Iniciando sesión en CassChoice como %s ...", usuario)
        try:
            sess = requests.Session()
            resp = sess.post(
                login_url,
                data={"usr": usuario, "pwd": password},
                headers={"User-Agent": self._ua},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CassChoiceError(f"Error de red durante login: {exc}") from exc

        if resp.status_code != 200:
            raise CassChoiceError(
                f"Login rechazado ({resp.status_code}): {resp.text[:200]}"
            )

        # El sid llega como cookie de sesión.
        sid = sess.cookies.get("sid")
        if not sid:
            raise CassChoiceError(
                "Login sin cookie 'sid'. Verifica usuario/contraseña."
            )
        self.sid = sid

        # Obtener el CSRF token desde la página del store (Frappe lo inyecta
        # como `frappe.csrf_token = "..."` en el HTML).
        try:
            page = sess.get(base + "/store/", headers={"User-Agent": self._ua},
                            timeout=self.timeout)
            import re
            m = re.search(r'csrf_token["\']?\s*[:=]\s*["\']([^"\']+)["\']', page.text)
            if m:
                self.token = m.group(1)
        except requests.RequestException:
            pass

        logger.info(
            "Sesión iniciada. sid=%s… token=%s",
            (self.sid or "")[:8],
            "obtenido" if self.token else "no encontrado",
        )

    _ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
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
