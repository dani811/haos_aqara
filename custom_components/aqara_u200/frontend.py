"""Bundled frontend registration for Aqara U200."""

from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import FRONTEND_MODULE_URL, FRONTEND_URL_PATH

_FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and load the bundled Lovelace card once per HA process."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL_PATH,
                str(_FRONTEND_DIR),
                cache_headers=True,
            )
        ]
    )

    module_urls = hass.data[DATA_EXTRA_MODULE_URL]
    if FRONTEND_MODULE_URL not in module_urls.urls:
        module_urls.add(FRONTEND_MODULE_URL)
