"""
Configuración centralizada leída desde variables de entorno (.env).

Usa pydantic-settings si está disponible; de lo contrario cae a una
implementación mínima basada en ``os.getenv`` para no romper el arranque.
"""
import os
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv es opcional
    pass


def _get(key: str, default=None):
    value = os.getenv(key)
    return value if value is not None and value != "" else default


class Settings:
    """Contenedor de configuración de la aplicación."""

    # --- Base de datos ---
    # Si no se define DATABASE_URL se usa SQLite local (desarrollo).
    database_url: str = _get(
        "DATABASE_URL",
        "sqlite:///./partsbot.db",
    )

    # --- Seguridad / JWT ---
    secret_key: str = _get("SECRET_KEY", "CAMBIAR-ESTE-SECRETO-EN-PRODUCCION")
    algorithm: str = _get("JWT_ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(_get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    # --- CassChoice API ---
    cass_sid: str = _get("CASS_SID", "")
    cass_token: str = _get("CASS_TOKEN", "")
    # Credenciales para login automático (obtienen sid/token sin copiar a mano).
    cass_usuario: str = _get("CASS_USUARIO", "")
    cass_password: str = _get("CASS_PASSWORD", "")
    cass_base_url: str = _get(
        "CASS_BASE_URL", "https://merchant.casschoice.com"
    )
    cass_vehicles_endpoint: str = _get(
        "CASS_VEHICLES_ENDPOINT",
        "/api/method/merchant_app.api.vehicle.VehicleRelationController.list_vehicle_relations",
    )
    cass_query_commodity_endpoint: str = _get(
        "CASS_QUERY_COMMODITY_ENDPOINT",
        "/api/method/merchant_app.api.product.ProductController.query_commodity",
    )
    # Endpoint de BÚSQUEDA/LISTADO paginado de piezas (crawl masivo).
    # Por defecto se reutiliza query_commodity con parámetros de paginación;
    # si CassChoice expone un endpoint de "search commodity" distinto, se puede
    # sobrescribir con CASS_SEARCH_ENDPOINT en el .env.
    cass_search_endpoint: str = _get(
        "CASS_SEARCH_ENDPOINT",
        "/api/method/merchant_app.api.product.ProductController.query_commodity",
    )

    # --- Crawl / paginación ---
    # Tamaño de página para el crawl masivo.
    cass_page_size: int = int(_get("CASS_PAGE_SIZE", "50"))
    # Nombres de los parámetros de paginación en el BODY de la petición.
    cass_param_page: str = _get("CASS_PARAM_PAGE", "page")
    cass_param_page_size: str = _get("CASS_PARAM_PAGE_SIZE", "pageSize")
    # Nombres de los campos de paginación en la RESPUESTA (se auto-detectan
    # varios alias; estos son los preferidos).
    cass_field_total: str = _get("CASS_FIELD_TOTAL", "total")
    cass_field_total_pages: str = _get("CASS_FIELD_TOTAL_PAGES", "total_pages")
    cass_field_has_next: str = _get("CASS_FIELD_HAS_NEXT", "has_next")
    cass_field_results: str = _get("CASS_FIELD_RESULTS", "results")

    # --- Resiliencia (reintentos con backoff exponencial) ---
    cass_max_retries: int = int(_get("CASS_MAX_RETRIES", "4"))
    cass_backoff_base: float = float(_get("CASS_BACKOFF_BASE", "1.5"))
    cass_backoff_max: float = float(_get("CASS_BACKOFF_MAX", "30"))

    # --- Negocio ---
    # Margen aplicado sobre el precio FOB (6% => 0.06).
    margen_ganancia: float = float(_get("MARGEN_GANANCIA", "0.06"))
    moneda_precio: str = _get("MONEDA_PRECIO", "USD")

    # --- IA (opcional) ---
    gemini_api_key: str = _get("GEMINI_API_KEY", "")

    # --- App ---
    api_base_url: str = _get("API_BASE_URL", "http://localhost:8000")

    @property
    def cass_vehicles_url(self) -> str:
        return self.cass_base_url.rstrip("/") + self.cass_vehicles_endpoint

    @property
    def cass_query_commodity_url(self) -> str:
        return self.cass_base_url.rstrip("/") + self.cass_query_commodity_endpoint

    @property
    def cass_search_url(self) -> str:
        return self.cass_base_url.rstrip("/") + self.cass_search_endpoint


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
