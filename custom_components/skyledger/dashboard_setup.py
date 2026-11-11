"""Create a starter dashboard once without overwriting user dashboards."""
import json
import logging
from pathlib import Path
from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace.const import LOVELACE_DATA

_LOGGER = logging.getLogger(__name__)
DASHBOARD_PATH = "skyledger-flights"
LEGACY_PATH = "upcoming-flights"


def should_create_dashboard(paths: set[str]) -> bool:
    return not ({DASHBOARD_PATH, LEGACY_PATH} & paths)


async def async_ensure_dashboard(hass) -> None:
    """Create a storage dashboard only if no SkyLedger dashboard exists."""
    if LOVELACE_DATA not in hass.data:
        _LOGGER.warning("Lovelace is unavailable; skipping SkyLedger dashboard")
        return
    data = hass.data[LOVELACE_DATA]
    paths = {path for path in data.dashboards if path}
    if not should_create_dashboard(paths):
        return
    collection = lovelace_dashboard.DashboardsCollection(hass)
    await collection.async_load()
    paths.update(item["url_path"] for item in collection.async_items())
    if not should_create_dashboard(paths):
        return
    config = json.loads((Path(__file__).parent / "dashboard.json").read_text(encoding="utf-8"))
    try:
        item = await collection.async_create_item({
            "url_path": DASHBOARD_PATH, "title": "SkyLedger",
            "icon": "mdi:airplane", "show_in_sidebar": True,
            "require_admin": False,
        })
        storage = lovelace_dashboard.LovelaceStorage(hass, item)
        data.dashboards[DASHBOARD_PATH] = storage
        await storage.async_save(config)
        frontend.async_register_built_in_panel(
            hass, "lovelace", frontend_url_path=DASHBOARD_PATH,
            require_admin=False, show_in_sidebar=True,
            sidebar_title="SkyLedger", sidebar_icon="mdi:airplane",
            config={"mode": "storage"},
        )
    except Exception:
        _LOGGER.exception("SkyLedger dashboard creation failed")
