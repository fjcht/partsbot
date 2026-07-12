"""
Cliente HTTP para la API de CassChoice (Frappe / merchant_app).

Encapsula la autenticación (sid + CSRF token) y los endpoints usados:
- list_vehicle_relations: árbol de vehículos (marca > modelo > año).
- query_commodity: detalle de piezas + precios a partir de números de parte.
- query_commodity paginado: crawl MASIVO de todas las piezas del catálogo
  recorriendo página por página (total_pages / has_next).

Características de robustez:
- Sesión HTTP persistente (``requests.Session``) que conserva TODAS las cookies
  obtenidas en el login (no sólo ``sid``), evitando errores 500 por sesión
  incompleta.
- Login por formulario (``usr`` / ``pwd``) — el formato original funcional de
  Frappe — con captura del ``sid`` (cookie) y del ``X-Frappe-CSRF-Token``
  (cookie o HTML del store).
- Reintentos con backoff exponencial ante errores de red o respuestas 5xx,
  para que un micro-corte del servidor no detenga un crawl masivo.

Las credenciales se leen desde variables de entorno (config.settings).
"""
import logging
import math
import random
import re
import time
from typing import Iterator, List, Optional

import requests

from config import settings

logger = logging.getLogger("partsbot.cass_client")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


class CassChoiceError(Exception):
    pass


class CassChoiceClient:
    def __init__(
        self,
        sid: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        auto_login: bool = True,
        max_retries: Optional[int] = None,
    ):
        self.sid = sid or settings.cass_sid
        self.token = token or settings.cass_token
        self.timeout = timeout
        self.max_retries = (
            max_retries if max_retries is not None else settings.cass_max_retries
        )
        # Sesión persistente: conserva cookies entre login y llamadas.
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _UA})
        # Si ya tenemos sid/token (de .env) los sembramos en la sesión.
        if self.sid:
            self.session.cookies.set("sid", self.sid)

        # Si no hay sid/token pero SÍ hay usuario/contraseña, iniciar sesión.
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
    # Autenticación automática (Frappe login) — formato formulario usr/pwd
    # ------------------------------------------------------------------
    def login(self, usuario: str, password: str) -> None:
        """
        Inicia sesión en CassChoice (backend Frappe) usando el formato de
        FORMULARIO original que funciona: ``usr`` / ``pwd`` codificados como
        ``application/x-www-form-urlencoded`` (NO JSON).

        Obtiene automáticamente:
          - ``sid``  : cookie de sesión (queda en ``self.session.cookies``).
          - ``token``: X-Frappe-CSRF-Token (cookie ``csrf_token`` o HTML).
        """
        base = settings.cass_base_url.rstrip("/")
        login_url = base + "/api/method/login"
        logger.info("Iniciando sesión en CassChoice como %s ...", usuario)
        try:
            # data=... => envío como formulario (usr/pwd), formato original.
            resp = self.session.post(
                login_url,
                data={"usr": usuario, "pwd": password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CassChoiceError(f"Error de red durante login: {exc}") from exc

        if resp.status_code != 200:
            raise CassChoiceError(
                f"Login rechazado ({resp.status_code}): {resp.text[:200]}"
            )

        # El sid llega como cookie de sesión (queda en la sesión persistente).
        sid = self.session.cookies.get("sid")
        if not sid:
            raise CassChoiceError(
                "Login sin cookie 'sid'. Verifica usuario/contraseña."
            )
        self.sid = sid

        # CSRF token: Frappe puede dejarlo como cookie 'csrf_token' o inyectarlo
        # en el HTML del store (frappe.csrf_token = "...").
        self.token = self.session.cookies.get("csrf_token") or self.token
        if not self.token:
            try:
                page = self.session.get(base + "/store/", timeout=self.timeout)
                m = re.search(
                    r'csrf_token["\']?\s*[:=]\s*["\']([^"\']+)["\']', page.text
                )
                if m:
                    self.token = m.group(1)
            except requests.RequestException:
                pass

        logger.info(
            "Sesión iniciada. sid=%s… token=%s",
            (self.sid or "")[:8],
            "obtenido" if self.token else "no encontrado",
        )

    # ------------------------------------------------------------------
    # Cabeceras / cookies
    # ------------------------------------------------------------------
    def _request_headers(self, json_body: bool = True) -> dict:
        headers = {
            "Referer": settings.cass_base_url.rstrip("/") + "/store/",
        }
        if self.token:
            headers["X-Frappe-CSRF-Token"] = self.token
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    # ------------------------------------------------------------------
    # Petición con reintentos + backoff exponencial
    # ------------------------------------------------------------------
    def _solicitar(
        self,
        metodo: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        contexto: str = "petición",
    ) -> dict:
        """
        Ejecuta una petición HTTP reintentando ante errores de red y respuestas
        5xx (micro-cortes del servidor), con backoff exponencial + jitter.
        Devuelve el JSON decodificado. Lanza CassChoiceError si se agotan los
        reintentos o hay un error no recuperable (4xx).
        """
        ultimo_error = None
        for intento in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    metodo,
                    url,
                    json=json_body,
                    headers=self._request_headers(json_body=json_body is not None),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                ultimo_error = f"error de red: {exc}"
                logger.warning(
                    "%s falló (intento %d/%d): %s",
                    contexto, intento, self.max_retries, ultimo_error,
                )
            else:
                # 5xx => reintentar; 4xx => error definitivo.
                if resp.status_code >= 500:
                    ultimo_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
                    logger.warning(
                        "%s devolvió %d (intento %d/%d), reintentando...",
                        contexto, resp.status_code, intento, self.max_retries,
                    )
                elif resp.status_code >= 400:
                    raise CassChoiceError(
                        f"{contexto} rechazada ({resp.status_code}): {resp.text[:200]}"
                    )
                else:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise CassChoiceError(
                            f"{contexto}: respuesta no es JSON válido: {exc}"
                        ) from exc

            # Backoff exponencial con tope y jitter.
            if intento < self.max_retries:
                espera = min(
                    settings.cass_backoff_base ** intento,
                    settings.cass_backoff_max,
                )
                espera += random.uniform(0, 0.5)
                time.sleep(espera)

        raise CassChoiceError(
            f"{contexto}: se agotaron los {self.max_retries} reintentos. "
            f"Último error: {ultimo_error}"
        )

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    def listar_vehiculos(self) -> list:
        """Devuelve el árbol de relaciones de vehículos (lista de nodos)."""
        logger.info("Descargando catálogo de vehículos de CassChoice...")
        payload = self._solicitar(
            "GET", settings.cass_vehicles_url, contexto="listar vehículos"
        )
        data = payload.get("message", {})
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
        payload = self._solicitar(
            "POST",
            settings.cass_query_commodity_url,
            json_body={"partsNumbers": parts_numbers},
            contexto="query_commodity",
        )
        msg = payload.get("message", {})
        if not isinstance(msg, dict):
            return []
        data = msg.get("data") or {}
        return data.get("results", []) if isinstance(data, dict) else []

    # ------------------------------------------------------------------
    # Crawl MASIVO paginado
    # ------------------------------------------------------------------
    @staticmethod
    def _extraer_paginacion(data: dict, page: int, page_size: int) -> dict:
        """
        Normaliza los campos de paginación de la respuesta, tolerando distintos
        nombres (total_pages/totalPages, has_next/hasNext, results/records/list).
        Si la API sólo entrega ``total``, calcula total_pages y has_next.
        """
        if not isinstance(data, dict):
            return {"results": [], "total": 0, "total_pages": 0, "has_next": False, "page": page}

        def _primero(*claves, default=None):
            for k in claves:
                if k in data and data[k] is not None:
                    return data[k]
            return default

        results = _primero(
            settings.cass_field_results, "results", "records", "list", "items",
            default=[],
        )
        if not isinstance(results, list):
            results = []

        total = _primero(settings.cass_field_total, "total", "count", "totalCount", default=0)
        try:
            total = int(total)
        except (ValueError, TypeError):
            total = 0

        total_pages = _primero(
            settings.cass_field_total_pages, "total_pages", "totalPages", "pages",
        )
        if total_pages is None:
            total_pages = math.ceil(total / page_size) if (total and page_size) else 1
        try:
            total_pages = int(total_pages)
        except (ValueError, TypeError):
            total_pages = 1

        has_next = _primero(settings.cass_field_has_next, "has_next", "hasNext", "hasMore")
        if has_next is None:
            has_next = page < total_pages
        else:
            has_next = bool(has_next)

        return {
            "results": results,
            "total": total,
            "total_pages": total_pages,
            "has_next": has_next,
            "page": page,
        }

    def query_commodity_pagina(
        self,
        page: int = 1,
        page_size: Optional[int] = None,
        filtro: Optional[dict] = None,
    ) -> dict:
        """
        Obtiene UNA página del catálogo masivo de piezas.

        Devuelve un dict normalizado:
            {"results": [...], "total": int, "total_pages": int,
             "has_next": bool, "page": int}

        Los nombres de los parámetros de paginación en el body y de los campos
        de la respuesta son configurables (ver config.Settings), de modo que si
        el endpoint real usa otros nombres basta con ajustarlos en el .env.
        """
        page_size = page_size or settings.cass_page_size
        body = {
            settings.cass_param_page: page,
            settings.cass_param_page_size: page_size,
        }
        if filtro:
            body.update(filtro)

        payload = self._solicitar(
            "POST",
            settings.cass_search_url,
            json_body=body,
            contexto=f"crawl piezas (página {page})",
        )
        msg = payload.get("message", payload)
        data = msg.get("data", msg) if isinstance(msg, dict) else {}
        return self._extraer_paginacion(data, page, page_size)

    def crawl_commodities(
        self,
        limite_paginas: Optional[int] = None,
        page_size: Optional[int] = None,
        filtro: Optional[dict] = None,
        desde_pagina: int = 1,
    ) -> Iterator[dict]:
        """
        Generador que recorre TODAS las páginas del catálogo de piezas usando
        ``total_pages`` / ``has_next``. Emite un dict por página con:
            {"page", "total_pages", "total", "results"}.

        - ``limite_paginas``: máximo de páginas a recorrer (para pruebas, p.ej. 5).
        - Es resiliente: los reintentos con backoff ya viven en ``_solicitar``.
        """
        page_size = page_size or settings.cass_page_size
        page = max(1, desde_pagina)
        paginas_recorridas = 0
        while True:
            info = self.query_commodity_pagina(page, page_size, filtro)
            paginas_recorridas += 1
            logger.info(
                "Página %d/%s — %d resultado(s) (total piezas: %s)",
                info["page"], info["total_pages"] or "?",
                len(info["results"]), info["total"],
            )
            yield info

            if limite_paginas and paginas_recorridas >= limite_paginas:
                logger.info("Límite de páginas alcanzado (%d).", limite_paginas)
                break
            if not info["has_next"]:
                logger.info("No hay más páginas (has_next=False).")
                break
            page += 1
