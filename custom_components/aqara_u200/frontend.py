"""Bundled frontend registration for Aqara U200."""

from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, FRONTEND_MODULE_URL, FRONTEND_URL_PATH

_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the bundled Lovelace card once per HA process.

    The static path is served with ``cache_headers=True`` (long-lived
    caching) but the card's filename never changes between releases — so
    without a cache-busting suffix, every browser/companion-app that ever
    loaded an older version keeps serving it from cache indefinitely, even
    after a restart and a manual page reload (confirmed live 2026-08-31: a
    fresh install of 0.13.0-beta.1 still served the 0.12.0 card verbatim).
    Appending the installed integration version as a query string forces a
    new URL — and therefore a fresh fetch — on every version bump, while
    still caching normally within one version.
    """
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL_PATH,
                str(_FRONTEND_DIR),
                cache_headers=True,
            )
        ]
    )

    integration = await async_get_integration(hass, DOMAIN)
    module_url = f"{FRONTEND_MODULE_URL}?v={integration.version}"

    module_urls = hass.data[DATA_EXTRA_MODULE_URL]
    if module_url not in module_urls.urls:
        module_urls.add(module_url)
